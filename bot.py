import discord
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions
import re
import traceback
import asyncio
import functools
import sys
import os
import logging
import json
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

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

# --- FILE & DATA PERSISTENCE ---
def load_file(filename):
    try:
        path = os.path.join(os.getcwd(), filename)
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log_info("CRITICAL: {} not found in {}".format(filename, os.getcwd()))
        return []

def load_mogg_data():
    path = os.path.join(os.getcwd(), "mogg_stats.json")
    if not os.path.exists(path):
        return {}
    
    try:
        with open(path, "r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        log_info("mogg_stats.json error: {}. Returning empty dict.".format(e))
        return {}

def save_mogg_data(data):
    path = os.path.join(os.getcwd(), "mogg_stats.json")
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        log_info("Failed to save mogg_stats.json: {}".format(e))

token_list = load_file("discordtoken.txt")
DISCORD_TOKEN = token_list[0] if token_list else None
ALL_KEYS = load_file("keys.txt")
ADMIN_IDS = [int(i) for i in load_file("admins.txt")]

# --- API KEY MANAGER ---
exhausted_tracker = {}
def configure_genai(key_index):
    genai.configure(api_key=ALL_KEYS[key_index])

if ALL_KEYS:
    configure_genai(0)

MODEL_CHAIN = ['gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-3.1-flash-lite-preview']

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

@bot.event
async def on_ready():
    log_info("--- {} ONLINE ---".format(bot.user.name))
    await asyncio.sleep(2)
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    if os.path.exists(update_file):
        try:
            with open(update_file, "r") as f:
                content = f.read().strip()
                if content:
                    channel_id = int(content)
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send("✅ **Update Completed:** The bot is back online.")
        except Exception as e:
            log_info("Failed to post update message: {}".format(e))
        finally:
            if os.path.exists(update_file):
                os.remove(update_file)

# --- RANKING LOGIC ---
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

# --- COMMANDS ---

@bot.command(name="help")
async def help_command(ctx):
    help_text = (
        "### 🤖 Bot Commands\n"
        "* **!tldr [amount]**\n"
        "  Summarizes activity with jump-links.\n\n"
        "* **!arguments [amount]**\n"
        "  Analyzes conflicts and updates the Moggboard.\n\n"
        "* **!moggboard**\n"
        "  View the server power rankings.\n\n"
        "* **!keystatus**\n"
        "  Check AI API key health.\n\n"
        "* **!update**\n"
        "  **(Admin)** Pulls code and restarts."
    )
    await ctx.send(help_text)

@bot.command(name="moggboard")
async def moggboard(ctx):
    data = load_mogg_data()
    if not data:
        return await ctx.send("The Moggboard is currently empty. Start some beef with `!arguments`!")

    # Sorting logic: Ratio first, then total wins
    sorted_users = sorted(
        data.items(), 
        key=lambda x: (x[1]['wins']/(x[1]['wins']+x[1]['losses'] or 1), x[1]['wins']), 
        reverse=True
    )

    msg = "## 🏆 THE OFFICIAL MOGGBOARD\n"
    msg += "| Rank | User | Wins | Losses | Ratio | Class |\n"
    msg += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"

    for i, (user_name, stats) in enumerate(sorted_users, 1):
        w = stats['wins']
        l = stats['losses']
        total = w + l
        ratio = w / total if total > 0 else 0
        rank_class = get_rank_class(ratio)
        ratio_pct = "{:.1f}%".format(ratio * 100)
        
        msg += "| #{} | **{}** | {} | {} | {} | *{}* |\n".format(i, user_name, w, l, ratio_pct, rank_class)

    await ctx.send(msg)

@bot.command(name="update")
async def update(ctx):
    if ctx.author.id not in ADMIN_IDS:
        return await ctx.send("⛔ **Access Denied.**")
    await ctx.send("🔄 **Update Triggered.** Restarting...")
    update_file = os.path.join(os.getcwd(), "update_channel.txt")
    try:
        with open(update_file, "w") as f:
            f.write(str(ctx.channel.id))
            f.flush()
            os.fsync(f.fileno())
    except: pass
    sys.exit(0)

@bot.command(name="keystatus")
async def keystatus(ctx):
    if not exhausted_tracker:
        await ctx.send("✅ All keys are fresh.")
        return
    msg = "### 🔑 API Key Status\n"
    for model in MODEL_CHAIN:
        dead = len(exhausted_tracker.get(model, []))
        msg += "* **{}:** {}/{} Keys Available\n".format(model, len(ALL_KEYS)-dead, len(ALL_KEYS))
    await ctx.send(msg)

# --- CORE LOGIC ---

async def get_ai_response_async(model, prompt):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(model.generate_content, prompt))

async def fetch_history(ctx, args):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    transcript_list = []
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])
    base_url = "https://discord.com/channels/{}/{}/".format(ctx.guild.id, ctx.channel.id)

    if is_time_mode:
        delta = timedelta(minutes=value) if "min" in raw_input else timedelta(hours=value)
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append("USER: {} | LINK: {}{} | MSG: {}".format(msg.author.display_name, base_url, msg.id, msg.content))
    else:
        async for msg in ctx.channel.history(limit=value + 10):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append("USER: {} | LINK: {}{} | MSG: {}".format(msg.author.display_name, base_url, msg.id, msg.content))
            if len(transcript_list) >= value: break
        transcript_list.reverse()
    return transcript_list

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    full_transcript = "\n".join(transcript)
    prompt = "Summarize this Discord transcript grouped by user. Use [Jump to Message](URL) for significant posts.\n\nTRANSCRIPT:\n{}".format(full_transcript)
    await process_ai_request(ctx, prompt, "Summary")

@bot.command(name="arguments")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def arguments(ctx, *, args: str = "50"):
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")
    full_transcript = "\n".join(transcript)
    
    prompt = """
    Analyze the following Discord transcript for disagreements.
    
    # CONFLICT SUMMARY
    Briefly list each argument found. State who was involved.

    # KEY POINTS
    Side A vs Side B. Use [Context](URL) links for major points.

    # VERDICT
    Analyze who is logically 'more right'.

    # MOGG RATING
    State clearly who mogged who. 
    Use the format: "WINNER: [Name] | LOSER: [Name]" if a clear mogging occurred.

    RULES:
    - Use '---SPLIT---' to separate these 4 sections.
    - If no argument exists, say 'The vibes are currently immaculate'.
    
    TRANSCRIPT:
    {}
    """.format(full_transcript)
    await process_ai_request(ctx, prompt, "Argument Analysis", update_stats=True)

async def process_ai_request(ctx, prompt, title_prefix, update_stats=False):
    async with ctx.typing():
        response = None
        used_model = ""
        for model_name in MODEL_CHAIN:
            for i in range(len(ALL_KEYS)):
                if i in exhausted_tracker.get(model_name, []): continue
                try:
                    configure_genai(i)
                    current_model = genai.GenerativeModel(model_name)
                    response = await get_ai_response_async(current_model, prompt)
                    used_model = model_name
                    break 
                except Exception: continue
            if response: break

        if not response:
            return await ctx.send("🔄 Quotas hit. Try again later.")

        await ctx.send("### {} for {}\n> **Model:** {}".format(title_prefix, ctx.author.mention, used_model))
        
        raw_output = response.text
        sections = raw_output.split("---SPLIT---")

        # Handle Stats Update (Internal Parsing)
        if update_stats:
            mogg_section = sections[-1] if len(sections) >= 4 else ""
            match = re.search(r"WINNER:\s*(.*?)\s*\|\s*LOSER:\s*(.*)", mogg_section, re.IGNORECASE)
            if match:
                winner = match.group(1).strip()
                loser = match.group(2).strip()
                data = load_mogg_data()
                
                for p in [winner, loser]:
                    if p not in data: data[p] = {"wins": 0, "losses": 0}
                
                data[winner]["wins"] += 1
                data[loser]["losses"] += 1
                save_mogg_data(data)
                log_info("Moggboard Updated: {} > {}".format(winner, loser))

        for section in sections:
            content = section.strip()
            if content:
                for j in range(0, len(content), 1900):
                    await ctx.send(content[j:j+1900])

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
