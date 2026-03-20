"""
RAG Service — ChromaDB for vector storage + retrieval.
Handles PDF parsing, chunking, embedding, and semantic search.
"""
import chromadb
from chromadb.config import Settings
import config
from services import llm_service
import fitz  # PyMuPDF
import asyncio

# Initialize ChromaDB
_client = chromadb.Client(Settings(
    persist_directory=config.CHROMA_PERSIST_DIR,
    anonymized_telemetry=False,
    is_persistent=True,
))


def _get_collection(user_id: int):
    """Get or create a ChromaDB collection for a user."""
    return _client.get_or_create_collection(
        name=f"user_{user_id}",
        metadata={"hnsw:space": "cosine"},
    )


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks of ~chunk_size tokens (rough char estimate)."""
    # Rough: 1 token ≈ 4 chars
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
    """Embed and store text chunks for a user."""
    collection = _get_collection(user_id)
    for i, chunk in enumerate(texts):
        embedding = await llm_service.generate_embedding(chunk)
        collection.add(
            ids=[f"{source}_{i}"],
            embeddings=[embedding],
            documents=[chunk],
            metadatas=[{"source": source, "chunk_index": i}],
        )


async def add_log_to_rag(user_id: int, log_text: str, log_date: str):
    """Add a daily log entry to RAG for future retrieval."""
    collection = _get_collection(user_id)
    embedding = await llm_service.generate_embedding(log_text)
    doc_id = f"log_{log_date}_{hash(log_text) % 10000}"
    collection.add(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[log_text],
        metadatas=[{"source": "daily_log", "date": log_date}],
    )


async def query(user_id: int, question: str, k: int = 5) -> list[str]:
    """Retrieve the top-k most relevant chunks for a question."""
    collection = _get_collection(user_id)

    if collection.count() == 0:
        return []

    embedding = await llm_service.generate_embedding(question)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=min(k, collection.count()),
    )
    return results["documents"][0] if results["documents"] else []


async def ingest_pdf(user_id: int, file_bytes: bytes) -> int:
    """Parse a PDF, chunk it, embed it, and store in ChromaDB. Returns chunk count."""
    text = parse_pdf(file_bytes)
    chunks = chunk_text(text)
    await add_documents(user_id, chunks, source="autobiography")
    return len(chunks)


async def ingest_text(user_id: int, text: str, source: str = "autobiography") -> int:
    """Chunk, embed, and store raw text. Returns chunk count."""
    chunks = chunk_text(text)
    await add_documents(user_id, chunks, source=source)
    return len(chunks)
