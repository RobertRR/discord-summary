import discord
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions
import os
import re
import traceback
import math
from datetime import datetime, timedelta

# --- API KEY MANAGER ---
def load_keys():
    try:
        with open("keys.txt", "r") as f:
            # Filters out empty lines and whitespace
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("CRITICAL: keys.txt not found in the bot directory!")
        return []

ALL_KEYS = load_keys()
# Dictionary to track which keys are "Dead" for which models
# Format: { "model_name": [list_of_exhausted_key_indices] }
exhausted_tracker = {}

def configure_genai(key_index):
    genai.configure(api_key=ALL_KEYS[key_index])

if not ALL_KEYS:
    print("CRITICAL: No API keys found. Bot will fail to initialize.")
else:
    configure_genai(0)

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MODEL_CHAIN = [
    'gemini-3.1-pro-preview',
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-3.1-flash-lite-preview'
]

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"--- {bot.user.name} ONLINE ---")
    print(f"Keys Loaded: {len(ALL_KEYS)}")
    print(f"Logic: Key-Priority Fallback")
    print(f"--------------------------")

# --- COMMANDS ---

@bot.command(name="keystatus")
async def keystatus(ctx):
    """Shows which models have exhausted which keys."""
    if not exhausted_tracker:
        await ctx.send(f"✅ **All {len(ALL_KEYS)} keys are fresh** across all models.")
        return

    status_msg = "### 🔑 API Key Status\n"
    for model in MODEL_CHAIN:
        dead_keys = exhausted_tracker.get(model, [])
        count = len(ALL_KEYS) - len(dead_keys)
        status_msg += f"* **{model}:** {count}/{len(ALL_KEYS)} Keys Available\n"
    
    await ctx.send(status_msg)

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

            # Step 1: Loop through Models (Strongest first)
            for model_name in MODEL_CHAIN:
                # Step 2: Loop through Keys for THIS specific model
                for i in range(len(ALL_KEYS)):
                    # Skip key if we already know it's dead for this specific model
                    if i in exhausted_tracker.get(model_name, []):
                        continue

                    try:
                        configure_genai(i)
                        current_model = genai.GenerativeModel(model_name)
                        response = current_model.generate_content(prompt)
                        used_model = model_name
                        used_key_num = i + 1
                        break # Found a working Key/Model combo!
                    
                    except (exceptions.ResourceExhausted, exceptions.InternalServerError):
                        # Mark this key as dead for THIS model
                        if model_name not in exhausted_tracker:
                            exhausted_tracker[model_name] = []
                        exhausted_tracker[model_name].append(i)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Key {i+1} Exhausted for {model_name}.")
                        continue
                    
                    except exceptions.NotFound:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Model {model_name} not found. Skipping model entirely.")
                        break # Move to next model in MODEL_CHAIN
                
                if response: break # Exit model loop if we got a result

            # Final check: If EVERYTHING failed, reset the tracker and try one last time
            if not response:
                print("--- ALL KEYS/MODELS EXHAUSTED. RESETTING TRACKER ---")
                exhausted_tracker.clear()
                await ctx.send("🛑 **All quotas hit.** Resetting key tracker and retrying once...")
                # Recurse once to see if anything reset
                return await tldr(ctx, args=args)

            # 3. Output
            header = f"### Summary for {ctx.author.mention}\n> **Context:** {summary_info} | **Model:** {used_model} | **Key:** #{used_key_num}"
            await ctx.send(header)
            
            summary_text = response.text
            if len(summary_text) > 1900:
                parts = [summary_text[i:i+1900] for i in range(0, len(summary_text), 1900)]
                for p in parts: await ctx.send(p)
            else:
                await ctx.send(summary_text)
                    
    except Exception as e:
        print(f"CRITICAL ERROR: {traceback.format_exc()}")
        await ctx.send(f"❌ **Summary failed.** All keys are currently locked out.")

bot.run(TOKEN)
