import discord
from discord.ext import commands
from google import genai
from google.genai import errors 
import re, asyncio, functools, sys, os, json, logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# --- VERSION TRACKING ---
# v4.3 "Vibe Auditor" - Now tracks user reactions and reports token usage metadata.
BOT_VERSION = "v4.3 - Vibe Auditor 📊"

# --- LOGGING ---
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
def load_file(filename):
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
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
            os.fsync(f.fileno())
    except Exception as e:
        log_info(f"Save Failed: {e}")

# --- CONFIG ---
token_list = load_file("discordtoken.txt")
DISCORD_TOKEN = token_list[0] if token_list else None
ALL_KEYS = load_file("keys.txt")
ADMIN_IDS = [int(i) for i in load_file("admins.txt")]

exhausted_tracker = {} 
MODEL_CHAIN = ['gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-3.1-flash-lite-preview']
DAILY_LIMITS = {'gemini-3.1-pro-preview': 5, 'gemini-3-flash-preview': 50, 'gemini-2.5-flash': 20, 'gemini-3.1-flash-lite-preview': 100}

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

@bot.event
async def on_ready():
    log_info(f"--- {bot.user.name} ONLINE ({BOT_VERSION}) ---")
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    if os.path.exists(update_file):
        try:
            with open(update_file, "r") as f:
                channel = await bot.fetch_channel(int(f.read().strip()))
                if channel: await channel.send(f"✅ **Update Completed:** I am now running **{BOT_VERSION}**")
        except: pass
        finally: os.remove(update_file)

# --- RANKING ---
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

# --- CORE LOGIC ---

@bot.command(name="version")
async def version(ctx):
    """Displays the current running version and its fun name."""
    await ctx.send(f"🤖 **Current Version:** `{BOT_VERSION}`")

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
        msg += f"{i}. **{user}**\n> **Class:** `{get_rank_class(ratio)}` | **Stats:** `{w}W - {l}L` ({ratio*100:.1f}%)\n\n"
    await ctx.send(msg)

@bot.command(name="keystatus")
async def keystatus(ctx):
    now = datetime.now()
    usage = load_json_data("usage_stats.json").get(now.strftime('%Y-%m-%d'), {})
    msg = "### 🔑 API Key & Quota Status\n"
    for model in MODEL_CHAIN:
        dead = len(exhausted_tracker.get(model, {}))
        used = usage.get(model, 0)
        total = DAILY_LIMITS.get(model, 0) * len(ALL_KEYS)
        msg += f"* **{model}**\n  └ Rate: `{len(ALL_KEYS)-dead}/{len(ALL_KEYS)}` ready | Daily: `{used}/{total}` used\n"
    await ctx.send(msg)

@bot.command(name="update")
async def update(ctx):
    if ctx.author.id not in ADMIN_IDS: return await ctx.send("⛔ Denied.")
    await ctx.send(f"🔄 Pulling latest code for **{BOT_VERSION}** and recycling container...")
    with open("update_channel.txt", "w") as f: f.write(str(ctx.channel.id))
    sys.exit(0)

async def fetch_history(ctx, args):
    raw_input = args.strip()
    transcript_list = []
    base_url = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/"

    # Resolve message targets
    links = re.findall(r'https://discord\.com/channels/\d+/\d+/(\d+)', raw_input)
    if len(links) >= 2:
        s_id, e_id = sorted([int(links[0]), int(links[1])])
        target_history = ctx.channel.history(after=await ctx.channel.fetch_message(s_id), before=await ctx.channel.fetch_message(e_id), oldest_first=True, limit=300)
    elif ctx.message.reference:
        target_history = ctx.channel.history(after=await ctx.channel.fetch_message(ctx.message.reference.message_id), oldest_first=True, limit=200)
    else:
        numbers = re.findall(r'\d+', raw_input)
        val = int(numbers[0]) if numbers else 50
        if "min" in raw_input.lower() or "hour" in raw_input.lower():
            mins = val if "min" in raw_input.lower() else val * 60
            target_history = ctx.channel.history(after=discord.utils.utcnow() - timedelta(minutes=mins), oldest_first=True)
        else:
            target_history = ctx.channel.history(limit=min(val, 300))

    async for msg in target_history:
        if msg.author.bot or msg.id == ctx.message.id: continue
        
        # --- REACTION LOGIC ---
        rx_str = ""
        if msg.reactions:
            rx_list = [f"{str(r.emoji)}x{r.count}" for r in msg.reactions]
            rx_str = f" (REACTIONS: {', '.join(rx_list)})"
            
        transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}{rx_str}")
    
    return transcript_list

async def process_ai_request(ctx, prompt, title, update_stats=False):
    async with ctx.typing():
        response = None
        used_model = ""
        now = datetime.now()
        
        for model_name in MODEL_CHAIN:
            if model_name not in exhausted_tracker: exhausted_tracker[model_name] = {}
            for i, key in enumerate(ALL_KEYS):
                if i in exhausted_tracker[model_name] and now < exhausted_tracker[model_name][i]: continue
                try:
                    client = genai.Client(api_key=key)
                    response = await asyncio.to_thread(client.models.generate_content, model=model_name, contents=prompt)
                    used_model = model_name
                    
                    # Update Usage Stats
                    today = now.strftime('%Y-%m-%d')
                    data = load_json_data("usage_stats.json")
                    if today not in data: data[today] = {m: 0 for m in MODEL_CHAIN}
                    data[today][model_name] = data[today].get(model_name, 0) + 1
                    save_json_data("usage_stats.json", data)
                    break 
                except errors.ClientError as e:
                    if "429" in str(e): exhausted_tracker[model_name][i] = now + timedelta(seconds=65)
                    continue
                except: continue
            if response: break
            
        if not response: return await ctx.send("🔄 All keys rate-limited.")
        
        # --- TOKEN AUDIT ---
        meta = response.usage_metadata
        token_info = f"📊 **Token Audit:** `In: {meta.prompt_token_count}` | `Out: {meta.candidates_token_count}` | `Total: {meta.total_token_count}`"

        await ctx.send(f"### {title} for {ctx.author.mention}\n> **Model:** `{used_model}`")
        sections = response.text.split("---SPLIT---")
        
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

        for s in sections:
            content = s.strip()
            if content and "WINNER:" not in content:
                for j in range(0, len(content), 1900): await ctx.send(content[j:j+1900])
        
        await ctx.send(token_info)

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    try: await ctx.message.add_reaction("✅")
    except: pass
    
    transcript = await fetch_history(ctx, args)
    if not transcript: return
    
    # --- ENHANCED BULLET POINT PROMPT ---
    prompt = (
        f"Summarize the conversation clearly. Use '---SPLIT---' between sections.\n"
        f"Emojis in transcript are user reactions; use them to gauge sentiment.\n\n"
        f"# 📝 SUMMARIES\n"
        f"Group by user display name. Format: **[Name]**: followed by a list of bullet points detailing their actions or points made.\n\n"
        f"# 📈 CORTISOL SPIKES\n"
        f"Note any toxic behavior or high-tension arguments.\n\n"
        f"# MOGG DATA (INTERNAL)\n"
        f"WINNER: [Name] | LOSER: [Name]\n\n"
        f"TRANSCRIPT:\n" + "\n".join(transcript)
    )
    await process_ai_request(ctx, prompt, "Summary", update_stats=True)

if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)
