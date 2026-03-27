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
    embed.add_field(name="⏰ By Time", value="`!tldr 1 hour` or `!tldr 30 minutes`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="tldr")
async def tldr(ctx, arg1: str = "50", arg2: str = "messages"):
    # Smart Input Handling: Figure out which is the number and which is the unit
    if arg1.isdigit():
        value, unit = int(arg1), arg2.lower()
    elif arg2.isdigit():
        value, unit = int(arg2), arg1.lower()
    else:
        return await ctx.send("❌ Please provide a number (e.g., `!tldr 50` or `!tldr 1 hour`)")

    transcript_list = []
    
    # 1. Fetching Logic
    if unit in ["hour", "hours", "minute", "minutes", "min", "hr"]:
        delta = timedelta(minutes=value) if "min" in unit else timedelta(hours=value)
        await ctx.send(f"⏳ Scanning messages from the last {value} {unit}...")
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
    else:
        await ctx.send(f"📂 Fetching the last {value} messages...")
        async for msg in ctx.channel.history(limit=value + 5):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
            if len(transcript_list) >= value: break
        transcript_list.reverse()

    if not transcript_list:
        return await ctx.send("No messages found.")

    # 2. Refined AI Prompt with your strict formatting
    transcript = "\n".join(transcript_list)
    prompt = f"""
    Summarize the following Discord transcript. 
    
    STRICT FORMATTING RULES:
    - Group the summary by the person who spoke.
    - Every user section MUST start with their name formatted exactly like this: __DISPLAY_NAME [username]__
    - DO NOT use bold (**). Use only double underscores (__) for the header.
    - Use 'DISPLAY_NAME' and 'USERNAME' tags from the transcript for the header.
    - Separate each user's summary block with '---SPLIT---'.
    
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
        await ctx.send("❌ Summary failed.")

bot.run(TOKEN)
