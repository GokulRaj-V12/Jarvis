"""
Telegram Service — bot commands and message handling.
"""
import logging
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from services import memory_service, rag_service, personality_service, llm_service
import config

logger = logging.getLogger(__name__)

import httpx
from telegram.ext import Application
from telegram.request import HTTPXRequest
import json
import time

# Debug instrumentation (NDJSON) for DEBUG MODE.
# Writes to `debug-a1ec73.log` in the current working directory.
DEBUG_LOG_PATH = "debug-a1ec73.log"

def _debug_log(hypothesis_id: str, message: str, data: dict, run_id: str = "prefix"):
    payload = {
        "sessionId": "a1ec73",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": "services/telegram_service.py:build_telegram_app",
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        # Never let debug logging break the app.
        pass

def build_telegram_app(token: str):
    """Builds a high-reliability Telegram app for cloud environments."""
    # Use the official builder methods to inject the custom client
    builder = Application.builder().token(token)

    #region agent log
    _debug_log(
        "H5_telegram_version",
        "python-telegram-bot version",
        {"telegram_version": getattr(__import__("telegram"), "__version__", None)},
    )
    #endregion

    # Console markers to confirm which code path runs on HF.
    # (We also keep the NDJSON file logs for debug mode.)
    print(
        "[telegram_service] ptb_version=",
        getattr(__import__("telegram"), "__version__", None),
        "has_http_client=",
        hasattr(builder, "http_client"),
        "has_get_updates_http_client=",
        hasattr(builder, "get_updates_http_client"),
        flush=True,
    )

    #region agent log
    _debug_log(
        "H1_builder_http_client_present",
        "builder attribute presence",
        {
            "has_http_client": hasattr(builder, "http_client"),
            "has_get_updates_http_client": hasattr(builder, "get_updates_http_client"),
        },
    )
    #endregion

    #region agent log
    _debug_log(
        "H4_alternative_request_methods_present",
        "other request-related attributes",
        {
            "has_request": hasattr(builder, "request"),
            "has_get_updates_request": hasattr(builder, "get_updates_request"),
        },
    )
    #endregion

    # PTB v21.6 doesn't support `.http_client()` / `.get_updates_http_client()`.
    # Instead, configure the HTTP client via `.request(...)` using HTTPXRequest.
    # Important: ignore proxy-related environment variables on cloud runtimes.
    # HF containers sometimes have empty proxy env vars which can cause httpx to fail DNS/connect.
    #
    # Do NOT force IPv4 via `local_address` here; HF networks may only allow IPv6.
    transport = httpx.AsyncHTTPTransport(retries=3)
    httpx_kwargs = {"transport": transport, "trust_env": False}
    #region agent log
    _debug_log(
        "H6_httpxrequest_httpx_kwargs",
        "HTTPXRequest constructed with httpx_kwargs",
        {"httpx_kwargs_keys": list(httpx_kwargs.keys())},
        run_id="post-fix",
    )
    #endregion
    request = HTTPXRequest(httpx_kwargs=httpx_kwargs)

    app = builder.request(request).build()

    #region agent log
    _debug_log(
        "H2_app_build_success",
        "Telegram Application built via builder.request(HTTPXRequest(...))",
        {"app_type": type(app).__name__, "has_bot": hasattr(app, "bot")},
        run_id="post-fix",
    )
    #endregion

    return app

# Initialize the global app instance
print("[telegram_service] Building global Telegram app...", flush=True)
app = build_telegram_app(config.TELEGRAM_BOT_TOKEN)
print("[telegram_service] Global Telegram app built.", flush=True)


# --- Command Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initialize user profile."""
    user = update.effective_user
    memory_service.upsert_user(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        f"Hey {user.first_name}! 👋 I'm Jarvis, your personal AI companion.\n\n"
        f"Here's what I can do:\n"
        f"/log — Tell me about your day\n"
        f"/goal — Set a new goal\n"
        f"/plan — Get today's game plan\n"
        f"/review — End-of-day reflection\n"
        f"/streak — Check your streak 🔥\n"
        f"/weekly — Weekly summary\n\n"
        f"You can also send me a PDF of your autobiography/journal and I'll remember it all.\n\n"
        f"Let's get to work! 💪"
    )


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log daily update."""
    user_id = update.effective_user.id
    text = " ".join(context.args) if context.args else ""

    if not text:
        await update.message.reply_text(
            "Tell me what's up! Use it like:\n"
            "/log Worked on the project for 3 hours. Feeling good but tired."
        )
        return

    # Save to structured DB
    memory_service.save_log(user_id, text)

    # Save to RAG for future retrieval
    today = datetime.now().strftime("%Y-%m-%d")
    await rag_service.add_log_to_rag(user_id, text, today)

    # Get streak
    streak = memory_service.get_streak(user_id)

    await update.message.reply_text(
        f"Logged! ✅\n🔥 Streak: {streak['current_streak']} days\n\nKeep it rolling."
    )


async def cmd_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or view goals."""
    user_id = update.effective_user.id
    text = " ".join(context.args) if context.args else ""

    if not text:
        # Show current goals
        goals = memory_service.get_active_goals(user_id)
        if not goals:
            await update.message.reply_text(
                "No active goals yet. Set one like:\n"
                "/goal Learn Python in 30 days"
            )
            return

        msg = "🎯 Your Goals:\n\n"
        for i, g in enumerate(goals, 1):
            msg += f"{i}. {g['title']}\n"
        msg += "\nTo add a new one: /goal Your new goal here"
        await update.message.reply_text(msg)
        return

    memory_service.save_goal(user_id, text)
    await update.message.reply_text(f"Goal set: {text} 🎯\n\nLet's make it happen.")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate today's plan."""
    user_id = update.effective_user.id
    plan = await generate_plan(user_id)
    await update.message.reply_text(plan)


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """End-of-day review."""
    user_id = update.effective_user.id
    review = await generate_review(user_id)
    await update.message.reply_text(review)


async def cmd_streak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show streak stats."""
    user_id = update.effective_user.id
    streak = memory_service.get_streak(user_id)
    await update.message.reply_text(
        f"🔥 Streak Stats\n\n"
        f"Current streak: {streak['current_streak']} days\n"
        f"Longest streak: {streak['longest_streak']} days\n"
        f"Total logs: {streak['total_logs']}\n\n"
        f"{'Keep going! 💪' if streak['current_streak'] > 0 else 'Start a new streak today with /log!'}"
    )


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Weekly summary."""
    user_id = update.effective_user.id
    summary = await personality_service.generate_weekly_summary(user_id)
    await update.message.reply_text(summary)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PDF uploads."""
    user_id = update.effective_user.id
    document = update.message.document

    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("I can only process PDF files for now. Send me a .pdf!")
        return

    await update.message.reply_text("Got it! Processing your PDF... 📄")

    file = await context.bot.get_file(document.file_id)
    file_bytes = await file.download_as_bytearray()

    chunk_count = await rag_service.ingest_pdf(user_id, bytes(file_bytes))
    await update.message.reply_text(
        f"Done! Processed {chunk_count} chunks from your PDF. "
        f"I'll use this to understand you better. 🧠"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages with RAG-augmented responses."""
    user_id = update.effective_user.id
    text = update.message.text

    # Ensure user exists
    user = update.effective_user
    memory_service.upsert_user(user.id, user.username or "", user.first_name or "")

    # Retrieve relevant context from RAG
    rag_chunks = await rag_service.query(user_id, text, k=3)
    rag_context = "\n".join(rag_chunks) if rag_chunks else ""

    # Build personality context
    personality_context = await personality_service.build_context(user_id)

    # Combine context
    full_context = ""
    if personality_context:
        full_context += personality_context + "\n\n"
    if rag_context:
        full_context += f"## Relevant Memories\n{rag_context}"

    # Generate response
    try:
        response = await llm_service.generate(text, context=full_context)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        await update.message.reply_text("Hmm, something went wrong on my end. Try again in a sec! 🐾")


# --- Plan/Review generators (used by commands + scheduler) ---

async def generate_plan(user_id: int) -> str:
    """Generate a morning plan for the user."""
    personality_context = await personality_service.build_context(user_id)
    rag_chunks = await rag_service.query(user_id, "daily priorities and tasks", k=3)
    rag_context = "\n".join(rag_chunks) if rag_chunks else ""

    context = personality_context
    if rag_context:
        context += f"\n\n## Relevant Memories\n{rag_context}"

    prompt = """Generate a morning plan for today. Include:
1. 3 priority tasks (realistic, focused)
2. One thing to avoid today (based on their patterns)
3. A short motivational line

Keep it SHORT. No fluff. Golden retriever energy."""

    return await llm_service.generate(prompt, context=context)


async def generate_review(user_id: int) -> str:
    """Generate an evening review for the user."""
    today_logs = memory_service.get_today_logs(user_id)
    personality_context = await personality_service.build_context(user_id)

    log_text = "\n".join([l["content"] for l in today_logs]) if today_logs else "No logs today."

    context = personality_context + f"\n\n## Today's Logs\n{log_text}"

    prompt = """Generate a brief end-of-day review. Include:
1. What was accomplished (based on logs)
2. Any blockers noticed
3. One suggestion for tomorrow
4. Score the day out of 10

If no logs were made, gently remind them to log.
Keep it short and encouraging. Golden retriever energy."""

    return await llm_service.generate(prompt, context=context)


async def send_message_to_user(user_id: int, text: str):
    """Send a proactive message to a user (used by scheduler)."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send message to {user_id}: {e}")


# --- Register handlers ---

def register_handlers():
    """Register all command and message handlers."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("goal", cmd_goal))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("streak", cmd_streak))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
