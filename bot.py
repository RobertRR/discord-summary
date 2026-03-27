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
        log_info("CRITICAL: {} not found!".format(filename))
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
    log_info("--- {} ONLINE ---".format(bot.user.name))
    
    # Check if we were in the middle of an update
    if os.path.exists("update_channel.txt"):
        try:
            with open("update_channel.txt", "r") as f:
                channel_id = int(f.read().strip())
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.send("✅ **Update Completed:** The bot has successfully restarted and is now running the latest code.")
        except Exception as e:
            log_info("Failed to send update completion message: {}".format(e))
        finally:
            # Always delete the file so it doesn't spam on every normal reboot
            if os.path.exists("update_channel.txt"):
                os.remove("update_channel.txt")

# --- COMMANDS ---

@bot.command(name="help")
async def help_command(ctx):
    help_text = (
        "### 🤖 Bot Commands\n"
        "* **!tldr [amount]**\n"
        "  Summarizes activity with jump-links to messages.\n\n"
        "* **!arguments [amount]**\n"
        "  Analyzes conflicts, identifies who got mogged, and provides verdicts.\n\n"
        "* **!keystatus**\n"
        "  Check AI API key health.\n\n"
        "* **!update**\n"
        "  **(Admin)** Pulls code and restarts."
    )
    await ctx.send(help_text)

@bot.command(name="update")
async def update(ctx):
    if ctx.author.id not in ADMIN_IDS:
        return await ctx.send("⛔ **Access Denied.**")
    
    await ctx.send("🔄 **Update Triggered.** Pulling latest code and restarting...")
    
    # Save the current channel ID to a file so we know where to post after restart
    with open("update_channel.txt", "w") as f:
        f.write(str(ctx.channel.id))
        
    log_info("Update initiated by {}. Restarting...".format(ctx.author.display_name))
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
    prompt = """
    Summarize this Discord transcript. Group by user.
    For each user's summary points, use the provided LINKs in the transcript to create a Masked Link [Jump to Message](URL) next to their most significant contributions.
    
    TRANSCRIPT:
    {}
    """.format(full_transcript)
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
    Briefly list each argument found. State who was involved and the core disagreement. 
    Do NOT include links in this section.

    # KEY POINTS
    Break down Side A and Side B using bullet points.
    For every major point raised, you MUST use the corresponding LINK from the transcript to create a masked link: [Context](URL).

    # VERDICT
    Analyze who is logically or factually 'more right'.

    # MOGG RATING
    Assess if anyone in the conversation has been 'mogged'.

    RULES:
    - Use '---SPLIT---' to separate these 4 sections.
    - If no argument exists, say 'The vibes are currently immaculate'.
    
    TRANSCRIPT:
    {}
    """.format(full_transcript)
    await process_ai_request(ctx, prompt, "Argument Analysis")

async def process_ai_request(ctx, prompt, title_prefix):
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
                except Exception:
                    continue
            if response: break

        if not response:
            return await ctx.send("🔄 Quotas hit. Try again later.")

        await ctx.send("### {} for {}\n> **Model:** {}".format(title_prefix, ctx.author.mention, used_model))
        
        raw_output = response.text
        sections = raw_output.split("---SPLIT---")
        for section in sections:
            content = section.strip()
            if content:
                for j in range(0, len(content), 1900):
                    await ctx.send(content[j:j+1900])

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
