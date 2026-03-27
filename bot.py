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
# Reverting to 2.5-flash as requested for better intelligence/speed
model = genai.GenerativeModel('gemini-2.5-flash')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} | Model: Gemini 2.5 Flash | Sync: {datetime.now().strftime('%H:%M:%S')}")

@bot.command(name="tldr")
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    summary_info = ""
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        # 1. Fetching Logic with Nickname + Global Name support
        if is_time_mode:
            delta = timedelta(minutes=value) if "min" in raw_input else timedelta(hours=value)
            summary_info = f"the last {value} {'minutes' if 'min' in raw_input else 'hours'}"
            
            async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
                if msg.author.bot or msg.id == ctx.message.id: continue
                nick = msg.author.display_name
                global_n = msg.author.global_name or msg.author.name
                transcript_list.append(f"USER: {nick} [{global_n}] | MSG: {msg.content}")
        else:
            summary_info = f"the last {value} messages"
            async for msg in ctx.channel.history(limit=value + 5):
                if msg.author.bot or msg.id == ctx.message.id: continue
                nick = msg.author.display_name
                global_n = msg.author.global_name or msg.author.name
                transcript_list.append(f"USER: {nick} [{global_n}] | MSG: {msg.content}")
                if len(transcript_list) >= value: break
            transcript_list.reverse()

        if not transcript_list:
            return await ctx.send(f"No messages found for {summary_info}.")

        full_transcript_text = "\n".join(transcript_list)
        
        # --- PROMPT RE-TUNED FOR 2.5 FLASH ---
        prompt = f"""
        Provide an intelligent, nuanced summary of this Discord transcript. Group by user.
        
        STRICT FORMATTING RULES:
        - Header: __Nickname [GlobalName]__ (Use double underscores, NO BOLD)
        - List: Use '*' for every bullet point.
        - Detail: Do not just list facts; summarize the intent and tone of the discussion.
        - NO BOLDING (**).
        - Separation: End every user block with '---SPLIT---'.

        TRANSCRIPT:
        {full_transcript_text}
        """

        async with ctx.typing():
            response = model.generate_content(prompt)
            
            if not response.text:
                raise ValueError("AI returned no content.")

            # Scrub all bolding programmatically
            clean_text = response.text.replace("**", "")
            
            await ctx.send(f"Summary of {summary_info} as requested by {ctx.author.mention}")
            
            for section in clean_text.split('---SPLIT---'):
                msg_part = section.strip()
                if msg_part:
                    # Fixes potential formatting glitches where bullets bunch up
                    formatted_part = msg_part.replace(". *", ".\n*")
                    await ctx.send(formatted_part)
                    
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        traceback.print_exc()
        await ctx.send(f"❌ Summary failed. Check the logs.")

bot.run(TOKEN)
