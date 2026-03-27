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
    # Adding a timestamp so you can see exactly when the script last loaded
    print(f"Logged in as {bot.user} | Load Time: {datetime.now().strftime('%H:%M:%S')}")

@bot.command(name="tldr")
async def tldr(ctx, *, args: str = "50"):
    raw_input = args.lower()
    numbers = re.findall(r'\d+', raw_input)
    value = int(numbers[0]) if numbers else 50
    
    transcript_list = []
    summary_info = ""
    is_time_mode = any(k in raw_input for k in ["min", "hour", "hr"])

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

    # --- REFINED PROMPT FOR BULLETS ---
    prompt = f"""
    Summarize this Discord transcript into concise bullet points.
    
    STRICT RULES:
    - Group by person.
    - Header: __DISPLAY_NAME [username]__
    - FORMAT: Use an asterisk (*) for each bullet point. 
    - NO PARAGRAPHS. Each key point must be its own bullet.
    - NO BOLD (**). Use only double underscores (__) for the header.
    - Use 'DISPLAY_NAME' and 'USERNAME' tags from the transcript.
    - Separate users with '---SPLIT---'.
    
    TRANSCRIPT:
    {transcript_list}
    """

    try:
        async with ctx.typing():
            response = model.generate_content(prompt)
            # The "Nuclear Option": Strip all bolding stars
            clean_text = response.text.replace("**", "")
            
            # Send the announcement header
            await ctx.send(f"Summary of {summary_info} as requested by {ctx.author.mention}")
            
            for section in clean_text.split('---SPLIT---'):
                if section.strip():
                    await ctx.send(section.strip())
                    
    except Exception as e:
        print(f"Error: {e}")
        await ctx.send("❌ Summary failed. Check Prometheus logs.")

bot.run(TOKEN)
