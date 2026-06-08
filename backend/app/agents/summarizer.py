import time
import asyncio
import structlog
import google.generativeai as genai

from backend.app.agents.graph import AgentState
from backend.app.services.vector_service import vector_service
from backend.app.core.config import settings

logger = structlog.get_logger()

genai.configure(api_key=settings.GEMINI_API_KEY)

MAP_PROMPT = """Summarize the following text chunk concisely in 2-3 sentences.
Focus on the key information and main points.

Text: {chunk}

Summary:"""

REDUCE_PROMPT = """You have been given multiple summaries of different parts of a document.
Combine them into one coherent, well-structured final summary.
The summary should be comprehensive but concise (aim for 150-250 words).
Preserve all important facts, numbers, and key points.

Partial summaries:
{summaries}

Final summary:"""


def map_chunk(model, chunk_text: str) -> str:
    """
    Summarizes a single chunk (the MAP step).
    Called once per chunk.
    """
    try:
        response = model.generate_content(
            MAP_PROMPT.format(chunk=chunk_text[:1000]),
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=150,
            )
        )
        return response.text.strip()
    except Exception as e:
        logger.warning("Map step failed for chunk", error=str(e))
        return chunk_text[:200]  # fallback: return truncated original


def reduce_summaries(model, summaries: list[str]) -> str:
    """
    Combines all chunk summaries into one final summary (the REDUCE step).
    """
    combined = "\n\n---\n\n".join(
        [f"Part {i+1}: {s}" for i, s in enumerate(summaries)]
    )
    response = model.generate_content(
        REDUCE_PROMPT.format(summaries=combined),
        generation_config=genai.GenerationConfig(
            temperature=0.3,
            max_output_tokens=400,
        )
    )
    return response.text.strip()


def summarizer_node(state: AgentState) -> dict:
    """
    Summarizer node — map-reduce summarization over document chunks.

    Flow:
    1. Retrieve ALL chunks for the user's documents from Qdrant
    2. MAP: summarize each chunk with Gemini
    3. REDUCE: combine all summaries into one final summary
    4. Pass summary to synthesizer

    Reads from state: user_id, document_ids, question
    Writes to state: summary, retrieved_chunks, nodes_invoked, agent_trace
    """
    start_time = time.time()
    user_id = state["user_id"]
    document_ids = state.get("document_ids")

    logger.info("Summarizer starting", user_id=user_id)

    model = genai.GenerativeModel(settings.GEMINI_MODEL)

    try:
        # Step 1 — get all chunks for the document
        # Use a dummy embedding to get all chunks (high top_k)
        import google.generativeai as genai_embed
        dummy_embedding = genai_embed.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            content="summarize",
            task_type="retrieval_query",
        )["embedding"]

        chunks = asyncio.get_event_loop().run_until_complete(
            vector_service.search(
                query_embedding=dummy_embedding,
                user_id=user_id,
                document_ids=document_ids,
                top_k=50,  # get many chunks for summarization
            )
        )

        if not chunks:
            summary = "No document content found to summarize."
        else:
            logger.info("Summarizing chunks", total=len(chunks))

            # Step 2 — MAP: summarize each chunk
            chunk_summaries = []
            for i, chunk in enumerate(chunks):
                chunk_summary = map_chunk(model, chunk["text"])
                chunk_summaries.append(chunk_summary)
                if (i + 1) % 5 == 0:
                    logger.info("Map progress", done=i+1, total=len(chunks))

            # Step 3 — REDUCE: combine all summaries
            if len(chunk_summaries) == 1:
                summary = chunk_summaries[0]
            else:
                summary = reduce_summaries(model, chunk_summaries)

            logger.info("Summarization complete", summary_length=len(summary))

    except Exception as e:
        logger.error("Summarizer failed", error=str(e))
        summary = f"Summarization failed: {str(e)}"
        chunks = []

    latency = int((time.time() - start_time) * 1000)

    return {
        "summary": summary,
        "retrieved_chunks": chunks if chunks else [],
        "nodes_invoked": ["summarizer"],
        "agent_trace": [{
            "node": "summarizer",
            "chunks_processed": len(chunks) if chunks else 0,
            "latency_ms": latency,
        }],
        "latency_ms": latency,
    }
