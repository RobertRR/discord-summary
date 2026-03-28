import discord
from discord.ext import commands
from google import genai  # Official Google GenAI Python SDK (v1.0+)
from google.genai import errors 
import re, asyncio, functools, sys, os, json, logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# --- VERSION TRACKING ---
# v4.2 - The GenAI Migration 🚀
# Migration Notes: Switched from 'google-generativeai' to 'google-genai'.
# This version implements 'asyncio.to_thread' to prevent API blocking.
BOT_VERSION = "v4.2 🚀"

# --- LOGGING INFRASTRUCTURE ---
# We use a RotatingFileHandler to prevent 'bot_terminal.log' from eating all disk space.
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

# --- DATA PERSISTENCE & FILE I/O ---
# These functions handle loading plain text lists (keys, tokens) and structured JSON data.
def load_file(filename):
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log_info(f"CRITICAL: {filename} not found")
        return []

def load_json_data(filename):
    """Loads JSON data for Moggboard stats or Usage stats."""
    path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except: return {}

def save_json_data(filename, data):
    """Saves data with fsync to ensure it's written to disk before the container could restart."""
    path = os.path.join(os.getcwd(), filename)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        log_info(f"Failed to save {filename}: {e}")

# --- GLOBAL CONFIGURATION ---
token_list = load_file("discordtoken.txt")
DISCORD_TOKEN = token_list[0] if token_list else None
ALL_KEYS = load_file("keys.txt")
ADMIN_IDS = [int(i) for i in load_file("admins.txt")]

# exhausted_tracker: Stores timestamp when a key/model combo hits a 429 Rate Limit.
exhausted_tracker = {} 

# Model Chain: The bot will try these in order if the primary model is rate-limited.
MODEL_CHAIN = ['gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-3.1-flash-lite-preview']

# Daily Limits: Internal soft-caps to track against usage_stats.json.
DAILY_LIMITS = {
    'gemini-3.1-pro-preview': 5,
    'gemini-3-flash-preview': 50,
    'gemini-2.5-flash': 20,
    'gemini-3.1-flash-lite-preview': 100
}

# --- BOT INITIALIZATION ---
intents = discord.Intents.default()
intents.message_content = True  # Required to read channel history
intents.members = True          # Required to resolve display names
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

@bot.event
async def on_ready():
    log_info(f"--- {bot.user.name} ONLINE (Version {BOT_VERSION}) ---")
    
    # Recovery Logic: If the bot was restarted via !update, it sends a 'back online' message.
    await asyncio.sleep(5) 
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    if os.path.exists(update_file):
        try:
            with open(update_file, "r") as f:
                channel_id = int(f.read().strip())
                channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(f"✅ **Update Completed:** I am back online. Current Version: **{BOT_VERSION}**")
        except Exception as e:
            log_info(f"Recovery Message Failed: {e}")
        finally:
            if os.path.exists(update_file): os.remove(update_file)

# --- RANKING LOGIC ---
def get_rank_class(ratio):
    """Determines Moggboard ranking based on Win/Loss ratio (Dota-style naming)."""
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

@bot.command(name="moggboard")
async def moggboard(ctx):
    """Displays the competitive hierarchy of the server."""
    all_data = load_json_data("mogg_stats.json")
    guild_id = str(ctx.guild.id)
    server_data = all_data.get(guild_id, {})
    if not server_data: return await ctx.send("The Moggboard for this server is empty.")
    
    # Sort by Ratio (Win %) first, then total Wins.
    sorted_users = sorted(server_data.items(), key=lambda x: (x[1]['wins']/(x[1]['wins']+x[1]['losses'] or 1), x[1]['wins']), reverse=True)
    msg = f"## 👑 {ctx.guild.name.upper()} MOGGBOARD\n"
    for i, (user, stats) in enumerate(sorted_users, 1):
        w, l = stats['wins'], stats['losses']
        ratio = (w / (w+l) if (w+l)>0 else 0)
        rank_class = get_rank_class(ratio)
        msg += f"{i}. **{user}**\n> **Class:** `{rank_class}` | **Stats:** `{w}W - {l}L` ({ratio*100:.1f}%)\n\n"
    await ctx.send(msg)

@bot.command(name="keystatus")
async def keystatus(ctx):
    """Admin/User tool to monitor API health and daily quotas."""
    now = datetime.now()
    usage = load_json_data("usage_stats.json").get(now.strftime('%Y-%m-%d'), {})
    msg = "### 🔑 API Key & Quota Status\n"
    for model in MODEL_CHAIN:
        dead_count = len(exhausted_tracker.get(model, {}))
        available = len(ALL_KEYS) - dead_count
        used = usage.get(model, 0)
        total_limit = DAILY_LIMITS.get(model, 0) * len(ALL_KEYS)
        msg += f"* **{model}**\n  └ Rate: `{available}/{len(ALL_KEYS)}` ready | Daily: `{used}/{total_limit}` used\n"
    await ctx.send(msg)

@bot.command(name="update")
async def update(ctx):
    """Force-pulls new code and restarts the container via sys.exit(0)."""
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Access Denied.")
    await ctx.send("🔄 Pulling latest code and recycling container...")
    with open("update_channel.txt", "w") as f: f.write(str(ctx.channel.id))
    sys.exit(0)

# --- TRANSCRIPT ENGINE ---
async def fetch_history(ctx, args):
    """
    Complex history fetching logic. Supports:
    1. Message Link Pairs (Start/End)
    2. Replying to a message (Replied Msg -> Now)
    3. Relative time (e.g., '10 mins', '1 hr')
    4. Simple integer (e.g., '50' for last 50 messages)
    """
    raw_input = args.strip()
    transcript_list = []
    base_url = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/"

    # Option 1: Links
    links = re.findall(r'https://discord\.com/channels/\d+/\d+/(\d+)', raw_input)
    if len(links) >= 2:
        try:
            start_id, end_id = sorted([int(links[0]), int(links[1])])
            start_msg = await ctx.channel.fetch_message(start_id)
            end_msg = await ctx.channel.fetch_message(end_id)
            async for msg in ctx.channel.history(after=start_msg.created_at, before=end_msg.created_at, oldest_first=True, limit=300):
                if msg.author.bot: continue
                transcript_list.append(f"USER: {msg.author.display_name} | LINK: {base_url}{msg.id} | MSG: {msg.content}")
            transcript_list.insert(0, f"USER: {start_msg.author.display_name} | LINK: {base_url}{start_msg.id} | MSG: {start_msg.content}")
            transcript_list.append(f"USER: {end_msg.author.display_name} | LINK: {base_url}{end_msg.id} | MSG: {end_msg.content}")
            return transcript_list
        except: pass

    # Option 2: Replies
    if ctx.message.reference:
        try:
            replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            async for msg in ctx.channel.history(after=replied_msg.created_at, oldest_first=True, limit=200):
                if msg.author.bot: continue
                transcript_list.append(f"USER: {msg.author.display_name} | LINK: {base_url}{msg.id} | MSG: {msg.content}")
            transcript_list.insert(0, f"USER: {replied_msg.author.display_name} | LINK: {base_url}{replied_msg.id} | MSG: {replied_msg.content}")
            return transcript_list
        except: pass

    # Option 3 & 4: Time or Amount
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    if any(k in raw_input.lower() for k in ["min", "hour", "hr"]):
        delta_minutes = value if "min" in raw_input.lower() else value * 60
        if delta_minutes > 1440: # 24hr hard limit
            await ctx.reply("⚠️ Safeguard: Requests limited to 24h.")
            return None
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - timedelta(minutes=delta_minutes), oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"USER: {msg.author.display_name} | LINK: {base_url}{msg.id} | MSG: {msg.content}")
    else:
        async for msg in ctx.channel.history(limit=min(value, 300) + 10):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"USER: {msg.author.display_name} | LINK: {base_url}{msg.id} | MSG: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()
    return transcript_list

# --- AI PROCESSING ENGINE ---
async def process_ai_request(ctx, prompt, title_prefix, update_stats=False):
    """
    The main AI loop. Implements 'API Key Rotation' and 'Model Chaining'.
    Uses asyncio.to_thread because the google-genai SDK is synchronous.
    """
    async with ctx.typing():
        response = None
        used_model = ""
        now = datetime.now()
        guild_id = str(ctx.guild.id)
        
        for model_name in MODEL_CHAIN:
            if model_name not in exhausted_tracker: exhausted_tracker[model_name] = {}
            for i in range(len(ALL_KEYS)):
                # Check if this specific key is on cooldown
                if i in exhausted_tracker[model_name] and now < exhausted_tracker[model_name][i]: continue
                
                try:
                    client = genai.Client(api_key=ALL_KEYS[i])
                    
                    # Offload the blocking API call to a separate thread
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model_name,
                        contents=prompt
                    )
                    used_model = model_name
                    
                    # Record usage stats for !keystatus
                    today = now.strftime('%Y-%m-%d')
                    data = load_json_data("usage_stats.json")
                    if today not in data: data[today] = {m: 0 for m in MODEL_CHAIN}
                    data[today][model_name] = data[today].get(model_name, 0) + 1
                    save_json_data("usage_stats.json", data)
                    break 
                except errors.ClientError as e:
                    err_str = str(e)
                    if "429" in err_str: # Rate Limit
                        exhausted_tracker[model_name][i] = now + timedelta(seconds=65)
                    elif "403" in err_str: # Invalid Key
                        log_info(f"Key {i} Invalid/Forbidden.")
                    continue
                except Exception as e:
                    log_info(f"API Error: {e}"); continue
            if response: break
            
        if not response: return await ctx.send("🔄 Quotas Exhausted.")
        
        await ctx.send(f"### {title_prefix} for {ctx.author.mention}\n> **Model:** `{used_model}`")
        sections = response.text.split("---SPLIT---")
        
        # Moggboard Update: Parses 'WINNER: X | LOSER: Y' from the AI output.
        if update_stats:
            mogg_section = sections[-1] if len(sections) >= 3 else ""
            match = re.search(r"WINNER:\s*([^\s|]+)\s*\|\s*LOSER:\s*([^\s\n\r]+)", mogg_section, re.IGNORECASE)
            if match:
                winner, loser = match.group(1).strip().rstrip('.,!'), match.group(2).strip().rstrip('.,!')
                all_data = load_json_data("mogg_stats.json")
                if guild_id not in all_data: all_data[guild_id] = {}
                for p in [winner, loser]:
                    if p not in all_data[guild_id]: all_data[guild_id][p] = {"wins": 0, "losses": 0}
                all_data[guild_id][winner]["wins"] += 1
                all_data[guild_id][loser]["losses"] += 1
                save_json_data("mogg_stats.json", all_data)
                
        # Send chunks to Discord (under 2000 char limit)
        for s in sections:
            content = s.strip()
            if content and "WINNER:" not in content:
                for j in range(0, len(content), 1900): await ctx.send(content[j:j+1900])

# --- COMMAND WRAPPERS ---
@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return
    
    history_text = "\n".join(transcript)
    prompt = (
        f"Summarize transcript. Use '---SPLIT---' between sections.\n"
        f"# 📝 SUMMARIES\nGrouped by User Display Name: [Name]: bullet points.\n"
        f"# 📈 CORTISOL SPIKES\nIf toxic: '⚠️ [Name] penalized for high cortisol.'\n"
        f"# MOGG DATA (INTERNAL)\nWINNER: [Name] | LOSER: [Name]\n\n"
        f"TRANSCRIPT:\n{history_text}"
    )
    await process_ai_request(ctx, prompt, "Summary", update_stats=True)

if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)
