import discord
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions  # Added this for precise error catching
import os
import re
import traceback
import math
from datetime import datetime, timedelta

TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"--- BOT ONLINE ---")
    print(f"Logged in as: {bot.user}")
    print(f"Sync Time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"------------------")

@bot.command(name="tldr")
@commands.cooldown(1, 30, commands.BucketType.channel)
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    summary_info = ""
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        if is_time_mode:
            delta = timedelta(minutes=value) if "min" in raw_input else timedelta(hours=value)
            summary_info = f"the last {value} {'minutes' if 'min' in raw_input else 'hours'}"
            async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"USER: {msg.author.display_name} [{msg.author.global_name or msg.author.name}] | MSG: {msg.content}")
        else:
            summary_info = f"the last {value} messages"
            async for msg in ctx.channel.history(limit=value + 10):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"USER: {msg.author.display_name} [{msg.author.global_name or msg.author.name}] | MSG: {msg.content}")
                if len(transcript_list) >= value: break
            transcript_list.reverse()

        if not transcript_list:
            return await ctx.send(f"No messages found for {summary_info}.")

        full_transcript_text = "\n".join(transcript_list)
        prompt = f"""
        Provide a nuanced summary of this transcript. Group by user.
        Header: __Nickname [GlobalName]__ (No Bold)
        Bullet points (*) only. NO BOLDING (**).
        End each user block with '---SPLIT---'.
        TRANSCRIPT:
        {full_transcript_text}
        """

        async with ctx.typing():
            # Attempt AI generation
            response = model.generate_content(prompt)
            
            usage = response.usage_metadata
            print(f"[{datetime.now().strftime('%H:%M:%S')}] SUCCESS | Tokens: {usage.total_token_count}")

            if not response.text:
                raise ValueError("AI returned no content.")

            clean_text = response.text.replace("**", "")
            await ctx.send(f"Summary of {summary_info} as requested by {ctx.author.mention}")
            
            for section in clean_text.split('---SPLIT---'):
                msg_part = section.strip()
                if msg_part:
                    formatted_part = msg_part.replace(". *", ".\n*")
                    await ctx.send(formatted_part)
                    
    # --- SPECIFIC GOOGLE ERROR CATCHING ---
    except exceptions.ResourceExhausted as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] QUOTA EXHAUSTED: 20/20 Limit reached.")
        await ctx.send("🛑 **Daily Limit Reached.** I've used my 20 free summaries for the day. Please try again in 24 hours!")
    
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        traceback.print_exc()
        await ctx.send(f"❌ Summary failed. Check the host logs.")

@tldr.error
async def tldr_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        remaining = math.ceil(error.retry_after)
        await ctx.send(f"⏳ **Cooldown active.** Please wait {remaining}s.", delete_after=10)

bot.run(TOKEN)
