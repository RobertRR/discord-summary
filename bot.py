import discord
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions
import re, asyncio, functools, sys, os, json, logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from youtube_transcript_api import YouTubeTranscriptApi

# --- VERSION TRACKING ---
BOT_VERSION = "v3.16 - Library Fix (fetch) 🛠️"

# --- LOGGING SETUP ---
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

# --- STARTUP PERMISSION CHECK ---
def check_write_permissions():
    test_file = "permission_test.tmp"
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        log_info(f"SUCCESS: Bot has write access. Version: {BOT_VERSION}")
        return True
    except Exception as e:
        log_info(f"CRITICAL: Bot lacks write access! Error: {e}")
        return False

# --- FILE & DATA PERSISTENCE ---
def load_file(filename):
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log_info(f"CRITICAL: {filename} not found")
        return []

def load_json_data(filename):
    path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except: return {}

def save_json_data(filename, data):
    path = os.path.join(os.getcwd(), filename)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        log_info(f"Failed to save {filename}: {e}")

# Run permission audit
has_write_access = check_write_permissions()

token_list = load_file("discordtoken.txt")
DISCORD_TOKEN = token_list[0] if token_list else None
ALL_KEYS = load_file("keys.txt")
ADMIN_IDS = [int(i) for i in load_file("admins.txt")]

# --- API & QUOTA CONFIG ---
exhausted_tracker = {} 
MODEL_CHAIN = ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.5-flash-8b']

DAILY_LIMITS = {
    'gemini-1.5-pro': 5,
    'gemini-1.5-flash': 50,
    'gemini-1.5-flash-8b': 100
}

def configure_genai(key_index):
    genai.configure(api_key=ALL_KEYS[key_index])

if ALL_KEYS:
    configure_genai(0)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

@bot.event
async def on_ready():
    log_info(f"--- {bot.user.name} ONLINE (Version {BOT_VERSION}) ---")
    await asyncio.sleep(5) 
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    if os.path.exists(update_file):
        try:
            with open(update_file, "r") as f:
                content = f.read().strip()
                if content:
                    channel_id = int(content)
                    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                    if channel:
                        await channel.send(f"✅ **Update Completed:** I am back online. Current Version: **{BOT_VERSION}**")
        except Exception as e:
            log_info(f"Recovery Message Failed: {e}")
        finally:
            if os.path.exists(update_file): os.remove(update_file)

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
    return "Unranked"

@bot.command(name="help")
async def help_command(ctx):
    help_text = (
        "### 🤖 Bot Commands\n"
        "* **!version**\n"
        "  Shows the current build version.\n\n"
        "* **!tldr [amount]**\n"
        "  Summaries + **Cortisol Spike** detection.\n\n"
        "* **!tldw (as a reply)**\n"
        "  Summarizes a YouTube video transcript.\n\n"
        "* **!arguments [amount]**\n"
        "  Conflict Analysis and Mogg updates.\n\n"
        "* **!moggboard**\n"
        "  View the server's dominance hierarchy.\n\n"
        "* **!keystatus**\n"
        "  Check API health and daily quotas.\n\n"
        "---\n"
        "### 🛡️ Admin Commands\n"
        "* **!clearmogs**\n"
        "  Resets Moggboard data to zero.\n\n"
        "* **!botlog**\n"
        "  Displays the last 10 lines of the terminal log.\n\n"
        "* **!update**\n"
        "  Pulls latest code from GitHub and restarts the container."
    )
    await ctx.send(help_text)

@bot.command(name="version")
async def version(ctx):
    await ctx.send(f"Current Build: **{BOT_VERSION}**")

@bot.command(name="botlog")
async def botlog(ctx):
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Access Denied.")
    try:
        with open("bot_terminal.log", "r") as f:
            lines = f.readlines()
            last_lines = "".join(lines[-10:])
            await ctx.send(f"```\n{last_lines}\n```")
    except Exception as e:
        await ctx.send(f"Could not read log: {e}")

@bot.command(name="moggboard")
async def moggboard(ctx):
    data = load_json_data("mogg_stats.json")
    if not data: return await ctx.send("The Moggboard is empty.")
    sorted_users = sorted(data.items(), key=lambda x: (x[1]['wins']/(x[1]['wins']+x[1]['losses'] or 1), x[1]['wins']), reverse=True)
    msg = "## 👑 THE OFFICIAL MOGGBOARD\n"
    for i, (user, stats) in enumerate(sorted_users, 1):
        w, l = stats['wins'], stats['losses']
        ratio = (w / (w+l) if (w+l)>0 else 0)
        rank_class = get_rank_class(ratio)
        msg += f"{i}. **{user}**\n> **Class:** `{rank_class}` | **Stats:** `{w}W - {l}L` ({ratio*100:.1f}%)\n\n"
    await ctx.send(msg)

@bot.command(name="clearmogs")
async def clearmogs(ctx):
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Admin only.")
    save_json_data("mogg_stats.json", {})
    await ctx.send("🗑️ **Moggboard Reset.**")

@bot.command(name="keystatus")
async def keystatus(ctx):
    now = datetime.now()
    usage = load_json_data("usage_stats.json").get(now.strftime('%Y-%m-%d'), {})
    msg = "### 🔑 API Key & Quota Status\n"
    for model in MODEL_CHAIN:
        dead_count = len(exhausted_tracker.get(model, {}))
        available = len(ALL_KEYS) - dead_count
        used = usage.get(model, 0)
        total_limit = DAILY_LIMITS.get(model, 0) * len(ALL_KEYS)
        msg += f"* **{model}**\n  └ Rate: `{available}/{len(ALL_KEYS)}` keys ready | Daily: `{used}/{total_limit}` used\n"
    await ctx.send(msg)

@bot.command(name="update")
async def update(ctx):
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Access Denied.")
    await ctx.send("🔄 Cleaning local script and forcing container recycle...")
    try:
        script_path = os.path.join(os.getcwd(), "bot.py")
        if os.path.exists(script_path):
            with open(script_path, 'w') as f: f.write("")
            os.remove(script_path)
    except Exception as e:
        log_info(f"Update cleanup failed: {e}")
    with open("update_channel.txt", "w") as f: f.write(str(ctx.channel.id))
    sys.exit(0)

async def get_ai_response_async(model, prompt):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(model.generate_content, prompt))

async def fetch_history(ctx, args):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    transcript_list = []
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])
    base_url = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/"
    if is_time_mode:
        delta = timedelta(minutes=value) if "min" in raw_input else timedelta(hours=value)
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"USER: {msg.author.display_name} | LINK: {base_url}{msg.id} | MSG: {msg.content}")
    else:
        async for msg in ctx.channel.history(limit=value + 10):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"USER: {msg.author.display_name} | LINK: {base_url}{msg.id} | MSG: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()
    return transcript_list

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    history_text = "\n".join(transcript)
    prompt = f"Summarize transcript.\n# 📝 SUMMARIES\nBullet points.\n# 📈 CORTISOL SPIKES\nIdentify aggression/shouting. If toxic, state: '⚠️ [Name] has been penalized for high cortisol levels.'\n# MOGG DATA (INTERNAL)\nFormat: 'WINNER: [Name] | LOSER: [Name]'\nRULES: Use '---SPLIT---' between sections.\n\nTRANSCRIPT:\n{history_text}"
    await process_ai_request(ctx, prompt, "Summary", update_stats=True)

@bot.command(name="tldw")
@commands.cooldown(1, 60, commands.BucketType.user)
async def tldw(ctx):
    if not ctx.message.reference:
        return await ctx.send("❌ Please **reply** to a message containing a YouTube link with `!tldw`.")
    try:
        replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        yt_regex = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
        match = re.search(yt_regex, replied_msg.content)
        if not match: return await ctx.send("❌ No valid YouTube URL found.")
        video_id = match.group(1)
        await ctx.message.add_reaction("⏳")
        async with ctx.typing():
            try:
                # NEW v3.16 FIX: Instantiate class first, then use fetch()
                api = YouTubeTranscriptApi()
                transcript_data = api.fetch(video_id, languages=['en', 'en-GB']).to_raw_data()
                full_text = " ".join([i['text'] for i in transcript_data])
            except Exception as e:
                log_info(f"Transcript fetch failed: {e}")
                return await ctx.send(f"❌ Could not fetch transcript: {e}")
            
            prompt = f"Summarize video transcript in one paragraph.\n\nTRANSCRIPT:\n{full_text[:50000]}"
            flash_chain = ['gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-1.5-pro']
            await process_ai_request(ctx, prompt, "Video Summary (TL;DW)", update_stats=False, custom_chain=flash_chain)
    except Exception as e:
        log_info(f"TLDW Error: {e}")
        await ctx.send("⚠️ Error processing video.")

@bot.command(name="arguments")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def arguments(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    history_text = "\n".join(transcript)
    prompt = f"Analyze for arguments. Use '---SPLIT---' between sections.\n\nTRANSCRIPT:\n{history_text}"
    await process_ai_request(ctx, prompt, "Argument Analysis", update_stats=True)

async def process_ai_request(ctx, prompt, title_prefix, update_stats=False, custom_chain=None):
    async with ctx.typing():
        response, used_model = None, ""
        now = datetime.now()
        chain = custom_chain if custom_chain else MODEL_CHAIN
        for model_name in chain:
            if model_name not in exhausted_tracker: exhausted_tracker[model_name] = {}
            for i in range(len(ALL_KEYS)):
                if i in exhausted_tracker[model_name] and now < exhausted_tracker[model_name][i]: continue
                try:
                    configure_genai(i)
                    current_model = genai.GenerativeModel(model_name)
                    response = await get_ai_response_async(current_model, prompt)
                    used_model = model_name
                    today = now.strftime('%Y-%m-%d')
                    data = load_json_data("usage_stats.json")
                    if today not in data: data[today] = {m: 0 for m in MODEL_CHAIN}
                    data[today][model_name] += 1
                    save_json_data("usage_stats.json", data)
                    break 
                except exceptions.ResourceExhausted:
                    exhausted_tracker[model_name][i] = now + timedelta(seconds=65)
                except Exception as e: log_info(f"Error: {e}")
            if response: break
        if not response: return await ctx.send("🔄 Quotas Exhausted.")
        await ctx.send(f"### {title_prefix} for {ctx.author.mention}\n> **Model:** `{used_model}`")
        sections = response.text.split("---SPLIT---")
        if update_stats:
            mogg_section = sections[-1] if len(sections) >= 3 else ""
            match = re.search(r"WINNER:\s*([^\s|]+)\s*\|\s*LOSER:\s*([^\s\n\r]+)", mogg_section, re.IGNORECASE)
            if match:
                winner, loser = match.group(1).strip().rstrip('.,!'), match.group(2).strip().rstrip('.,!')
                data = load_json_data("mogg_stats.json")
                for p in [winner, loser]:
                    if p not in data: data[p] = {"wins": 0, "losses": 0}
                data[winner]["wins"] += 1; data[loser]["losses"] += 1
                save_json_data("mogg_stats.json", data)
        for s in sections:
            content = s.strip()
            if content and "WINNER:" not in content:
                for j in range(0, len(content), 1900): await ctx.send(content[j:j+1900])

if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)
