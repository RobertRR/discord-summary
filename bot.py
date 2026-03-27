import discord
from discord.ext import commands
import google.generativeai as genai
import os
from datetime import datetime, timedelta

# 1. Configuration
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

intents = discord.Intents.default()
intents.message_content = True
# Removing the default help command to use our custom one
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Prometheus System: Online")

# 2. New Help Command
@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="🤖 Discord Summarizer Help",
        description="I use Gemini AI to summarize chat history by user.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📜 Summarize by Count", 
        value="`!tldr 50` \nSummarizes the last 50 messages.", 
        inline=False
    )
    embed.add_field(
        name="⏰ Summarize by Time", 
        value="`!tldr 1 hour` or `!tldr 30 minutes` \nSummarizes everything within that window.", 
        inline=False
    )
    embed.set_footer(text="Built for Prometheus Home Server")
    await ctx.send(embed=embed)

@bot.command(name="tldr")
async def tldr(ctx, value: str = "50", unit: str = "messages"):
    transcript_list = []
    search_label = ""

    # Logic to fetch history
    if unit.lower() in ["hour", "hours", "minute", "minutes", "min", "hr"]:
        amount = int(value)
        delta = timedelta(minutes=amount) if "min" in unit.lower() else timedelta(hours=amount)
        search_after = discord.utils.utcnow() - delta
        search_label = f"everything since {amount} {unit} ago"
        
        await ctx.send(f"⏳ Scanning messages from the last {amount} {unit}...")
        
        async for msg in ctx.channel.history(after=search_after, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id:
                continue
            # New Formatting: DisplayName (username)
            transcript_list.append(f"{msg.author.display_name} ({msg.author.name}): {msg.content}")
    else:
        count = int(value)
        search_label = f"the last {count} messages"
        await ctx.send(f"📂 Fetching the last {count} messages...")
        
        async for msg in ctx.channel.history(limit=count + 5):
            if msg.author.bot or msg.id == ctx.message.id:
                continue
            # New Formatting: DisplayName (username)
            transcript_list.append(f"{msg.author.display_name} ({msg.author.name}): {msg.content}")
            if len(transcript_list) >= count:
                break
        transcript_list.reverse()

    if not transcript_list:
        await ctx.send("No messages found in that range.")
        return

    # Prepare Prompt
    transcript = "\n".join(transcript_list)
    prompt = f"""
    Summarize this Discord transcript ({search_label}).
    
    FORMATTING RULES:
    - Group by user. 
    - Use this exact header format: __**Display Name (username)**__
    - Use '---SPLIT---' between each user's block.
    - Be concise and focus on key points/actions.
    
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
        print(f"Gemini Error: {e}")
        await ctx.send("❌ Summary failed. Check logs on Prometheus.")

bot.run(TOKEN)
