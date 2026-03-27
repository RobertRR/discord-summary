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

# --- FILE LOADER ---
def load_file(filename):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log_info(f"CRITICAL: {filename} not found!")
        return []

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
    log_info(f"--- {bot.user.name} ONLINE ---")
    if ADMIN_IDS:
        try:
            admin = await bot.fetch_user(ADMIN_IDS[0])
            await admin.send(f"✅ **System Online:** Bot has restarted and is running the latest version from GitHub.")
        except Exception as e:
            log_info(f"Could not send boot notification: {e}")

# --- COMMANDS ---

@bot.command(name="help")
async def help_command(ctx):
    help_text = (
        "### 🤖 Bot Commands\n"
        "* **!tldr [amount]**\n"
        "  Summarizes recent activity. Examples: `!tldr 50`, `!tldr 1hr`.\n\n"
        "* **!arguments [amount]**\n"
        "  Analyzes conflicts, creates a stance table, and provides a verdict.\n\n"
        "* **!keystatus**\n"
        "  Check the health and quota of the AI API keys.\n\n"
        "* **!help**\n"
        "  Shows this message.\n\n"
        "**👑 Admin Only**\n"
        "* **!update**\n"
        "  Pulls latest code from GitHub and restarts the bot."
    )
    await ctx.send(help_text)

@bot.command(name="update")
async def update(ctx):
    if ctx.author.id not in ADMIN_IDS:
        return await ctx.send("⛔ **Access Denied.**")
    await ctx.send("🔄 **Update Triggered.** Pulling latest code and restarting...")
    log_info(f"Update initiated by {ctx.author.display_name}. Exiting...")
    sys.exit(0)

@bot.command(name="keystatus")
async def keystatus(ctx):
    if not exhausted_tracker:
        await ctx.send(f"✅ All {len(ALL_KEYS)} keys are fresh.")
        return
    msg = "### 🔑 API Key Status\n"
    for model in MODEL_CHAIN:
        dead = len(exhausted_tracker.get(model, []))
        msg += f"* **{model}:** {len(ALL_KEYS)-dead}/{len(ALL_KEYS)} Keys Available\n"
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

    if is_time_mode:
        delta = timedelta(minutes=value) if "min" in raw_input else timedelta(hours=value)
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}")
    else:
        async for msg in ctx.channel.history(limit=value + 10):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()
    
    return transcript_list

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")

    # Move join outside f-string for Py 3.11 compatibility
    full_transcript = "\n".join(transcript)
    prompt = f"""
    Summarize this Discord transcript grouped by user.
    STRICT FORMATTING RULES:
    1. Start each user section with the name underlined like this: __Nickname__
    2. DO NOT put spaces between the underscores and the name.
    3. Use bullet points (*) for details.
    4. DO NOT use bolding (**) anywhere.
    5. Use '---SPLIT---' between different users.
    
    TRANSCRIPT:
    {full_transcript}
    """
    await process_ai_request(ctx, prompt, "Summary")

@bot.command(name="arguments")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def arguments(ctx, *, args: str = "50"):
    transcript = await fetch_history(ctx, args)
    if not transcript: return await ctx.send("No messages found.")

    # Move join outside f-string for Py 3.11 compatibility
    full_transcript = "\n".join(transcript)
    prompt = f"""
    Analyze the following Discord transcript for arguments or disagreements.
    
    1. Create a Markdown Table summarizing each argument:
       | Users Involved | Topic of Argument | Stance/Side A | Stance/Side B |
    2. Provide a 'Key Points' breakdown for each side.
    3. Provide a 'Verdict' analyzing who is logically or factually 'more right' based ONLY on the text provided.
    
    If no clear argument is found, state that the vibes are currently immaculate.
    DO NOT use bolding (**) in the output.
    Use '---SPLIT---' to separate logical sections.
    
    TRANSCRIPT:
    {full_transcript}
    """
    await process_ai_request(ctx, prompt, "Argument Analysis")

async def process_ai_request(ctx, prompt, title_prefix):
    async with ctx.typing():
        response = None
        used_model = ""
        used_key_num = 0

        for model_name in MODEL_CHAIN:
            for i in range(len(ALL_KEYS)):
                if i in exhausted_tracker.get(model_name, []): continue
                try:
                    configure_genai(i)
                    current_model = genai.GenerativeModel(model_name)
                    response = await get_ai_response_async(current_model, prompt)
                    used_model = model_name
                    used_key_num = i + 1
                    break 
                except (exceptions.ResourceExhausted, exceptions.InternalServerError):
                    if model_name not in exhausted_tracker: exhausted_tracker[model_name] = []
                    exhausted_tracker[model_name].append(i)
                    continue
            if response: break

        if not response:
            exhausted_tracker.clear()
            return await ctx.send("🔄 Quotas hit. Try again in a moment.")

        header = f"### {title_prefix} for {ctx.author.mention}\n> **Model:** {used_model} | **Key:** #{used_key_num}"
        await ctx.send(header)
        
        clean_text = response.text.replace("**", "")
        clean_text = re.sub(r'__\s*(.*?)\s*__', r'__\1__', clean_text)
        sections = clean_text.split("---SPLIT---")
        
        for section in sections:
            content = section.strip()
            if content:
                for j in range(0, len(content), 1900):
                    await ctx.send(content[j:j+1900])

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    log_info("CRITICAL: No token found in discordtoken.txt")
