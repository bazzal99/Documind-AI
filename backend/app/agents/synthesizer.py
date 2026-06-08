import time
import structlog
import google.generativeai as genai

from backend.app.agents.graph import AgentState
from backend.app.core.config import settings

logger = structlog.get_logger()

genai.configure(api_key=settings.GEMINI_API_KEY)

ANSWER_PROMPT = """You are a helpful document assistant. Answer the user's question 
based ONLY on the provided context. If the context doesn't contain enough information 
to answer, say so clearly — do not make up information.

Context from documents:
{context}

User question: {question}

Instructions:
- Answer directly and clearly
- Only use information from the context above
- If you reference specific information, mention which document it came from
- If the context is insufficient, say: "I couldn't find enough information in your documents to answer this question."

Answer:"""

CRITIQUE_PROMPT = """Review this answer and check if it stays faithful to the provided context.

Context: {context}
Question: {question}
Answer: {answer}

Does this answer contain ANY information not found in the context? 
Respond with JSON only: {{"faithful": true/false, "issue": "description or null"}}"""

GENERAL_PROMPT = """You are DocuMind AI, a helpful document intelligence assistant.
Answer this general question helpfully and concisely.

Question: {question}

Answer:"""


def build_context(chunks: list[dict]) -> tuple[str, list[dict]]:
    """
    Builds a context string from retrieved chunks.
    Returns the context string and a list of source citations.
    """
    if not chunks:
        return "", []

    context_parts = []
    sources = []

    for i, chunk in enumerate(chunks):
        context_parts.append(
            f"[Source {i+1} - {chunk['filename']}]:\n{chunk['text']}"
        )
        sources.append({
            "index": i + 1,
            "filename": chunk["filename"],
            "document_id": chunk["document_id"],
            "relevance_score": chunk.get("rerank_score", chunk.get("score", 0)),
        })

    return "\n\n".join(context_parts), sources


def synthesizer_node(state: AgentState) -> dict:
    """
    Synthesizer node — generates the final answer with citations.

    Flow:
    1. Build context from retrieved chunks or summary
    2. Generate answer with Gemini
    3. Self-critique — check for hallucinations
    4. If hallucination detected — regenerate with stricter prompt
    5. Return final answer + sources

    Reads from state: question, retrieved_chunks, summary, route
    Writes to state: final_answer, sources, nodes_invoked, agent_trace
    """
    start_time = time.time()
    question = state["question"]
    route = state.get("route", "retriever")
    retrieved_chunks = state.get("retrieved_chunks") or []
    summary = state.get("summary")

    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    sources = []
    hallucination_detected = False

    try:
        # Case 1 — no documents found, answer generally
        if route == "synthesizer" or (not retrieved_chunks and not summary):
            response = model.generate_content(
                GENERAL_PROMPT.format(question=question),
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=500,
                )
            )
            final_answer = response.text.strip()

        # Case 2 — summarizer ran, use the summary
        elif route == "summarizer" and summary:
            final_answer = summary
            # Build sources from retrieved chunks used during summarization
            _, sources = build_context(retrieved_chunks[:3])

        # Case 3 — retriever ran, answer from chunks
        else:
            context, sources = build_context(retrieved_chunks)

            if not context:
                final_answer = (
                    "I couldn't find relevant information in your documents "
                    "to answer this question. Please make sure your documents "
                    "are fully indexed (status: indexed) and try again."
                )
            else:
                # Generate answer from context
                response = model.generate_content(
                    ANSWER_PROMPT.format(context=context, question=question),
                    generation_config=genai.GenerationConfig(
                        temperature=0.2,   # low temperature = more faithful to context
                        max_output_tokens=600,
                    )
                )
                final_answer = response.text.strip()

                # Self-critique — check for hallucinations
                try:
                    import json
                    critique_response = model.generate_content(
                        CRITIQUE_PROMPT.format(
                            context=context[:2000],  # limit context size
                            question=question,
                            answer=final_answer,
                        ),
                        generation_config=genai.GenerationConfig(
                            temperature=0,
                            max_output_tokens=100,
                        )
                    )
                    raw = critique_response.text.strip()
                    if raw.startswith("```"):
                        raw = raw.split("```")[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                    critique = json.loads(raw.strip())

                    if not critique.get("faithful", True):
                        hallucination_detected = True
                        logger.warning(
                            "Hallucination detected, regenerating",
                            issue=critique.get("issue")
                        )
                        # Regenerate with stricter prompt
                        strict_prompt = (
                            ANSWER_PROMPT.format(context=context, question=question)
                            + "\n\nIMPORTANT: Only use information explicitly stated "
                            "in the context. Do not add any outside knowledge."
                        )
                        response2 = model.generate_content(
                            strict_prompt,
                            generation_config=genai.GenerationConfig(
                                temperature=0,
                                max_output_tokens=600,
                            )
                        )
                        final_answer = response2.text.strip()

                except Exception as e:
                    logger.warning("Self-critique failed", error=str(e))

    except Exception as e:
        logger.error("Synthesizer failed", error=str(e))
        final_answer = f"I encountered an error generating the answer: {str(e)}"

    latency = int((time.time() - start_time) * 1000)

    logger.info(
        "Synthesizer complete",
        answer_length=len(final_answer),
        sources=len(sources),
        hallucination_detected=hallucination_detected,
        latency_ms=latency,
    )

    return {
        "final_answer": final_answer,
        "sources": sources,
        "nodes_invoked": ["synthesizer"],
        "agent_trace": [{
            "node": "synthesizer",
            "sources_used": len(sources),
            "hallucination_detected": hallucination_detected,
            "answer_length": len(final_answer),
            "latency_ms": latency,
        }],
        "latency_ms": latency,
    }
