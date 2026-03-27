import discord
from discord.ext import commands
import google.generativeai as genai
import os
import re
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
    print(f"Logged in as {bot.user}")

@bot.command(name="tldr")
async def tldr(ctx, *, args: str = "50"):
    # 1. ROBUST PARSING: Scan the raw input string
    raw_input = args.lower()
    
    # Extract the first number found in the string
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    header_text = ""
    
    # 2. TRIGGER TIME LOGIC: If 'min' or 'hour' exists anywhere in the input
    if "min" in raw_input or "hour" in raw_input or "hr" in raw_input:
        if "min" in raw_input:
            delta = timedelta(minutes=value)
            display_unit = "minutes"
        else:
            delta = timedelta(hours=value)
            display_unit = "hours"
            
        header_text = f"Summary of the last {value} {display_unit} as requested by {ctx.author.mention}"
        
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
    else:
        # Default to Message Count Logic
        header_text = f"Summary of the last {value} messages as requested by {ctx.author.mention}"
        
        async for msg in ctx.channel.history(limit=value + 5):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()

    if not transcript_list:
        return await ctx.send(f"No messages found for {header_text.split('as requested')[0].strip()}.")

    # 3. POST THE HEADER
    await ctx.send(header_text)

    # 4. GEMINI PROCESSING
    transcript = "\n".join(transcript_list)
    prompt = f"""
    Summarize the following Discord transcript. 
    
    STRICT FORMATTING RULES:
    - Group by person.
    - Header Format: __DISPLAY_NAME [username]__
    - CRITICAL: Use NO bold (**) ever. Use ONLY double underscores (__) for the header.
    - Use the 'DISPLAY_NAME' and 'USERNAME' provided in the transcript.
    - Separate users with '---SPLIT---'.
    
    TRANSCRIPT:
    {transcript}
    """

    try:
        async with ctx.typing():
            response = model.generate_content(prompt)
            # STRIP ALL BOLDING: This manually removes any ** added by the AI
            clean_text = response.text.replace("**", "")
            
            for section in clean_text.split('---SPLIT---'):
                if section.strip():
                    await ctx.send(section.strip())
    except Exception as e:
        print(f"Error: {e}")
        await ctx.send("❌ Summary failed. Check logs.")

bot.run(TOKEN)
