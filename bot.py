import discord
from discord.ext import commands
from google import genai
from google.genai import errors 
import re, asyncio, functools, sys, os, json, logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# --- VERSION TRACKING ---
# v4.7.7 - Documentation & Context Update. Expanded comments and added !huh logic.
# Major: 4 | Minor: 7 | Subminor: 7
BOT_VERSION = "v4.7.7 - Documentation & Context ⚡"

# --- GLOBAL START TIME ---
# Used for uptime tracking in the !version command.
START_TIME = datetime.now()

# --- LOGGING ---
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
    print(msg)
    app_log.info(msg)

# --- DATA HELPERS ---
# NOTE: keys.txt, discordtoken.txt, and admins.txt must stay in the same dir.
def load_file(filename):
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log_info(f"CRITICAL: {filename} missing.")
        return []

def load_json_data(filename):
    path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f:
            return json.loads(f.read().strip())
    except: return {}

def save_json_data(filename, data):
    path = os.path.join(os.getcwd(), filename)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            # os.fsync forces the OS to write to disk immediately.
            # Vital for NUCs to prevent corruption on sudden power loss.
            os.fsync(f.fileno()) 
    except Exception as e:
        log_info(f"Save Failed: {e}")

# --- CONFIG ---
token_list = load_file("discordtoken.txt")
DISCORD_TOKEN = token_list[0] if token_list else None
ALL_KEYS = load_file("keys.txt")
ADMIN_IDS = [int(i) for i in load_file("admins.txt")]

# exhausted_tracker: Stores (model_name -> {key_index -> reset_time})
exhausted_tracker = {} 

# MODEL_CHAIN: Order of fallback if a key is rate-limited (429) or exhausted.
MODEL_CHAIN = ['gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-3.1-flash-lite-preview']
DAILY_LIMITS = {'gemini-3.1-pro-preview': 5, 'gemini-3-flash-preview': 50, 'gemini-2.5-flash': 20, 'gemini-3.1-flash-lite-preview': 100}

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True         
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help') # Removing default to use our custom !help logic.

@bot.event
async def on_ready():
    log_info(f"--- {bot.user.name} ONLINE ({BOT_VERSION}) ---")
    # update_channel.txt tells the bot where to report back after a !update reboot.
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    if os.path.exists(update_file):
        try:
            with open(update_file, "r") as f:
                channel = await bot.fetch_channel(int(f.read().strip()))
                if channel: await channel.send(f"✅ **Update Completed:** I am now running **{BOT_VERSION}**")
        except: pass
        finally: os.remove(update_file)

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

# --- COMMANDS ---

@bot.command(name="help")
async def help_command(ctx):
    """
    Custom Help Menu: Uses legacy formatting with dual sections.
    Note: Spacing is intentional to match original Discord visual style.
    """
    help_text = (
        "🤖 **Bot Commands**\n"
        "**`!version`**\n"
        "Shows the current build version.\n\n"
        "**`!tldr [amount]`**\n"
        "Summaries + Cortisol Spike detection.\n\n"
        "**`!huh`**\n"
        "Reply to a message to explain content and fact-check claims.\n\n"
        "**`!arguments [amount]`**\n"
        "Conflict Analysis and Mogg updates.\n\n"
        "**`!moggboard`**\n"
        "View the server's dominance hierarchy.\n\n"
        "**`!keystatus`**\n"
        "Check API health and daily quotas.\n\n"
        "---\n"
        "🛡️ **Admin Commands**\n"
        "**`!clearmogs`**\n"
        "Resets Moggboard data to zero.\n\n"
        "**`!botlog`**\n"
        "Displays the last 10 lines of the terminal log.\n\n"
        "**`!update`**\n"
        "Pulls latest code from GitHub and restarts the container."
    )
    await ctx.send(help_text)

@bot.command(name="version")
async def version(ctx):
    """Uptime calculation: Uses the global START_TIME established at boot."""
    delta = datetime.now() - START_TIME
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    await ctx.send(f"🤖 **Current Version:** `{BOT_VERSION}`\n⏱️ **Uptime:** `{uptime_str}`")

@bot.command(name="huh")
async def huh(ctx):
    """
    Contextual Fact-Checker: This command requires a reply (ctx.message.reference).
    It extracts text, links, and image attachments from the target message
    and prompts Gemini to verify claims and explain the content.
    """
    if not ctx.message.reference:
        return await ctx.send("❌ You must reply to a message with `!huh` to use this feature.")
    
    # Fetch the target message that is being replied to
    target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    media_parts = []
    
    # Image extraction: Checks attachments for compatible image formats
    if target.attachments:
        for attachment in target.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                image_data = await attachment.read()
                media_parts.append({'mime_type': 'image/jpeg', 'data': image_data})

    # Fact-check prompt: Specific instructions for veracity and sourcing.
    prompt = (
        f"CONTEXT: You are explaining a specific post to a user. Use '---SPLIT---' for long answers.\n"
        f"MESSAGE CONTENT: {target.content}\n"
        f"INSTRUCTIONS:\n"
        f"1. Explain what this message/image means in plain English.\n"
        f"2. Identify any claims or assertions made.\n"
        f"3. FACT CHECK: If a claim is made, verify its accuracy. If it is factually incorrect, "
        f"provide a concise correction and MUST include a link to a primary or highly reputable source.\n"
        f"4. If an image is provided, identify if it has been manipulated or is visually inaccurate. Explain why."
    )
    
    await process_ai_request(ctx, prompt, "Explanation & Fact-Check", media_parts=media_parts)

@bot.command(name="moggboard")
async def moggboard(ctx):
    """Moggboard Logic: Sorts by win ratio (W/W+L) then by total win count."""
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
    """Quota Tracker: Pulls usage from usage_stats.json and checks local exhaustion_tracker."""
    now = datetime.now()
    usage = load_json_data("usage_stats.json").get(now.strftime('%Y-%m-%d'), {})
    msg = "### 🔑 API Key & Quota Status\n"
    for model in MODEL_CHAIN:
        dead = len(exhausted_tracker.get(model, {}))
        used = usage.get(model, 0)
        total = DAILY_LIMITS.get(model, 0) * len(ALL_KEYS)
        msg += f"* **{model}**\n  └ Rate: `{len(ALL_KEYS)-dead}/{len(ALL_KEYS)}` ready | Daily: `{used}/{total}` used\n"
    await ctx.send(msg)

@bot.command(name="clearmogs")
async def clearmogs(ctx):
    """Admin Only: Deletes the guild's entry from the mogg_stats.json file."""
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    m_data = load_json_data("mogg_stats.json")
    if str(ctx.guild.id) in m_data:
        del m_data[str(ctx.guild.id)]
        save_json_data("mogg_stats.json", m_data)
        await ctx.send("🧹 **Moggboard cleared for this server.**")

@bot.command(name="botlog")
async def botlog(ctx):
    """Admin Only: Reads the rolling log file. Limited to 10 lines to prevent Discord message overflow."""
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    try:
        with open("bot_terminal.log", "r") as f:
            lines = f.readlines()
            last_10 = "".join(lines[-10:])
            await ctx.send(f"```text\n{last_10}\n```")
    except: await ctx.send("Log read failed.")

@bot.command(name="update")
async def update(ctx):
    """Update Flow: Saves the current channel ID to a text file before exiting so it can report success on reboot."""
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    await ctx.send("📡 **Fetching latest upstream code and recycling the container...**")
    with open("update_channel.txt", "w") as f: f.write(str(ctx.channel.id))
    sys.exit(0)

async def fetch_history(ctx, args):
    """
    History Aggregator: Support for relative counts (e.g. !tldr 50), 
    direct message links (before/after), and message replies.
    """
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
        
        # Reaction Extraction: Converts 😂x2 into text strings so AI can gauge vibe.
        rx_str = ""
        if msg.reactions:
            rx_list = [f"{str(r.emoji)}x{r.count}" for r in msg.reactions]
            rx_str = f" (REACTIONS: {', '.join(rx_list)})"
        transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}{rx_str}")
    return transcript_list

async def process_ai_request(ctx, prompt, title, update_stats=False, media_parts=None):
    """
    Key Switcher/Rate Limiter: Attempts to find a functional API key across the model chain.
    Implements a 65s cooling period for keys that hit 429 errors.
    """
    async with ctx.typing():
        response = None
        used_model = ""
        now = datetime.now()
        
        # Payload assembly: merges text prompt with any image data provided.
        content_payload = [prompt] + (media_parts if media_parts else [])
        
        for model_name in MODEL_CHAIN:
            if model_name not in exhausted_tracker: exhausted_tracker[model_name] = {}
            for i, key in enumerate(ALL_KEYS):
                if i in exhausted_tracker[model_name] and now < exhausted_tracker[model_name][i]: continue
                try:
                    client = genai.Client(api_key=key)
                    # Offload to thread to keep the Discord heartbeat alive during long AI inference.
                    response = await asyncio.to_thread(client.models.generate_content, model=model_name, contents=content_payload)
                    used_model = model_name
                    today = now.strftime('%Y-%m-%d')
                    data = load_json_data("usage_stats.json")
                    if today not in data: data[today] = {m: 0 for m in MODEL_CHAIN}
                    data[today][model_name] = data[today].get(model_name, 0) + 1
                    save_json_data("usage_stats.json", data)
                    break 
                except errors.ClientError as e:
                    if "429" in str(e): 
                        exhausted_tracker[model_name][i] = now + timedelta(seconds=65)
                    continue
                except: continue
            if response: break
        if not response: return await ctx.send("🔄 All keys rate-limited.")
        
        # Output Formatting: Splits responses by '---SPLIT---' to manage Discord's 2000char limit.
        meta = response.usage_metadata
        token_info = f"📊 **Token Audit:** `In: {meta.prompt_token_count}` | `Out: {meta.candidates_token_count}` | `Total: {meta.total_token_count}`"
        await ctx.send(f"### {title} for {ctx.author.mention}\n> **Model:** `{used_model}`")
        
        sections = response.text.split("---SPLIT---")
        mogg_msg = ""
        if update_stats:
            # Mogg Extraction: Looks for WINNER/LOSER keywords in the AI response to update scoreboard.
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
    """Summary feature: Prompts AI to group by name and find toxic spikes."""
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return
    prompt = (
        f"Summarize the conversation clearly. Use '---SPLIT---' between sections.\n"
        f"IMPORTANT: Use reactions (e.g. 😂x3) in transcript to gauge social vibe.\n\n"
        f"# 📝 SUMMARIES\n"
        f"Group by user display name. Format: **[Name]**: [bullet points].\n\n"
        f"# 📈 CORTISOL SPIKES\n"
        f"Concise notes on toxic behavior. Keep it very tidy and brief.\n\n"
        f"# MOGG DATA (INTERNAL)\n"
        f"WINNER: [Name] | LOSER: [Name]\n\n"
        f"TRANSCRIPT:\n" + "\n".join(transcript)
    )
    await process_ai_request(ctx, prompt, "Summary", update_stats=True)

@bot.command(name="arguments")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def arguments(ctx, *, args: str = "50"):
    """Adjudication feature: Specifically forces Gemini to judge a conflict."""
    try: await ctx.message.add_reaction("⚖️")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return
    prompt = (
        f"Analyze the following conversation specifically to determine a winner and a loser based on argument strength, wit, and social dominance.\n"
        f"Format the final line exactly as: WINNER: [Name] | LOSER: [Name]\n\n"
        f"TRANSCRIPT:\n" + "\n".join(transcript)
    )
    await process_ai_request(ctx, prompt, "Adjudication", update_stats=True)

if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)
