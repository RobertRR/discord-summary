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
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.command(name="tldr")
async def tldr(ctx, value: str = "50", unit: str = "messages"):
    """
    Usage:
    !tldr 100           -> 100 messages
    !tldr 1 hour        -> Last 1 hour
    !tldr 30 minutes    -> Last 30 mins
    """

    transcript_list = []
    search_label = ""

    # 1. Determine if we are searching by TIME or COUNT
    if unit.lower() in ["hour", "hours", "minute", "minutes", "min", "hr"]:
        # Time-based logic
        amount = int(value)
        if "minute" in unit.lower() or "min" in unit.lower():
            delta = timedelta(minutes=amount)
        else:
            delta = timedelta(hours=amount)

        search_after = discord.utils.utcnow() - delta
        search_label = f"everything since {amount} {unit} ago"

        await ctx.send(f"⏳ Scanning messages from the last {amount} {unit}...")

        async for msg in ctx.channel.history(after=search_after, oldest_first=True):
            if msg.author.bot or msg.id == ctx.message.id:
                continue
            transcript_list.append(f"{msg.author.display_name}: {msg.content}")

    else:
        # Message count logic (Default)
        count = int(value)
        search_label = f"the last {count} messages"

        await ctx.send(f"📂 Fetching the last {count} messages...")

        async for msg in ctx.channel.history(limit=count + 5):
            if msg.author.bot or msg.id == ctx.message.id:
                continue
            transcript_list.append(f"{msg.author.display_name}: {msg.content}")
            if len(transcript_list) >= count:
                break
        # History is newest -> oldest, so reverse it for the AI
        transcript_list.reverse()

    if not transcript_list:
        await ctx.send("Empty handed! No recent messages found to summarize.")
        return

    # 2. Prepare the prompt
    transcript = "\n".join(transcript_list)
    prompt = f"""
    Summarize this Discord transcript ({search_label}).

    FORMATTING:
    - Group by user using: __**USERNAME**__
    - Use '---SPLIT---' between each user's block.
    - Be punchy and keep it to the main points.

    TRANSCRIPT:
    {transcript}
    """

    # 3. Generate with Gemini
    try:
        async with ctx.typing():
            response = model.generate_content(prompt)
            for section in response.text.split('---SPLIT---'):
                if section.strip():
                    await ctx.send(section.strip())
    except Exception as e:
        print(f"Gemini Error: {e}")
        await ctx.send("❌ Something went wrong with the summary. Try a shorter timeframe.")

bot.run(TOKEN)
