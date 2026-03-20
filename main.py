"""
Jarvis — Personal AI Assistant
Main FastAPI application with Telegram webhook + API endpoints.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from telegram import Update

from services import memory_service, rag_service, personality_service, telegram_service, scheduler_service
from models.schemas import PlanRequest, ReviewRequest, PersonalityUpdateRequest
import config

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("Starting Jarvis...")
    memory_service.init_db()
    telegram_service.register_handlers()

    # Initialize telegram app
    await telegram_service.app.initialize()
    await telegram_service.app.start()

    # Set webhook if URL is configured
    if config.WEBHOOK_URL:
        webhook_url = f"{config.WEBHOOK_URL}/webhook"
        await telegram_service.app.bot.set_webhook(webhook_url)
        logger.info(f"Telegram webhook set: {webhook_url}")
    else:
        logger.info("No WEBHOOK_URL set — use polling for local dev (see README)")

    # Start scheduler
    scheduler_service.start_scheduler()

    logger.info("Jarvis is online! 🤖")
    yield

    # Shutdown
    logger.info("Shutting down Jarvis...")
    scheduler_service.stop_scheduler()
    await telegram_service.app.stop()
    await telegram_service.app.shutdown()


app = FastAPI(title="Jarvis Personal Assistant", lifespan=lifespan)


# --- Telegram Webhook ---

@app.post("/webhook")
async def telegram_webhook(request: dict):
    """Handle incoming Telegram updates via webhook."""
    update = Update.de_json(request, telegram_service.app.bot)
    await telegram_service.app.process_update(update)
    return {"ok": True}


# --- API Endpoints ---

@app.post("/upload_pdf")
async def upload_pdf(user_id: int, file: UploadFile = File(...)):
    """Upload a PDF for autobiography/journal ingestion."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    content = await file.read()
    chunk_count = await rag_service.ingest_pdf(user_id, content)
    return {"status": "ok", "chunks_processed": chunk_count}


@app.post("/generate_plan")
async def api_generate_plan(req: PlanRequest):
    """Generate a daily plan for a user."""
    plan = await telegram_service.generate_plan(req.user_id)
    return {"plan": plan}


@app.post("/review_day")
async def api_review_day(req: ReviewRequest):
    """Generate an end-of-day review for a user."""
    review = await telegram_service.generate_review(req.user_id)
    return {"review": review}


@app.post("/update_personality")
async def api_update_personality(req: PersonalityUpdateRequest):
    """Trigger a personality profile update for a user."""
    result = await personality_service.update_personality(req.user_id)
    return {"result": result}


@app.get("/health")
async def health():
    return {"status": "alive", "bot": "jarvis"}


# --- Local polling mode (for development) ---

if __name__ == "__main__":
    import asyncio

    async def run_polling():
        """Run bot in polling mode for local development."""
        logger.info("Starting Jarvis in POLLING mode (local dev)...")
        memory_service.init_db()
        telegram_service.register_handlers()
        scheduler_service.start_scheduler()

        # Use polling instead of webhook
        await telegram_service.app.initialize()
        await telegram_service.app.start()
        await telegram_service.app.updater.start_polling(drop_pending_updates=True)

        logger.info("Jarvis is online in polling mode! 🤖 Press Ctrl+C to stop.")

        try:
            # Keep running
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await telegram_service.app.updater.stop()
            await telegram_service.app.stop()
            await telegram_service.app.shutdown()
            scheduler_service.stop_scheduler()

    asyncio.run(run_polling())
