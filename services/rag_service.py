"""
RAG Service — Firestore for vector storage + semantic retrieval.
Replacing ChromaDB to enable statelessness on Cloud Run.
"""
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
import config
from services import llm_service
import fitz  # PyMuPDF
import asyncio
import logging

logger = logging.getLogger(__name__)

# Initialize Firestore
db = firestore.Client(project=config.GOOGLE_CLOUD_PROJECT)

def chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks."""
    char_size = chunk_size * 4
    char_overlap = overlap * 4
    chunks = []
    start = 0
    while start < len(text):
        end = start + char_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += char_size - char_overlap
    return chunks

def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    doc.close()
    return text

async def add_documents(user_id: int, texts: list[str], source: str = "autobiography"):
    """Embed and store text chunks in Firestore."""
    coll_ref = db.collection("memories")

    for i, chunk in enumerate(texts):
        embedding = await llm_service.generate_embedding(chunk)
        # Firestore Vector Search requires the vector to be stored as a Vector object
        doc_data = {
            "user_id": user_id,
            "content": chunk,
            "embedding": Vector(embedding),
            "source": source,
            "chunk_index": i,
            "created_at": firestore.SERVER_TIMESTAMP
        }
        coll_ref.add(doc_data)

async def add_log_to_rag(user_id: int, log_text: str, log_date: str):
    """Add a daily log entry to RAG."""
    coll_ref = db.collection("memories")
    embedding = await llm_service.generate_embedding(log_text)
    doc_data = {
        "user_id": user_id,
        "content": log_text,
        "embedding": Vector(embedding),
        "source": "daily_log",
        "date": log_date,
        "created_at": firestore.SERVER_TIMESTAMP
    }
    coll_ref.add(doc_data)

async def query(user_id: int, question: str, k: int = 3) -> list[str]:
    """Retrieve top-k relevant chunks using Firestore Vector Search."""
    collection = db.collection("memories")

    # Generate embedding for the question
    question_vector = await llm_service.generate_embedding(question)

    # Perform vector search
    # This requires a vector index in Firestore!
    try:
        query = collection.where("user_id", "==", user_id)\
            .find_nearest(
                vector_field="embedding",
                query_vector=Vector(question_vector),
                distance_measure=firestore.VectorDistanceMeasure.COSINE,
                limit=k
            )
        results = query.get()
        return [doc.to_dict().get("content", "") for doc in results]
    except Exception as e:
        logger.error(f"Vector search failed (did you create the index?): {e}")
        # Fail gracefully by falling back to just returning nothing or latest logs
        return []

async def ingest_pdf(user_id: int, file_bytes: bytes) -> int:
    """Process a PDF and store in Firestore."""
    text = parse_pdf(file_bytes)
    chunks = chunk_text(text)
    await add_documents(user_id, chunks, source="autobiography")
    return len(chunks)

async def ingest_text(user_id: int, text: str, source: str = "autobiography") -> int:
    """Process raw text and store in Firestore."""
    chunks = chunk_text(text)
    await add_documents(user_id, chunks, source=source)
    return len(chunks)
