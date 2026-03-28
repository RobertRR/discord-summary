# ... (Imports remain the same)
from google.genai import types # Added this to handle Parts correctly

# ... (Version and Logging remain the same)
BOT_VERSION = "v4.7.8 - SDK Payload Fix 🛠️"

# --- COMMANDS ---

@bot.command(name="huh")
async def huh(ctx):
    """
    Contextual Fact-Checker: Uses types.Part for multimodal SDK compatibility.
    """
    if not ctx.message.reference:
        return await ctx.send("❌ You must reply to a message with `!huh` to use this feature.")
    
    target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    media_parts = []
    
    # FIXED: Using types.Part.from_bytes for the new google-genai SDK
    if target.attachments:
        for attachment in target.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'webp']):
                image_bytes = await attachment.read()
                # Create a proper Part object instead of a raw dictionary
                media_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

    prompt = (
        f"CONTEXT: You are explaining a specific post. If it's a tweet/image, describe it.\n"
        f"MESSAGE CONTENT: {target.content}\n"
        f"INSTRUCTIONS: Explain the meaning, check for accuracy, and link a primary source if a claim is false."
    )
    
    await process_ai_request(ctx, prompt, "Explanation & Fact-Check", media_parts=media_parts)

# --- CORE LOGIC UPDATE ---

async def process_ai_request(ctx, prompt, title, update_stats=False, media_parts=None):
    async with ctx.typing():
        response = None
        used_model = ""
        now = datetime.now()
        
        # FIXED: Ensure prompt is the first element in the list, followed by Part objects
        content_payload = [prompt] + (media_parts if media_parts else [])
        
        for model_name in MODEL_CHAIN:
            if model_name not in exhausted_tracker: exhausted_tracker[model_name] = {}
            for i, key in enumerate(ALL_KEYS):
                if i in exhausted_tracker[model_name] and now < exhausted_tracker[model_name][i]: continue
                try:
                    client = genai.Client(api_key=key)
                    # Inference call
                    response = await asyncio.to_thread(
                        client.models.generate_content, 
                        model=model_name, 
                        contents=content_payload
                    )
                    used_model = model_name
                    # ... (Usage stats logic remains same)
                    break 
                except errors.ClientError as e:
                    # IMPROVED: Only treat 429s as rate limits. 
                    # If it's a 400 (Bad Request), it will log as a real error.
                    if "429" in str(e): 
                        exhausted_tracker[model_name][i] = now + timedelta(seconds=65)
                        continue
                    else:
                        log_info(f"API Error ({model_name}): {e}")
                        return await ctx.send(f"⚠️ **API Error:** `{e}`")
                except Exception as e:
                    log_info(f"Unexpected Exception: {e}")
                    continue
            if response: break
            
        if not response: 
            return await ctx.send("🔄 All keys rate-limited or exhausted.")
        
        # ... (Rest of formatting and sending remains the same)
