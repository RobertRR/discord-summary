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
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="🤖 Discord Summarizer Help",
        description="Summarize chat history using Gemini AI.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📜 By Count", value="`!tldr 50` or `!tldr messages 50`", inline=False)
    embed.add_field(name="⏰ By Time", value="`!tldr 1 hour` or `!tldr 30 mins`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="tldr")
async def tldr(ctx, arg1: str = "50", arg2: str = "messages"):
    # 1. Input Handling
    if arg1.isdigit():
        value, unit = int(arg1), arg2.lower()
    elif arg2.isdigit():
        value, unit = int(arg2), arg1.lower()
    else:
        return await ctx.send("❌ Please provide a number (e.g., `!tldr 50` or `!tldr 1 hour`)")

    transcript_list = []
    header_text = ""
    
    # 2. Flexible Time Detection (min, mins, minutes, hour, hours, hr)
    is_time = any(u in unit for u in ["min", "hour", "hr"])
    
    if is_time:
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
        header_text = f"Summary of the last {value} messages as requested by {ctx.author.mention}"
        
        async for msg in ctx.channel.history(limit=value + 5):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()

    if not transcript_list:
        return await ctx.send("No messages found in that range.")

    # 3. Post the Header FIRST as its own message
    await ctx.send(header_text)

    # 4. Prompt for Gemini
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
