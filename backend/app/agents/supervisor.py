import time
import json
import re
import structlog
import google.generativeai as genai
from pydantic import BaseModel
from typing import Literal

from backend.app.agents.graph import AgentState
from backend.app.core.config import settings

logger = structlog.get_logger()

genai.configure(api_key=settings.GEMINI_API_KEY)


class RoutingDecision(BaseModel):
    route: Literal["retriever", "summarizer", "synthesizer"]
    reason: str


SUPERVISOR_PROMPT = """You are routing a user question to the correct handler.

Rules:
- "retriever": user asks a specific question about document content
- "summarizer": user explicitly asks to summarize a document
- "synthesizer": general conversation, greetings, or questions not about documents

Question: {question}

Respond with ONLY valid JSON on a single line, no markdown, no newlines:
{{"route": "retriever", "reason": "explanation"}}"""


def extract_json(text: str) -> dict:
    """Extracts JSON from text, handling markdown code fences."""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON found in: {text}")


def supervisor_node(state: AgentState) -> dict:
    start_time = time.time()
    question = state["question"]

    logger.info("Supervisor analyzing question", question=question[:100])

    try:
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        response = model.generate_content(
            SUPERVISOR_PROMPT.format(question=question),
            generation_config=genai.GenerationConfig(
                temperature=0,
                max_output_tokens=100,
            )
        )

        data = extract_json(response.text)
        decision = RoutingDecision(**data)
        route = decision.route
        reason = decision.reason

    except Exception as e:
        logger.warning("Supervisor fallback", error=str(e))
        q_lower = question.lower()
        if any(w in q_lower for w in ["summarize", "summary", "overview", "brief"]):
            route = "summarizer"
        elif any(w in q_lower for w in ["hello", "hi", "what can you", "who are you", "help"]):
            route = "synthesizer"
        else:
            route = "retriever"
        reason = f"Keyword-based fallback: {route}"

    latency = int((time.time() - start_time) * 1000)
    logger.info("Supervisor decision", route=route, reason=reason, latency_ms=latency)

    return {
        "route": route,
        "nodes_invoked": ["supervisor"],
        "agent_trace": [{
            "node": "supervisor",
            "route": route,
            "reason": reason,
            "latency_ms": latency,
        }],
        "tokens_used": 0,
        "latency_ms": latency,
    }