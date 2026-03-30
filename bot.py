import discord
from discord.ext import commands
from google import genai
from google.genai import errors, types # types is required for Part.from_bytes (Multimodal)
import re, asyncio, functools, sys, os, json, logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# --- VERSION TRACKING ---
# v4.8.3 - Added old prompts back.
# Pls stop hallucinating and changing code I didn't request.
BOT_VERSION = "v4.8.3 - Hallucination Removal 2 🧠"

# --- GLOBAL START TIME ---
START_TIME = datetime.now()

# --- LOGGING CONFIGURATION ---
# RotatingFileHandler prevents 'bot_terminal.log' from bloating the NUC's storage.
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
log_file = 'bot_terminal.log'
my_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5*1024*1024, backupCount=5)
my_handler.setFormatter(log_formatter)
my_handler.setLevel(logging.INFO)

app_log = logging.getLogger('root')
app_log.setLevel(logging.INFO)
app_log.addHandler(my_handler)

def log_info(msg):
    """Prints to console and writes to the rotating log file."""
    print(msg)
    app_log.info(msg)

# --- DATA PERSISTENCE HELPERS ---

def load_file(filename):
    """Reads text files (tokens/keys) and returns a list of non-empty lines."""
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log_info(f"CRITICAL: {filename} missing.")
        return []

def load_json_data(filename):
    """Loads state data (mogg_stats, usage_stats). Returns empty dict on failure."""
    path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f:
            return json.loads(f.read().strip())
    except Exception as e:
        log_info(f"JSON Load Error ({filename}): {e}")
        return {}

def save_json_data(filename, data):
    """Saves data with os.fsync to ensure disk commitment and prevent corruption."""
    path = os.path.join(os.getcwd(), filename)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            # Hardware safety: Forces the OS to write buffer to disk immediately.
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
# NOTE: 'gemini-3.1-pro-preview' is removed to isolate it for !huh only.
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

@bot.event
async def on_ready():
    """Reports update status to the designated channel upon restart."""
    log_info(f"--- {bot.user.name} ONLINE ({BOT_VERSION}) ---")
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    if os.path.exists(update_file):
        try:
            with open(update_file, "r") as f:
                channel = await bot.fetch_channel(int(f.read().strip()))
                if channel: await channel.send(f"✅ **Update Completed:** I am now running **{BOT_VERSION}**")
        except Exception: pass
        finally: os.remove(update_file)

# --- RANKING SYSTEM ---

def get_rank_class(ratio):
    """Maps win/loss ratios to tiered ranks for the Moggboard."""
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
    """Server help interface."""
    help_text = (
        "🤖 **Bot Commands**\n"
        "**`!version`**: Build info and uptime.\n"
        "**`!tldr [amount]`**: Multi-model conversation summary.\n"
        "**`!huh`**: Pro-model fact-checking and explanation.\n"
        "**`!arguments [amount]`**: Conflict analysis.\n"
        "**`!moggboard`**: View server hierarchy.\n"
        "**`!keystatus`**: Check API health/quotas.\n"
        "---\n"
        "🛡️ **Admin**: `!clearmogs`, `!botlog`, `!update`"
    )
    await ctx.send(help_text)

@bot.command(name="version")
async def version(ctx):
    """Calculates uptime and displays the current BOT_VERSION."""
    delta = datetime.now() - START_TIME
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    await ctx.send(f"🤖 **Current Version:** `{BOT_VERSION}`\n⏱️ **Uptime:** `{uptime_str}`")

@bot.command(name="huh")
async def huh(ctx):
    """
    Concise Fact-Checker: 
    - Uses 'gemini-3.1-pro-preview' exclusively for high-fidelity reasoning.
    """
    if not ctx.message.reference:
        return await ctx.send("❌ You must reply to a message with `!huh` to use this feature.")
    
    try: await ctx.message.add_reaction("🔍")
    except: pass

    target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    media_parts = []
    
    if target.attachments:
        for attachment in target.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                image_data = await attachment.read()
                media_parts.append(types.Part.from_bytes(data=image_data, mime_type='image/jpeg'))

    prompt = (
        f"CONTEXT: Explain the following content concisely.\n"
        f"CONTENT: {target.content}\n"
        f"INSTRUCTIONS:\n"
        f"1. Summarize exactly what this is saying in 1-2 short, clear sentences. DO NOT use paragraphs.\n"
        f"2. Check for misinformation. If incorrect, concisely state why and link a single credible/primary source.\n"
        f"3. Strict brevity: Avoid walls of text. If there is no misinformation, simply provide the summary."
    )
    
    # FORCED PRO MODEL: Exclusively uses the reasoning model for fact-checks.
    await process_ai_request(
        ctx, 
        prompt, 
        "Explanation & Fact-Check", 
        media_parts=media_parts, 
        forced_model='gemini-3.1-pro-preview'
    )

@bot.command(name="moggboard")
async def moggboard(ctx):
    """Renders the server's dominance hierarchy from JSON data."""
    all_data = load_json_data("mogg_stats.json")
    server_data = all_data.get(str(ctx.guild.id), {})
    if not server_data: return await ctx.send("Moggboard is currently empty.")
    
    sorted_users = sorted(server_data.items(), key=lambda x: (x[1]['wins']/(x[1]['wins']+x[1]['losses'] or 1), x[1]['wins']), reverse=True)
    msg = f"## 👑 {ctx.guild.name.upper()} MOGGBOARD\n"
    for i, (user, stats) in enumerate(sorted_users, 1):
        w, l = stats['wins'], stats['losses']
        ratio = (w / (w+l) if (w+l)>0 else 0)
        msg += f"{i}. **{user}**\n> **Class:** `{get_rank_class(ratio)}` | **Stats:** `{w}W - {l}L` ({ratio*100:.1f}%)\n\n"
    await ctx.send(msg)

@bot.command(name="keystatus")
async def keystatus(ctx):
    """Real-time monitoring of key availability and daily model consumption."""
    now = datetime.now()
    usage = load_json_data("usage_stats.json").get(now.strftime('%Y-%m-%d'), {})
    msg = "### 🔑 API Key & Quota Status\n"
    # Monitors both the general chain and the isolated Pro model.
    monitored_models = ['gemini-3.1-pro-preview'] + MODEL_CHAIN
    for model in monitored_models:
        dead = len(exhausted_tracker.get(model, {}))
        used = usage.get(model, 0)
        total = DAILY_LIMITS.get(model, 0) * len(ALL_KEYS)
        msg += f"* **{model}**\n  └ Rate: `{len(ALL_KEYS)-dead}/{len(ALL_KEYS)}` ready | Daily: `{used}/{total}` used\n"
    await ctx.send(msg)

# --- ADMIN UTILITIES ---

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
            await ctx.send(f"```text\n{last_10}\n```")
    except Exception: await ctx.send("Log read failed.")

@bot.command(name="update")
async def update(ctx):
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    await ctx.send("📡 **Fetching code... recycling container...**")
    with open("update_channel.txt", "w") as f: f.write(str(ctx.channel.id))
    sys.exit(0)

# --- AI PROCESSING ENGINE ---

async def fetch_history(ctx, args):
    """Context harvester for !tldr and !arguments."""
    raw_input = args.strip()
    transcript_list = []
    links = re.findall(r'https://discord\.com/channels/\d+/\d+/(\d+)', raw_input)
    
    if len(links) >= 2:
        s_id, e_id = sorted([int(links[0]), int(links[1])])
        target_history = ctx.channel.history(after=await ctx.channel.fetch_message(s_id), before=await ctx.channel.fetch_message(e_id), oldest_first=True, limit=300)
    elif ctx.message.reference:
        target_history = ctx.channel.history(after=await ctx.channel.fetch_message(ctx.message.reference.message_id), oldest_first=True, limit=200)
    else:
        numbers = re.findall(r'\d+', raw_input)
        val = int(numbers[0]) if numbers else 50
        target_history = ctx.channel.history(limit=min(val, 300))

    async for msg in target_history:
        if msg.author.bot or msg.id == ctx.message.id: continue
        rx_str = f" (REACTIONS: {[f'{str(r.emoji)}x{r.count}' for r in msg.reactions]})" if msg.reactions else ""
        transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}{rx_str}")
    return transcript_list

async def process_ai_request(ctx, prompt, title, update_stats=False, media_parts=None, forced_model=None):
    """
    Orchestrates the API call. 
    - forced_model: If provided, bypasses MODEL_CHAIN to use a specific model exclusively.
    """
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
                    if today not in data: data[today] = {m: 0 for m in monitored_models} if 'monitored_models' in locals() else {m: 0 for m in (['gemini-3.1-pro-preview'] + MODEL_CHAIN)}
                    data[today][model_name] = data[today].get(model_name, 0) + 1
                    save_json_data("usage_stats.json", data)
                    break 
                except errors.ClientError as e:
                    if "429" in str(e): 
                        exhausted_tracker[model_name][i] = now + timedelta(seconds=65)
                        continue
                    else:
                        log_info(f"API Error ({model_name}): {e}")
                        return await ctx.send(f"⚠️ **API Error:** `{e}`")
                except Exception as e:
                    log_info(f"Unexpected: {e}")
                    continue
            if response: break
        
        if not response: 
            return await ctx.send(f"🔄 **Quota Error:** All keys for `{target_models}` are exhausted.")
        
        meta = response.usage_metadata
        token_info = f"📊 **Token Audit:** `In: {meta.prompt_token_count}` | `Out: {meta.candidates_token_count}` | `Total: {meta.total_token_count}`"
        await ctx.send(f"### {title} for {ctx.author.mention}\n> **Model:** `{used_model}`")
        
        sections = response.text.split("---SPLIT---")
        mogg_msg = ""
        
        if update_stats:
            match = re.search(r"WINNER:\s*([^\s|]+)\s*\|\s*LOSER:\s*([^\s\n\r]+)", sections[-1], re.IGNORECASE)
            if match:
                w, l = match.group(1).strip().rstrip('.,!'), match.group(2).strip().rstrip('.,!')
                m_data = load_json_data("mogg_stats.json")
                s_id = str(ctx.guild.id)
                if s_id not in m_data: m_data[s_id] = {}
                for p in [w, l]:
                    if p not in m_data[s_id]: m_data[s_id][p] = {"wins": 0, "losses": 0}
                m_data[s_id][w]["wins"] += 1
                m_data[s_id][l]["losses"] += 1
                save_json_data("mogg_stats.json", m_data)
                mogg_msg = f"# 🏟️ MOGG LEDGER\n* **Winner:** {w} (+1W) | **Loser:** {l} (+1L)\n* **Updated:** `{w}: {m_data[s_id][w]['wins']}W` | `{l}: {m_data[s_id][l]['losses']}L`"
        
        for s in sections:
            content = s.strip()
            if content and "WINNER:" not in content:
                for j in range(0, len(content), 1900): await ctx.send(content[j:j+1900])
        
        if mogg_msg: await ctx.send(mogg_msg)
        await ctx.send(token_info)

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    history_text = "\n".join(transcript)
    prompt = (
        f"Summarize the following transcript. "
        f"CRITICAL: The '# 📝 SUMMARIES' section must be grouped by user display name.\n"
        f"# 📝 SUMMARIES\n"
        f"Grouped by User Display Name:\n"
        f"- [User Name]: bullet points of their contributions.\n"
        f"# 📈 CORTISOL SPIKES\n"
        f"Identify aggression/shouting. If toxic, state: '⚠️ [Name] has been penalized for high cortisol levels.'\n"
        f"# MOGG DATA (INTERNAL)\n"
        f"Format: 'WINNER: [Name] | LOSER: [Name]'\n"
        f"RULES: Use '---SPLIT---' between these 3 sections.\n\n"
        f"TRANSCRIPT:\n{history_text}"
    )
    await process_ai_request(ctx, prompt, "Summary", update_stats=True)

@bot.command(name="arguments")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def arguments(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    history_text = "\n".join(transcript)
    prompt = (
        f"Analyze the transcript for arguments. Use '---SPLIT---' between these 4 sections:\n"
        f"1. # 📜 ARGUMENT SUMMARY - Brief overview of what happened.\n"
        f"2. # 🔍 PER-POINT REVIEW - Detailed breakdown of claims made.\n"
        f"3. # ⚖️ FINAL VERDICT - Decisive resolution. Explicitly state: '[Name] wins and [Name] loses.'\n"
        f"4. MOGG DATA (INTERNAL) - Format: 'WINNER: [Name] | LOSER: [Name]'\n\n"
        f"TRANSCRIPT:\n{history_text}"
    )
    await process_ai_request(ctx, prompt, "Argument Analysis", update_stats=True)

if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)
