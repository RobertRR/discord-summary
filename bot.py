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
    print(f"Logged in as {bot.user} | Prometheus Update: {datetime.now().strftime('%H:%M:%S')}")

@bot.command(name="tldr")
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    summary_info = ""
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

    try:
        # 1. Fetching Logic
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

        # 2. Strict Formatting Prompt
        full_transcript_text = "\n".join(transcript_list)
        prompt = f"""
        Summarize this Discord transcript. Group by user.
        
        OUTPUT FORMAT EXAMPLE (FOLLOW THIS EXACTLY):
        __Display Name [username]__
        * Point one about what they said
        * Point two about their request
        ---SPLIT---

        STRICT RULES:
        1. Use ONLY double underscores (__) for the header.
        2. DO NOT use any bold (**). Strip all bolding.
        3. Use a single asterisk (*) for bullet points.
        4. NO PARAGRAPHS. Only bullet points.
        5. Separate each person's block with '---SPLIT---'.

        TRANSCRIPT:
        {full_transcript_text}
        """

        async with ctx.typing():
            response = model.generate_content(prompt)
            
            if not response.text:
                raise ValueError("Gemini returned an empty response.")

            # Scrub all bolding programmatically
            clean_text = response
