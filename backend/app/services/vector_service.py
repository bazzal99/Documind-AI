from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
from typing import Optional
import uuid
import structlog
from backend.app.core.config import settings

logger = structlog.get_logger()

# Embedding dimension for Gemini embedding-001 model
EMBEDDING_DIM = 3072


class VectorService:
    """
    Wraps Qdrant vector database operations.
    All vector storage and search goes through this class.
    """

    def __init__(self):
        self._client: Optional[QdrantClient] = None

    def get_client(self) -> QdrantClient:
        """Returns Qdrant client, creating it if needed."""
        if self._client is None:
            self._client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )
        return self._client

    async def ensure_collection(self) -> None:
        """
        Creates the Qdrant collection if it doesn't exist.
        Called once on startup.
        A collection is like a table — stores all document vectors.
        """
        client = self.get_client()
        collections = client.get_collections().collections
        names = [c.name for c in collections]

        if settings.QDRANT_COLLECTION not in names:
            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,      # must match embedding model output
                    distance=Distance.COSINE, # cosine similarity for text
                ),
            )
            logger.info("Qdrant collection created", name=settings.QDRANT_COLLECTION)
        else:
            logger.info("Qdrant collection exists", name=settings.QDRANT_COLLECTION)

    async def upsert_chunks(
        self,
        chunks: list[dict],
        user_id: str,
        document_id: str,
        filename: str,
    ) -> int:
        """
        Stores document chunks in Qdrant.
        Each chunk has: text, embedding vector, and metadata.

        Args:
            chunks: list of {"text": str, "embedding": list[float], "index": int}
            user_id: to namespace chunks per user
            document_id: to link chunks back to the document
            filename: for display in citations

        Returns: number of chunks stored
        """
        client = self.get_client()

        points = [
            PointStruct(
                id=str(uuid.uuid4()),     # unique ID for each chunk
                vector=chunk["embedding"],
                payload={
                    "text": chunk["text"],           # actual text content
                    "user_id": user_id,              # for filtering by user
                    "document_id": document_id,      # for filtering by document
                    "filename": filename,            # for citations
                    "chunk_index": chunk["index"],   # position in original doc
                },
            )
            for chunk in chunks
        ]

        client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=points,
        )

        logger.info("Chunks stored in Qdrant", count=len(points), document_id=document_id)
        return len(points)

    async def search(
        self,
        query_embedding: list[float],
        user_id: str,
        document_ids: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Searches for the most relevant chunks for a query.

        Args:
            query_embedding: the query converted to a vector
            user_id: only search this user's documents
            document_ids: optionally limit to specific documents
            top_k: how many chunks to return

        Returns: list of {"text": str, "filename": str, "score": float, "chunk_index": int}
        """
        client = self.get_client()

        # Always filter by user_id so users only see their own documents
        must_conditions = [
            FieldCondition(key="user_id", match=MatchValue(value=user_id))
        ]

        # Optionally filter by specific documents
        if document_ids:
            must_conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_ids[0])  # simple case
                )
            )

        results = client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=query_embedding,
            query_filter=Filter(must=must_conditions),
            limit=top_k,
            with_payload=True,   # return the text and metadata
        )

        return [
            {
                "text": r.payload["text"],
                "filename": r.payload["filename"],
                "document_id": r.payload["document_id"],
                "chunk_index": r.payload["chunk_index"],
                "score": round(r.score, 4),
            }
            for r in results
        ]

    async def delete_document_chunks(self, document_id: str) -> None:
        """
        Deletes all chunks belonging to a document.
        Called when a user deletes a document.
        """
        client = self.get_client()
        client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id)
                    )
                ]
            ),
        )
        logger.info("Document chunks deleted from Qdrant", document_id=document_id)


# Single shared instance
vector_service = VectorService()
