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
model = genai.GenerativeModel('gemini-2.5-flash')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} | System Time: {datetime.now().strftime('%H:%M:%S')}")

@bot.command(name="tldr")
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    summary_info = ""
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        # 1. FETCH LOGIC
        if is_time_mode:
            if "min" in raw_input:
                delta = timedelta(minutes=value)
                summary_info = f"the last {value} minutes"
            else:
                delta = timedelta(hours=value)
                summary_info = f"the last {value} hours"
            
            async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
        else:
            summary_info = f"the last {value} messages"
            async for msg in ctx.channel.history(limit=value + 5):
                if msg.author.bot or msg.id == ctx.message.id: continue
                transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
                if len(transcript_list) >= value: break
            transcript_list.reverse()

        if not transcript_list:
            return await ctx.send(f"No messages found for {summary_info}.")

        # 2. PROMPT BUILDING
        full_transcript_text = "\n".join(transcript_list)
        prompt = f"""
        Summarize this Discord transcript into concise bullet points. Group by user.
        
        STRICT FORMATTING:
        - Header: __Display Name [username]__
        - Body: Use a single asterisk (*) for bullet points.
        - NO BOLDING (**).
        - NO PARAGRAPHS.
        - Split each user with '---SPLIT---'.

        TRANSCRIPT:
        {full_transcript_text}
        """

        # 3. GENERATION
        async with ctx.typing():
            response = model.generate_content(prompt)
            
            if not response or not response.text:
                await ctx.send("❌ Gemini returned no data.")
                return

            # Programmatically strip all double asterisks (bolding)
            clean_text = response.text.replace("**", "")
            
            # Send initial tag message
            await ctx.send(f"Summary of {summary_info} as requested by {ctx.author.mention}")
            
            # Send each user section
            sections = clean_text.split('---SPLIT---')
            for section in sections:
                final_output = section.strip()
                if final_output:
                    await ctx.send(final_output)

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        traceback.print_exc()
        await ctx.send(f"❌ Error encountered: {str(e)[:100]}")

bot.run(TOKEN)
