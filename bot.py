import discord
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions
import re
import traceback
import math
from datetime import datetime, timedelta

# --- FILE LOADER HELPERS ---
def load_file(filename):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"CRITICAL: {filename} not found!")
        return []

# Load Discord Token
token_list = load_file("discordtoken.txt")
DISCORD_TOKEN = token_list[0] if token_list else None

# Load Gemini Keys
ALL_KEYS = load_file("keys.txt")

# --- API KEY MANAGER ---
exhausted_tracker = {}

def configure_genai(key_index):
    genai.configure(api_key=ALL_KEYS[key_index])

if ALL_KEYS:
    configure_genai(0)

# --- CONFIGURATION ---
MODEL_CHAIN = [
    'gemini-3.1-pro-preview',
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-3.1-flash-lite-preview'
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"--- {bot.user.name} ONLINE ---")
    print(f"Keys: {len(ALL_KEYS)} | Token Loaded: {'Yes' if DISCORD_TOKEN else 'No'}")

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

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    transcript_list = []
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        # 1. Fetching History
        if is_time_mode:
            delta = timedelta(minutes=value) if "min" in raw_input else timedelta(hours=value)
            summary_info = f"the last {value} {'mins' if 'min' in raw_input else 'hours'}"
            async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}")
        else:
            summary_info = f"the last {value} messages"
            async for msg in ctx.channel.history(limit=value + 10):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"USER: {msg.author.display_name} | MSG: {msg.content}")
                if len(transcript_list) >= value: break
            transcript_list.reverse()

        if not transcript_list:
            return await ctx.send(f"No messages found for {summary_info}.")

        prompt = f"Summarize this transcript by user with bullet points:\n\n" + "\n".join(transcript_list)

        # 2. KEY-PRIORITY LOGIC
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
                        response = current_model.generate_content(prompt)
                        used_model = model_name
                        used_key_num = i + 1
                        break 
                    except (exceptions.ResourceExhausted, exceptions.InternalServerError):
                        if model_name not in exhausted_tracker: exhausted_tracker[model_name] = []
                        exhausted_tracker[model_name].append(i)
                        continue
                    except exceptions.NotFound:
                        break 
                if response: break

            if not response:
                exhausted_tracker.clear()
                await ctx.send("🔄 Quotas hit. Resetting and retrying...")
                return await tldr(ctx, args=args)

            # 3. Output
            header = f"### Summary for {ctx.author.mention}\n> **Context:** {summary_info} | **Model:** {used_model} | **Key:** #{used_key_num}"
            await ctx.send(header)
            await ctx.send(response.text[:1900])
                    
    except Exception as e:
        print(f"ERROR: {traceback.format_exc()}")
        await ctx.send(f"❌ Summary failed.")

if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("CRITICAL: No token found in discordtoken.txt")
