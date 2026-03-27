import discord
from discord.ext import commands
import google.generativeai as genai
import os
import re
import traceback
from datetime import datetime, timedelta

TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)
# Using 2.0-flash as it's generally more stable for strict formatting
model = genai.GenerativeModel('gemini-2.0-flash')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} | Sync Time: {datetime.now().strftime('%H:%M:%S')}")

@bot.command(name="tldr")
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    summary_info = ""
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        if is_time_mode:
            if "min" in raw_input:
                delta = timedelta(minutes=value)
                summary_info = f"the last {value} minutes"
            else:
                delta = timedelta(hours=value)
                summary_info = f"the last {value} hours"
            
            async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | MESSAGE: {msg.content}")
        else:
            summary_info = f"the last {value} messages"
            async for msg in ctx.channel.history(limit=value + 5):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | MESSAGE: {msg.content}")
                if len(transcript_list) >= value: break
            transcript_list.reverse()

        if not transcript_list:
            return await ctx.send(f"No messages found for {summary_info}.")

        full_transcript_text = "\n".join(transcript_list)
        
        # --- ENHANCED PROMPT ---
        prompt = f"""
        Summarize this Discord transcript. Group by user.
        
        STRICT RULES:
        - Header Format: __Display Name__
        - Content Format: Use a bulleted list ONLY. 
        - Start every single point with an asterisk (*).
        - ONE bullet point per sentence.
        - ABSOLUTELY NO paragraphs or long blocks of text.
        - NO BOLDING (**).
        - End each user's section with '---SPLIT---'.

        TRANSCRIPT:
        {full_transcript_text}
        """

        async with ctx.typing():
            response = model.generate_content(prompt)
            
            if not response.text:
                raise ValueError("Gemini returned an empty response.")

            # Scrub all bolding
            clean_text = response.text.replace("**", "")
            
            # Send the header
            await ctx.send(f"Summary of {summary_info} as requested by {ctx.author.mention}")
            
            # Send the summaries
            for section in clean_text.split('---SPLIT---'):
                msg_part = section.strip()
                if msg_part:
                    # Final safety check: ensure Discord sees the bullets as a list
                    # This replaces any accidental "single-line" bullets with proper newlines
                    formatted_part = msg_part.replace(". *", ".\n*")
                    await ctx.send(formatted_part)
                    
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        traceback.print_exc()
        await ctx.send(f"❌ Summary failed. Error: {str(e)}")

bot.run(TOKEN)
