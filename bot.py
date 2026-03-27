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
async def tldr(ctx, *, args: str = "50"):
    # 1. Robust Parsing: Split the input into a list of words
    parts = args.lower().split()
    value = 50 # Default
    unit = "messages" # Default
    
    # Extract the number and the unit from the string
    for part in parts:
        if part.isdigit():
            value = int(part)
        elif any(u in part for u in ["min", "hour", "hr", "msg", "message"]):
            unit = part

    transcript_list = []
    header_text = ""
    
    # 2. Time Logic vs Count Logic
    if any(u in unit for u in ["min", "hour", "hr"]):
        # It's a TIME request
        if "min" in unit:
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
        # It's a COUNT request
        header_text = f"Summary of the last {value} messages as requested by {ctx.author.mention}"
        
        async for msg in ctx.channel.history(limit=value + 5):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()

    # 3. Validation
    if not transcript_list:
        return await ctx.send(f"No messages found for {header_text.split('as requested')[0].strip()}.")

    # 4. SEND THE HEADER (Ensuring this happens!)
    await ctx.send(header_text)

    # 5. Gemini Processing
    transcript = "\n".join(transcript_list)
    prompt = f"""
    Summarize the following Discord transcript. 
    
    STRICT FORMATTING RULES:
    - Group by person.
    - Header: __DISPLAY_NAME [username]__
    - CRITICAL: NO BOLD (**). Use ONLY double underscores (__) for the header.
    - If you use bolding anywhere, I will fail the task. Plain text bullets only.
    - Separate users with '---SPLIT---'.
    
    TRANSCRIPT:
    {transcript}
    """

    try:
        async with ctx.typing():
            response = model.generate_content(prompt)
            # Remove any accidental bolding Gemini might add anyway
            clean_response = response.text.replace("**", "")
            
            for section in clean_response.split('---SPLIT---'):
                if section.strip():
                    await ctx.send(section.strip())
    except Exception as e:
        print(f"Error: {e}")
        await ctx.send("❌ Summary failed. Check Prometheus logs.")

bot.run(TOKEN)
