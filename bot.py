import discord
from discord.ext import commands
import google.generativeai as genai
import os
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
async def tldr(ctx, arg1: str = "50", arg2: str = "messages"):
    # 1. Improved Input Parsing
    # Determine which is the number and which is the label
    if arg1.isdigit():
        value, label = int(arg1), arg2.lower()
    elif arg2.isdigit():
        value, label = int(arg2), arg1.lower()
    else:
        return await ctx.send("❌ Usage: `!tldr 50` or `!tldr 10 mins`")

    transcript_list = []
    header_text = ""
    
    # Check for any time-related keywords in the label
    time_units = ["min", "mins", "minute", "minutes", "hour", "hours", "hr", "hrs"]
    is_time_request = any(unit in label for unit in time_units)

    # 2. Fetching Logic
    if is_time_request:
        if any(m in label for m in ["min", "minute"]):
            delta = timedelta(minutes=value)
            display_unit = "minutes"
        else:
            delta = timedelta(hours=value)
            display_unit = "hours"
            
        header_text = f"Summary of the last {value} {display_unit} as requested by {ctx.author.mention}"
        
        # Fetching by Time
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
    else:
        # Defaulting to Message Count
        header_text = f"Summary of the last {value} messages as requested by {ctx.author.mention}"
        
        async for msg in ctx.channel.history(limit=value + 5):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()

    if not transcript_list:
        return await ctx.send(f"No messages found in {header_text.split('as requested')[0].strip()}.")

    # 3. THE FIX: Post the Header explicitly
    await ctx.send(header_text)

    # 4. Gemini Processing
    transcript = "\n".join(transcript_list)
    prompt = f"""
    Summarize the following Discord transcript. 
    
    STRICT FORMATTING RULES:
    - Group by person.
    - Header: __DISPLAY_NAME [username]__ (Underline only, NO bold).
    - Separate users with '---SPLIT---'.
    - Use the provided DISPLAY_NAME and USERNAME tags accurately.
    
    TRANSCRIPT:
    {transcript}
    """

    try:
        async with ctx.typing():
            response = model.generate_content(prompt)
            for section in response.text.split('---SPLIT---'):
                if section.strip():
                    await ctx.send(section.strip())
    except Exception as e:
        print(f"Error: {e}")
        await ctx.send("❌ Gemini failed to process the summary.")

bot.run(TOKEN)
