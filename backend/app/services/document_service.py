import os
import uuid
import time
from pathlib import Path
from typing import Optional
import structlog

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pypdf import PdfReader
from docx import Document as DocxDocument

import google.generativeai as genai

from backend.app.core.config import settings
from backend.app.db.models import Document, DocumentStatus
from backend.app.services.vector_service import vector_service

logger = structlog.get_logger()

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

# Chunking settings
CHUNK_SIZE = 500        # words per chunk
CHUNK_OVERLAP = 50      # words repeated between chunks


class DocumentService:
    """
    Handles the full document ingestion pipeline:
    upload → extract → chunk → embed → store
    """

    # ── Text extraction ───────────────────────────────────────────────────────

    def extract_text_from_pdf(self, file_path: str) -> str:
        """
        Extracts all text from a PDF file.
        pypdf reads each page and joins the text.
        """
        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        full_text = "\n\n".join(pages)
        logger.info("PDF text extracted", pages=len(reader.pages), chars=len(full_text))
        return full_text

    def extract_text_from_docx(self, file_path: str) -> str:
        """
        Extracts all text from a DOCX file.
        python-docx reads each paragraph.
        """
        doc = DocxDocument(file_path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        full_text = "\n\n".join(paragraphs)
        logger.info("DOCX text extracted", paragraphs=len(paragraphs), chars=len(full_text))
        return full_text

    def extract_text(self, file_path: str, filename: str) -> str:
        """
        Routes to the correct extractor based on file extension.
        """
        ext = Path(filename).suffix.lower()
        if ext == ".pdf":
            return self.extract_text_from_pdf(file_path)
        elif ext in [".docx", ".doc"]:
            return self.extract_text_from_docx(file_path)
        elif ext == ".txt":
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    # ── Chunking ──────────────────────────────────────────────────────────────

    def split_into_chunks(self, text: str) -> list[str]:
        """
        Splits text into overlapping word chunks.

        Example with CHUNK_SIZE=5, CHUNK_OVERLAP=2:
        "A B C D E F G H I J"
        Chunk 1: "A B C D E"
        Chunk 2: "D E F G H"   ← D E repeated (overlap)
        Chunk 3: "G H I J"

        This ensures context is not lost at boundaries.
        """
        words = text.split()
        chunks = []
        start = 0

        while start < len(words):
            end = start + CHUNK_SIZE
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)
            chunks.append(chunk_text)

            # Move forward by (CHUNK_SIZE - CHUNK_OVERLAP)
            # so next chunk starts CHUNK_OVERLAP words back
            start += CHUNK_SIZE - CHUNK_OVERLAP

        logger.info("Text split into chunks", total_chunks=len(chunks))
        return chunks

    # ── Embedding ─────────────────────────────────────────────────────────────

    def embed_text(self, text: str) -> list[float]:
        """
        Converts text to a vector using Gemini embedding model.
        Returns a list of 768 floats.
        """
        result = genai.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            content=text,
            task_type="RETRIEVAL_DOCUMENT",  # optimized for document storage
        )
        return result["embedding"]

    def embed_query(self, query: str) -> list[float]:
        """
        Converts a search query to a vector.
        Uses task_type="retrieval_query" — slightly different from document embedding.
        This asymmetry improves search quality.
        """
        result = genai.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            content=query,
            task_type="RETRIEVAL_QUERY",
        )
        return result["embedding"]

    # ── Full pipeline ─────────────────────────────────────────────────────────

    async def ingest_document(
        self,
        file_path: str,
        filename: str,
        user_id: str,
        document_id: str,
        db: AsyncSession,
    ) -> int:
        """
        Full ingestion pipeline:
        1. Extract text from file
        2. Split into chunks
        3. Embed each chunk with Gemini
        4. Store in Qdrant
        5. Update document status in PostgreSQL

        Returns: number of chunks indexed
        """
        # Make sure Qdrant collection exists
        await vector_service.ensure_collection()

        # Update status to "indexing"
        await self._update_status(db, document_id, DocumentStatus.indexing)

        try:
            # Step 1 — extract text
            text = self.extract_text(file_path, filename)
            if not text.strip():
                raise ValueError("No text could be extracted from the file")

            # Step 2 — split into chunks
            chunk_texts = self.split_into_chunks(text)

            # Step 3 — embed each chunk
            # We add a small delay to avoid hitting Gemini rate limits
            embedded_chunks = []
            for i, chunk_text in enumerate(chunk_texts):
                embedding = self.embed_text(chunk_text)
                embedded_chunks.append({
                    "text": chunk_text,
                    "embedding": embedding,
                    "index": i,
                })
                if i % 10 == 0:
                    logger.info("Embedding progress", chunk=i, total=len(chunk_texts))
                time.sleep(0.1)  # small delay to respect rate limits

            # Step 4 — store in Qdrant
            chunk_count = await vector_service.upsert_chunks(
                chunks=embedded_chunks,
                user_id=user_id,
                document_id=document_id,
                filename=filename,
            )

            # Step 5 — update document status to "indexed"
            await self._update_status(
                db, document_id, DocumentStatus.indexed, chunk_count=chunk_count
            )

            logger.info(
                "Document ingestion complete",
                document_id=document_id,
                chunks=chunk_count,
            )
            return chunk_count

        except Exception as e:
            # Mark document as failed so user knows something went wrong
            await self._update_status(
                db, document_id, DocumentStatus.failed, error=str(e)
            )
            logger.error("Document ingestion failed", document_id=document_id, error=str(e))
            raise

    async def _update_status(
        self,
        db: AsyncSession,
        document_id: str,
        status: DocumentStatus,
        chunk_count: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """Updates the document status in PostgreSQL."""
        result = await db.execute(
            select(Document).where(Document.id == uuid.UUID(document_id))
        )
        doc = result.scalar_one_or_none()
        if doc:
            doc.status = status
            if chunk_count is not None:
                doc.chunk_count = chunk_count
            if error is not None:
                doc.error_message = error
            await db.commit()


# Single shared instance
document_service = DocumentService()
