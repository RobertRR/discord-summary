import discord
from discord.ext import commands, tasks
from google import genai
from google.genai import errors, types # types is required for Part.from_bytes (Multimodal)
import re, asyncio, functools, sys, os, json, logging, hashlib, aiohttp
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, time

# --- VERSION TRACKING ---
# v5.0.4 - TLDW AI Rewrite 📺
# 1. Rewrote !tldw to bypass the failing transcript API.
# 2. Updated !tldw logic to send the YouTube URL directly to Gemini with specific summary and fact-checking instructions.
# 3. Removed youtube_transcript_api dependency.
BOT_VERSION = "v5.0.4 - TLDW AI Rewrite 📺"

# --- GLOBAL START TIME ---
START_TIME = datetime.now()

# NOTE: The raw URL for the GitHub Auto-Sync feature.
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Deages/discord-summary/main/bot.py"

# --- LOGGING CONFIGURATION ---
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
log_file = 'bot_terminal.log'
my_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5*1024*1024, backupCount=5)
my_handler.setFormatter(log_formatter)
my_handler.setLevel(logging.INFO)

app_log = logging.getLogger('root')
app_log.setLevel(logging.INFO)
app_log.addHandler(my_handler)

def log_info(msg):
    """Prints to console with timestamp and writes to the rotating log file."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
    formatted_msg = f"{timestamp} INFO {msg}"
    print(formatted_msg)
    app_log.info(msg)

# --- DATA PERSISTENCE HELPERS ---

def get_changelog():
    """Extracts the VERSION TRACKING section from the source code for Discord output."""
    try:
        with open(__file__, "r") as f:
            content = f.read()
            match = re.search(r"# --- VERSION TRACKING ---\n(.*?)\nBOT_VERSION", content, re.DOTALL)
            if match:
                lines = match.group(1).strip().split('\n')
                cleaned = "\n".join([line.replace('#', '•').strip() for line in lines])
                return cleaned
    except Exception:
        return "No changelog available."

def load_file(filename):
    """Reads text files (tokens/keys) and returns a list of non-empty lines."""
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

def save_text_safe(filename, content):
    """Saves text to disk with fsync to ensure it is committed before a process exit."""
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        log_info(f"Failed to save {filename}: {e}")

def load_json_data(filename):
    """Loads state data (mogg_stats, usage_stats). Returns empty dict on failure."""
    path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f:
            return json.loads(f.read().strip())
    except Exception:
        return {}

def save_json_data(filename, data):
    """Saves data with os.fsync to ensure disk commitment and prevent corruption."""
    path = os.path.join(os.getcwd(), filename)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno()) 
    except Exception as e:
        log_info(f"Save Failed: {e}")

# --- CONFIG & QUOTAS ---

token_list = load_file("discordtoken.txt")
DISCORD_TOKEN = token_list[0] if token_list else None
ALL_KEYS = load_file("keys.txt")
ADMIN_IDS = [int(i) for i in load_file("admins.txt")]

# exhausted_tracker: { "model_name": { key_index: resume_datetime } }
exhausted_tracker = {} 

# General fallback sequence for standard commands. 
MODEL_CHAIN = [
    'gemini-3-flash-preview', 
    'gemini-2.5-flash', 
    'gemini-3.1-flash-lite-preview'
]

# Hard-coded daily limits per key.
DAILY_LIMITS = {
    'gemini-3.1-pro-preview': 5, 
    'gemini-3-flash-preview': 50, 
    'gemini-2.5-flash': 20, 
    'gemini-3.1-flash-lite-preview': 100
}

# --- BOT INITIALIZATION ---

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True         
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

# --- UPDATE UTILITIES ---

def get_file_hash(filepath):
    """Generates a SHA256 hash of a file to detect content changes."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

async def fetch_remote_hash():
    """Fetches remote hash with strict no-cache headers to bypass GitHub CDN."""
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # Timestamp parameter serves as an additional cache-buster.
            async with session.get(f"{GITHUB_RAW_URL}?t={datetime.now().timestamp()}") as resp:
                if resp.status == 200:
                    content = await resp.read()
                    return hashlib.sha256(content).hexdigest()
                log_info(f"Update check HTTP Error: {resp.status}")
    except Exception as e:
        log_info(f"Update check Connection Error: {e}")
    return None

@tasks.loop(minutes=5)
async def check_for_updates():
    """Background task to monitor GitHub."""
    local_hash = get_file_hash(__file__)
    remote_hash = await fetch_remote_hash()
    
    if remote_hash:
        if local_hash != remote_hash:
            log_info(f"AUTO-UPDATE DETECTED: Local[{local_hash[:8]}] vs Remote[{remote_hash[:8]}]")
            # Store hash, type, and attempt count (0)
            save_text_safe("pending_update.txt", f"{remote_hash}|auto|0")
            sys.exit(0)
        else:
            log_info(f"Heartbeat: GitHub Sync Check - No changes found (Remote: {remote_hash[:8]})")

@bot.event
async def on_ready():
    """Startup routine: Validates sync, customized reporting based on update type."""
    log_info(f"--- {bot.user.name} ONLINE ({BOT_VERSION}) ---")
    
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    pending_file = os.path.join(os.getcwd(), "pending_update.txt")
    
    if os.path.exists(pending_file):
        with open(pending_file, "r") as f: 
            raw_pending = f.read().strip()
        
        # Format: hash|type|retries
        parts = raw_pending.split("|")
        expected_hash = parts[0]
        update_type = parts[1] if len(parts) > 1 else "manual"
        retries = int(parts[2]) if len(parts) > 2 else 0

        current_hash = get_file_hash(__file__)
        
        if current_hash != expected_hash:
            if retries < 1:
                log_info(f"Sync mismatch during {update_type} update. Expected {expected_hash[:8]}, found {current_hash[:8]}. Retrying once...")
                save_text_safe("pending_update.txt", f"{expected_hash}|{update_type}|{retries + 1}")
                sys.exit(0)
            else:
                log_info(f"CRITICAL: Sync failed after retry. Expected {expected_hash[:8]}, got {current_hash[:8]}. Aborting loop.")
                os.remove(pending_file)
        else:
            # Hash matches! Update was successful.
            log_info(f"Verified successful {update_type} sync. Posting report...")
            
            if os.path.exists(update_file):
                try:
                    with open(update_file, "r") as f: 
                        chan_id = int(f.read().strip())
                    
                    channel = await bot.fetch_channel(chan_id)
                    if channel:
                        my_member = channel.guild.me if hasattr(channel, "guild") else None
                        perms = channel.permissions_for(my_member) if my_member else None
                        
                        if perms and perms.send_messages:
                            changelog = get_changelog()
                            is_auto = (update_type == "auto")
                            title = "🤖 Auto-Update Successful" if is_auto else "✅ Manual Update Successful"
                            color = 0x9b59b6 if is_auto else 0x3498db
                            
                            if perms.embed_links:
                                embed = discord.Embed(title=title, color=color)
                                embed.add_field(name="Current Version", value=f"`{BOT_VERSION}`", inline=False)
                                if is_auto:
                                    embed.description = "*This update was automatically detected and deployed via GitHub sync.*"
                                embed.add_field(name="Recent Changes", value=changelog, inline=False)
                                await channel.send(embed=embed)
                            else:
                                msg = f"**{title}**\n**Version:** `{BOT_VERSION}`\n"
                                if is_auto: msg += "*(Automatic Sync)*\n"
                                msg += f"**Recent Changes:**\n{changelog}"
                                await channel.send(msg)
                except Exception as e:
                    log_info(f"Reporting error: {e}")
            
            os.remove(pending_file)

    if not check_for_updates.is_running():
        check_for_updates.start()

# --- RANKING SYSTEM ---

def get_rank_class(ratio):
    r = ratio * 100
    if r >= 99.5: return "Immortal"
    if r >= 90: return "Divine"
    if r >= 75: return "Ancient"
    if r >= 55: return "Legend"
    if r >= 40: return "Archon"
    if r >= 30: return "Crusader"
    if r >= 15: return "Guardian"
    if r > 0: return "Herald"
    return "Uncalibrated"

# --- CORE COMMANDS ---

@bot.command(name="help")
async def help_command(ctx):
    help_text = (
        "🤖 **Bot Commands**\n"
        "**`!version`**\n"
        "Shows build version, uptime, and changelog.\n\n"
        "**`!tldr [amount/today]`**\n"
        "Summaries + Cortisol Spike detection. Use 'today' for all msgs since 12am.\n\n"
        "**`!tldw`**\n"
        "**(Reply Required)** Analyzes and fact-checks a YouTube video link via AI query.\n\n"
        "**`!huh`**\n"
        "**(Reply Required)** Explains content and fact-checks a single message.\n\n"
        "**`!arguments [amount/today]`**\n"
        "Conflict Analysis and Mogg updates.\n\n"
        "**`!cortisolcheck @name`**\n"
        "Analyzes user aggression from the last 30m or last 20 messages.\n\n"
        "**`!moggboard`**\n"
        "View the server's dominance hierarchy.\n\n"
        "**`!keystatus`**\n"
        "Check API health and daily quotas.\n\n"
        "----- \n"
        "🛡️ **Admin Commands**\n"
        "**`!clearmogs`**, **`!botlog`**, **`!update`**"
    )
    await ctx.send(help_text)

@bot.command(name="version")
async def version(ctx):
    delta = datetime.now() - START_TIME
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    changelog = get_changelog()
    msg = (f"🤖 **Current Version:** `{BOT_VERSION}`\n⏱️ **Uptime:** `{uptime_str}`\n\n**Recent Changes:**\n{changelog}")
    await ctx.send(msg)

@bot.command(name="moggboard")
async def moggboard(ctx):
    all_data = load_json_data("mogg_stats.json")
    server_data = all_data.get(str(ctx.guild.id), {})
    if not server_data: return await ctx.send("Moggboard is currently empty.")
    sorted_users = sorted(server_data.items(), key=lambda x: (x[1]['wins']/(x[1]['wins']+x[1]['losses'] or 1), x[1]['wins']), reverse=True)
    msg = f"## 👑 {ctx.guild.name.upper()} MOGGBOARD\n"
    for i, (user, stats) in enumerate(sorted_users, 1):
        w, l = stats['wins'], stats['losses']
        ratio = (w / (w+l) if (w+l)>0 else 0)
        msg += f"{i}. **{user}**\n> **Rank:** `{get_rank_class(ratio)}` | **Stats:** `{w}W - {l}L` ({ratio*100:.1f}%)\n\n"
    await ctx.send(msg)

@bot.command(name="huh")
async def huh(ctx):
    if not ctx.message.reference: return await ctx.send("❌ Reply to a message with `!huh`.")
    try: await ctx.message.add_reaction("🔍")
    except: pass
    target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    media_parts = []
    if target.attachments:
        for attachment in target.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                image_data = await attachment.read()
                media_parts.append(types.Part.from_bytes(data=image_data, mime_type='image/jpeg'))
    prompt = (f"CONTEXT: Explain concisely.\nCONTENT: {target.content}\nINSTRUCTIONS:\n1. Summarize in 1-2 short sentences.\n2. Fact check; link primary source if false.\n3. Strict brevity.")
    await process_ai_request(ctx, prompt, "Explanation & Fact-Check", media_parts=media_parts, forced_model='gemini-3.1-pro-preview')

@bot.command(name="cortisolcheck")
async def cortisolcheck(ctx, member: discord.Member):
    """Analyzes a specific user's messages (last 30m or last 20 msgs) for stress/aggression."""
    try: await ctx.message.add_reaction("🧪")
    except: pass

    async with ctx.typing():
        time_limit = datetime.now() - timedelta(minutes=30)
        transcript_list = []
        
        async for msg in ctx.channel.history(after=time_limit, oldest_first=True, limit=500):
            if msg.author.id == member.id:
                transcript_list.append(f"MSG: {msg.content}")

        if not transcript_list:
            async for msg in ctx.channel.history(limit=2000):
                if msg.author.id == member.id:
                    transcript_list.append(f"MSG: {msg.content}")
                    if len(transcript_list) >= 20: break
            transcript_list.reverse()

        if not transcript_list:
            return await ctx.send(f"⚠️ No message history found for **{member.display_name}** in this channel.")

        history_text = "\n".join(transcript_list)
        prompt = (
            f"DIAGNOSTIC DATA: Messages from **{member.display_name}**.\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Analyze if 'cortisol' (aggression, toxicity, shouting, stress) is high.\n"
            f"2. Keep the report extremely short and concise.\n"
            f"3. Use themed emojis for every heading.\n"
            f"4. Do NOT overdo the joke; be blunt and clinical.\n"
            f"5. Do NOT provide a recommended treatment.\n\n"
            f"TRANSCRIPT:\n{history_text}"
        )
        await process_ai_request(ctx, prompt, f"Cortisol Diagnostic: {member.display_name}")

@bot.command(name="tldw")
async def tldw(ctx):
    """Summarizes and fact-checks a YouTube video by sending the URL to Gemini."""
    if not ctx.message.reference:
        return await ctx.send("❌ You must reply to a message containing a YouTube link with `!tldw`.")
    
    try: await ctx.message.add_reaction("📺")
    except: pass

    async with ctx.typing():
        try:
            # Fetch the referenced message
            target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            
            # Extract YouTube URL using regex
            regex = r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=[^ \n&]+|youtu\.be/[^ \n&?]+))"
            match = re.search(regex, target.content)
            
            if not match:
                return await ctx.send("❌ Could not find a valid YouTube link in the replied message.")
            
            video_url = match.group(1)

            prompt = (
                f"VIDEO URL: {video_url}\n\n"
                "INSTRUCTIONS:\n"
                "Provide a short summary of 2-3 sentences at most for what this video is about. "
                "Provide an assessment on whether it is factually accurate in its key messages or if it is misinformation, "
                "providing a credible authorative source reference to support that assessment. "
                "Use bullet points and emojis for the formatting."
            )
            
            # Use Pro model for high-fidelity fact-checking
            await process_ai_request(ctx, prompt, "Video Summary & Fact-Check", forced_model='gemini-3.1-pro-preview')
            
        except Exception as e:
            log_info(f"TLDW Command Error: {e}")
            await ctx.send("⚠️ Error processing the video link analysis.")

@bot.command(name="keystatus")
async def keystatus(ctx):
    now = datetime.now()
    usage = load_json_data("usage_stats.json").get(now.strftime('%Y-%m-%d'), {})
    msg = "### 🔑 API Key & Quota Status\n"
    monitored_models = ['gemini-3.1-pro-preview'] + MODEL_CHAIN
    for model in monitored_models:
        dead = len(exhausted_tracker.get(model, {}))
        used = usage.get(model, 0)
        total = DAILY_LIMITS.get(model, 0) * len(ALL_KEYS)
        msg += f"* **{model}**\n  └ Rate: `{len(ALL_KEYS)-dead}/{len(ALL_KEYS)}` ready | Daily: `{used}/{total}` used\n"
    await ctx.send(msg)

@bot.command(name="clearmogs")
async def clearmogs(ctx):
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    m_data = load_json_data("mogg_stats.json")
    if str(ctx.guild.id) in m_data:
        del m_data[str(ctx.guild.id)]
        save_json_data("mogg_stats.json", m_data)
        await ctx.send("🧹 **Moggboard cleared.**")

@bot.command(name="botlog")
async def botlog(ctx):
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    try:
        with open("bot_terminal.log", "r") as f:
            lines = f.readlines()
            last_10 = "".join(lines[-10:])
            await ctx.send("```text\n" + last_10 + "\n```")
    except Exception: await ctx.send("Log read failed.")

@bot.command(name="update")
async def update(ctx):
    """Saves channel ID and triggers restart for manual update."""
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    
    remote_hash = await fetch_remote_hash()
    if not remote_hash:
        return await ctx.send("❌ Could not connect to GitHub to verify version.")

    await ctx.send("📡 **Manual update initiated. Fetching latest code and recycling container...**")
    
    save_text_safe("update_channel.txt", str(ctx.channel.id))
    # Mark as manual update with 0 retries
    save_text_safe("pending_update.txt", f"{remote_hash}|manual|0")
    
    sys.exit(0)

# --- AI PROCESSING ENGINE ---

async def fetch_history(ctx, args):
    raw_input = args.strip().lower()
    transcript_list = []
    if raw_input == "today":
        today_start = datetime.combine(datetime.now().date(), time.min)
        target_history = ctx.channel.history(after=today_start, oldest_first=True, limit=1000)
    else:
        links = re.findall(r'https://discord\.com/channels/\d+/\d+/(\d+)', raw_input)
        if len(links) >= 2:
            s_id, e_id = sorted([int(links[0]), int(links[1])])
            target_history = ctx.channel.history(after=await ctx.channel.fetch_message(s_id), before=await ctx.channel.fetch_message(e_id), oldest_first=True, limit=300)
        elif ctx.message.reference:
            target_history = ctx.channel.history(after=await ctx.channel.fetch_message(ctx.message.reference.message_id), oldest_first=True, limit=200)
        else:
            numbers = re.findall(r'\d+', raw_input)
            target_history = ctx.channel.history(limit=min(int(numbers[0]) if numbers else 50, 300))
    async for msg in target_history:
        if msg.author.bot or msg.id == ctx.message.id: continue
        rx_str = f" (REACTIONS: {[f'{str(r.emoji)}x{r.count}' for r in msg.reactions]})" if msg.reactions else ""
        transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}{rx_str}")
    return transcript_list

async def process_ai_request(ctx, prompt, title, update_stats=False, media_parts=None, forced_model=None):
    async with ctx.typing():
        response = None
        used_model = ""
        now = datetime.now()
        content_payload = [prompt] + (media_parts if media_parts else [])
        target_models = [forced_model] if forced_model else MODEL_CHAIN
        for model_name in target_models:
            if model_name not in exhausted_tracker: exhausted_tracker[model_name] = {}
            for i, key in enumerate(ALL_KEYS):
                if i in exhausted_tracker[model_name] and now < exhausted_tracker[model_name][i]: continue
                try:
                    client = genai.Client(api_key=key)
                    response = await asyncio.to_thread(client.models.generate_content, model=model_name, contents=content_payload)
                    used_model = model_name
                    today = now.strftime('%Y-%m-%d')
                    data = load_json_data("usage_stats.json")
                    if today not in data: 
                        monitored = ['gemini-3.1-pro-preview'] + MODEL_CHAIN
                        data[today] = {m: 0 for m in monitored}
                    data[today][model_name] = data[today].get(model_name, 0) + 1
                    save_json_data("usage_stats.json", data)
                    break 
                except errors.ClientError as e:
                    if "429" in str(e): 
                        exhausted_tracker[model_name][i] = now + timedelta(seconds=65)
                        continue
                    return await ctx.send(f"⚠️ API Error: `{e}`")
                except Exception: continue
            if response: break
        if not response: return await ctx.send(f"🔄 Quota Error: `{target_models}` exhausted.")
        await ctx.send(f"### {title} for {ctx.author.mention}\n> **Model:** `{used_model}`")
        sections = response.text.split("---SPLIT---")
        if update_stats:
            match = re.search(r"WINNER:\s*([^\s|]+)\s*\|\s*LOSER:\s*([^\s\n\r]+)", sections[-1], re.IGNORECASE)
            if match:
                w, l = match.group(1).strip().rstrip('.,!'), match.group(2).strip().rstrip('.,!')
                m_data = load_json_data("mogg_stats.json")
                s_id = str(ctx.guild.id); m_data.setdefault(s_id, {})
                for p in [w, l]: m_data[s_id].setdefault(p, {"wins": 0, "losses": 0})
                m_data[s_id][w]["wins"] += 1; m_data[s_id][l]["losses"] += 1
                save_json_data("mogg_stats.json", m_data)
                await ctx.send(f"# 🏟️ MOGG LEDGER\n* **Winner:** {w} | **Loser:** {l}")
        for s in sections:
            content = s.strip()
            if content and "WINNER:" not in content:
                for j in range(0, len(content), 1900): await ctx.send(content[j:j+1900])

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    prompt = (f"Summarize conversation grouped by name. Use '---SPLIT---' between sections.\n# 📝 SUMMARIES\nGrouped by User Display Name.\n# 📈 CORTISOL SPIKES\n# MOGG DATA (INTERNAL)\nWINNER: [Name] | LOSER: [Name]\n\nTRANSCRIPT:\n" + "\n".join(transcript))
    await process_ai_request(ctx, prompt, "Summary", update_stats=True)

@bot.command(name="arguments")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def arguments(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    prompt = (f"Analyze arguments. Use '---SPLIT---' between sections:\n1. # 📜 SUMMARY\n2. # 🔍 REVIEW\n3. # ⚖️ VERDICT\n4. MOGG DATA (INTERNAL)\nWINNER: [Name] | LOSER: [Name]\n\nTRANSCRIPT:\n" + "\n".join(transcript))
    await process_ai_request(ctx, prompt, "Argument Analysis", update_stats=True)

if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)
