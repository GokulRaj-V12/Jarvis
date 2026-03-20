"""
LLM Service — Gemini (primary) with automatic Groq fallback on rate limit.

Priority chain:
  1. Gemini 2.0 Flash  (Google AI, free tier: 15 RPM)
  2. Groq Llama-3.3-70b (Groq, free tier: 30 RPM, very fast)
  3. Friendly error message if both fail
"""
import logging
import config

logger = logging.getLogger(__name__)

# --- Gemini setup ---
import google.generativeai as genai
genai.configure(api_key=config.GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel("gemini-2.0-flash")

# --- Groq setup (fallback) ---
_groq_client = None
if config.GROQ_API_KEY:
    from groq import Groq
    _groq_client = Groq(api_key=config.GROQ_API_KEY)
    logger.info("Groq fallback client initialized (model: llama-3.3-70b-versatile)")
else:
    logger.warning("GROQ_API_KEY not set — Groq fallback will be unavailable.")


def _is_rate_limit_error(e: Exception) -> bool:
    """Detect if an exception is a rate limit / quota error."""
    msg = str(e).lower()
    return any(keyword in msg for keyword in [
        "429", "rate limit", "resource_exhausted", "quota", "too many requests"
    ])


def _build_prompt(prompt: str, context: str, system_prompt: str) -> str:
    full = system_prompt + "\n\n"
    if context:
        full += f"--- CONTEXT (use this to personalize your response) ---\n{context}\n--- END CONTEXT ---\n\n"
    full += f"User message: {prompt}"
    return full


async def _try_gemini(full_prompt: str) -> str:
    """Call Gemini 2.0 Flash."""
    response = _gemini_model.generate_content(full_prompt)
    return response.text.strip()


async def _try_groq(prompt: str, context: str, system_prompt: str) -> str:
    """Call Groq Llama-3.3-70b as fallback."""
    if not _groq_client:
        raise RuntimeError("Groq client not configured — add GROQ_API_KEY to .env")

    messages = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({
            "role": "system",
            "content": f"Context about the user:\n{context}"
        })
    messages.append({"role": "user", "content": prompt})

    response = _groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=500,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


async def generate(prompt: str, context: str = "", system: str = "") -> str:
    """
    Generate a response with automatic fallback.
    Tries Gemini first; if rate limited, falls back to Groq.
    """
    system_prompt = system or config.SYSTEM_PROMPT
    full_prompt = _build_prompt(prompt, context, system_prompt)

    # --- Attempt 1: Gemini ---
    try:
        result = await _try_gemini(full_prompt)
        logger.info("Response generated via Gemini 2.0 Flash")
        return result
    except Exception as e:
        if _is_rate_limit_error(e):
            logger.warning(f"Gemini rate limited — switching to Groq fallback. Error: {e}")
        else:
            logger.error(f"Gemini error (non-rate-limit): {e}")
            # For non-rate-limit errors, still try Groq before giving up
            logger.info("Trying Groq as fallback for non-rate-limit Gemini error...")

    # --- Attempt 2: Groq fallback ---
    try:
        result = await _try_groq(prompt, context, system_prompt)
        logger.info("Response generated via Groq Llama-3.3-70b (fallback)")
        return result
    except Exception as e:
        logger.error(f"Groq fallback also failed: {e}")
        return "I'm having trouble connecting right now. Give me a moment and try again! 🐾"


async def generate_embedding(text: str) -> list[float]:
    """Generate embedding vector for text using the raw REST API to bypass gRPC bugs."""
    import aiohttp
    import json
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={config.GEMINI_API_KEY}"
    
    async with aiohttp.ClientSession() as session:
        payload = {
            "model": "models/text-embedding-004",
            "content": {"parts": [{"text": text}]}
        }
        headers = {"Content-Type": "application/json"}
        
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(f"Embedding REST API failed: {response.status} - {error_text}")
            
            data = await response.json()
            return data["embedding"]["values"]
