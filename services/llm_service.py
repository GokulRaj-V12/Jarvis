"""
LLM Service — abstraction over Gemini (free) and OpenAI (paid).
"""
import config

if config.LLM_PROVIDER == "openai":
    from openai import OpenAI

    _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
else:
    import google.generativeai as genai

    genai.configure(api_key=config.GEMINI_API_KEY)
    _gemini_model = genai.GenerativeModel("gemini-2.0-flash")


async def generate(prompt: str, context: str = "", system: str = "") -> str:
    """Generate a response from the LLM with optional context injection."""
    system_prompt = system or config.SYSTEM_PROMPT

    full_prompt = system_prompt + "\n\n"
    if context:
        full_prompt += f"--- CONTEXT (use this to personalize your response) ---\n{context}\n--- END CONTEXT ---\n\n"
    full_prompt += f"User message: {prompt}"

    try:
        if config.LLM_PROVIDER == "openai":
            response = _openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt},
                ],
                max_tokens=500,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        else:
            response = _gemini_model.generate_content(full_prompt)
            return response.text.strip()
    except Exception as e:
        return f"Sorry, I hit a snag: {e}"


async def generate_embedding(text: str) -> list[float]:
    """Generate embedding vector for text (used by RAG)."""
    if config.LLM_PROVIDER == "openai":
        response = _openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
    else:
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
        )
        return result["embedding"]
