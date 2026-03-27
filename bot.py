import discord
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions
import os
import re
import traceback
import math
from datetime import datetime, timedelta

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)

# 2026 Model Priority Chain
MODEL_CHAIN = [
    'gemini-3.1-pro-preview',
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-3.1-flash-lite-preview'
]

# --- BOT SETUP (FIXED INTENTS) ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # <--- CRITICAL: This allows the bot to see Nicknames/Members
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"--- {bot.user.name} ONLINE ---")
    print(f"Privileged Intents: Members={intents.members}")
    print(f"--------------------------")

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        # 1. Fetching Message History
        if is_time_mode:
            delta = timedelta(minutes=value) if "min" in raw_input else timedelta(hours=value)
            summary_info = f"the last {value} {'mins' if 'min' in raw_input else 'hours'}"
            async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
                if msg.author.bot or msg.id == ctx.message.id: continue
                # msg.author.display_name works ONLY if intents.members is True
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

        # 2. THE MULTI-MODEL FALLBACK LOOP
        async with ctx.typing():
            response = None
            used_model = ""

            for model_name in MODEL_CHAIN:
                try:
                    current_model = genai.GenerativeModel(model_name)
                    response = current_model.generate_content(prompt)
                    used_model = model_name
                    break 
                except (exceptions.ResourceExhausted, exceptions.NotFound) as e:
                    reason = "Quota" if isinstance(e, exceptions.ResourceExhausted) else "404 Not Found"
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {model_name} failed ({reason})")
                    continue 
                except Exception as e:
                    raise e

            if not response:
                raise Exception("All models in the chain were unavailable.")

            # 3. Final Output (FIXED HEADER & MENTION)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] SUCCESS | Model: {used_model}")
            
            # Using the Mention attribute triggers the ping notification
            header = f"### Summary for {ctx.author.mention}\n> **Context:** {summary_info} | **Model:** {used_model}"
            await ctx.send(header)
            
            # Sending text with split support in case summary is huge
            summary_text = response.text
            if len(summary_text) > 1900:
                # Simple split if it's too long for Discord's 2000 char limit
                parts = [summary_text[i:i+1900] for i in range(0, len(summary_text), 1900)]
                for p in parts:
                    await ctx.send(p)
            else:
                await ctx.send(summary_text)
                    
    except Exception as e:
        print(f"CRITICAL ERROR: {traceback.format_exc()}")
        await ctx.send(f"❌ **Summary failed.** Check server logs for details.")

bot.run(TOKEN)
