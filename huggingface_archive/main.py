"""
Jarvis — Personal AI Assistant
Main FastAPI application with Discord background task + API endpoints.
"""
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException

from services import (
    memory_service, 
    rag_service, 
    personality_service, 
    discord_service, 
    scheduler_service
)
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
    logger.info("========================================")
    logger.info("JARVIS APPLICATION STARTING...")
    logger.info("========================================")
    
    # Initialize Core Services
    memory_service.init_db()
    
    # Initialize Discord Bot in the background
    if config.DISCORD_BOT_TOKEN:
        logger.info("[Lifespan] Spawning Discord Bot task...")
        # We use start() instead of run() to avoid blocking the main thread
        asyncio.create_task(discord_service.bot.start(config.DISCORD_BOT_TOKEN))
    else:
        logger.warning("[Lifespan] CRITICAL: No DISCORD_BOT_TOKEN found!")

    # Start scheduler
    scheduler_service.start_scheduler()

    logger.info("[Lifespan] Jarvis is ready for action! 🐾🦾")
    yield

    # Shutdown
    logger.info("[Lifespan] Shutting down Jarvis...")
    scheduler_service.stop_scheduler()
    await discord_service.bot.close()


app = FastAPI(title="Jarvis Personal Assistant", lifespan=lifespan)

@app.get("/")
async def root():
    """Root endpoint to verify Jarvis is alive and stop 404 logs."""
    return {
        "status": "Jarvis is alive! 🤖🐾",
        "platform": "Discord",
        "build": "Stable-DNS-V3"
    }

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
    plan = await discord_service.generate_plan_internal(req.user_id)
    return {"plan": plan}


@app.post("/review_day")
async def api_review_day(req: ReviewRequest):
    """Generate an end-of-day review for a user."""
    review = await discord_service.generate_review_internal(req.user_id)
    return {"review": review}


@app.post("/update_personality")
async def api_update_personality(req: PersonalityUpdateRequest):
    """Trigger a personality profile update for a user."""
    result = await personality_service.update_personality(req.user_id)
    return {"result": result}


@app.get("/health")
async def health():
    return {"status": "alive", "bot": "jarvis-discord"}


if __name__ == "__main__":
    import uvicorn
    # Use 7860 as it's the default port for HF Spaces
    uvicorn.run(app, host="0.0.0.0", port=7860)
