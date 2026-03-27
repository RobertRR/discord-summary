import discord
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions
import os
import re
import traceback
import math
from datetime import datetime, timedelta

TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)

# 2026 Model Priority Chain
# 1. 3.1 Pro (Heavy Reasoning) -> 2. 3 Flash (Fast/Smart) -> 3. 3.1 Flash-Lite (Infinite Quota)
MODEL_CHAIN = [
    'gemini-3.1-pro-preview',      # Best Intelligence
    'gemini-3-flash-preview',      # Fast Preview (Needs the -preview suffix!)
    'gemini-2.5-flash',            # Reliable Middle-ground
    'gemini-3.1-flash-lite-preview' # 2026 Workhorse (High Free-Tier Limits)
]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"--- BOT ONLINE ---")
    print(f"Primary Model: {MODEL_CHAIN[0]}")
    print(f"------------------")

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        # 1. FETCHING DATA
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

        prompt = f"Summarize this Discord transcript. Group by user with bullet points:\n\n" + "\n".join(transcript_list)

        # 2. THE FALLBACK LOOP (The Fix)
        async with ctx.typing():
            response = None
            used_model = ""

            for model_name in MODEL_CHAIN:
                try:
                    current_model = genai.GenerativeModel(model_name)
                    response = current_model.generate_content(prompt)
                    used_model = model_name
                    break # Success! Exit the loop.
                except (exceptions.ResourceExhausted, exceptions.NotFound) as e:
                    # Logs why it's skipping to the next model
                    error_type = "Quota Hit" if isinstance(e, exceptions.ResourceExhausted) else "ID Not Found"
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Skipping {model_name} ({error_type})")
                    continue 
                except Exception as e:
                    # If it's a safety filter or other error, don't try the next model
                    raise e

            if not response:
                raise Exception("All models in the chain failed.")

            # 3. OUTPUT
            usage = response.usage_metadata
            print(f"[{datetime.now().strftime('%H:%M:%S')}] SUCCESS | Model: {used_model} | Tokens: {usage.total_token_count}")
            
            await ctx.send(f"**Summary of {summary_info}** (Generated via {used_model})")
            await ctx.send(response.text[:2000]) # Discord 2000 char limit safety
                    
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        await ctx.send(f"❌ **Summary failed.** I tried all models in my chain but they are either exhausted or unavailable.")

@tldr.error
async def tldr_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Wait {math.ceil(error.retry_after)}s.", delete_after=5)

bot.run(TOKEN)
