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
    embed.add_field(name="📜 By Count", value="`!tldr 50`", inline=True)
    embed.add_field(name="⏰ By Time", value="`!tldr 1 hour`", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="tldr")
async def tldr(ctx, value: str = "50", unit: str = "messages"):
    transcript_list = []
    
    # 1. Fetching Logic
    if unit.lower() in ["hour", "hours", "minute", "minutes", "min", "hr"]:
        amount = int(value)
        delta = timedelta(minutes=amount) if "min" in unit.lower() else timedelta(hours=amount)
        async for msg in ctx.channel.history(after=discord.utils.utcnow() - delta, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id: continue
            # Explicitly labeling fields for the AI
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
    else:
        count = int(value)
        async for msg in ctx.channel.history(limit=count + 5):
            if msg.author.bot or msg.id == ctx.message.id: continue
            transcript_list.append(f"DISPLAY_NAME: {msg.author.display_name} | USERNAME: {msg.author.name} | MESSAGE: {msg.content}")
            if len(transcript_list) >= count: break
        transcript_list.reverse()

    if not transcript_list:
        return await ctx.send("No messages found.")

    # 2. Refined AI Prompt
    transcript = "\n".join(transcript_list)
    prompt = f"""
    Summarize the following Discord transcript. 
    
    STRICT FORMATTING RULES:
    - Group the summary by the person who spoke.
    - Every user section MUST start with their name formatted exactly like this: __DISPLAY_NAME [username]__
    - DO NOT use bold (**). Use only double underscores (__) for underlining the header.
    - Use the 'DISPLAY_NAME' and 'USERNAME' tags provided in the transcript for accuracy.
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
