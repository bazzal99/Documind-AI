import time
import structlog
import google.generativeai as genai

from backend.app.agents.graph import AgentState
from backend.app.services.document_service import document_service
from backend.app.services.vector_service import vector_service
from backend.app.core.config import settings

logger = structlog.get_logger()

genai.configure(api_key=settings.GEMINI_API_KEY)

RERANK_PROMPT = """Rate how relevant this text chunk is for answering the question.
Score from 0.0 (not relevant) to 1.0 (highly relevant).
Respond with a single float number only.

Question: {question}
Text chunk: {chunk}

Score:"""


def rerank_chunks(question: str, chunks: list[dict], top_k: int = 3) -> list[dict]:
    """Reranks retrieved chunks using Gemini."""
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    scored = []

    for chunk in chunks:
        try:
            response = model.generate_content(
                RERANK_PROMPT.format(
                    question=question,
                    chunk=chunk["text"][:500]
                ),
                generation_config=genai.GenerationConfig(
                    temperature=0,
                    max_output_tokens=10,
                )
            )
            score = float(response.text.strip())
            scored.append({**chunk, "rerank_score": score})
        except Exception:
            scored.append({**chunk, "rerank_score": chunk.get("score", 0.5)})

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored[:top_k]


async def retriever_node(state: AgentState) -> dict:
    """
    Retriever node — searches documents for relevant chunks.
    Made async to work properly inside LangGraph's async context.
    """
    start_time = time.time()
    question = state["question"]
    user_id = state["user_id"]
    document_ids = state.get("document_ids")

    logger.info("Retriever searching", question=question[:100], user_id=user_id)

    try:
        # Embed the question
        query_embedding = document_service.embed_query(question)

        # Search Qdrant directly with await (no event loop workaround needed)
        chunks = await vector_service.search(
            query_embedding=query_embedding,
            user_id=user_id,
            document_ids=document_ids,
            top_k=10,
        )

        if not chunks:
            logger.warning("No chunks found in Qdrant", user_id=user_id)
            retrieved_chunks = []
        else:
            # retrieved_chunks = rerank_chunks(question, chunks, top_k=3)
            retrieved_chunks = chunks[:3]
            logger.info(
                "Retrieval complete",
                initial_chunks=len(chunks),
                after_rerank=len(retrieved_chunks),
            )

    except Exception as e:
        logger.error("Retriever failed", error=str(e))
        retrieved_chunks = []

    latency = int((time.time() - start_time) * 1000)

    return {
        "retrieved_chunks": retrieved_chunks,
        "nodes_invoked": ["retriever"],
        "agent_trace": [{
            "node": "retriever",
            "chunks_found": len(retrieved_chunks),
            "latency_ms": latency,
        }],
        "latency_ms": latency,
    }