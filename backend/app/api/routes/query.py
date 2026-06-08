import uuid
import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import structlog

from backend.app.db.session import get_db
from backend.app.db.models import ChatSession, Query, User
from backend.app.api.deps import get_current_user, get_current_user_with_rate_limit
from backend.app.agents.graph import agent_graph

router = APIRouter(prefix="/query", tags=["Query"])
logger = structlog.get_logger()


class QueryRequest(BaseModel):
    """What the client sends when asking a question."""
    question: str
    session_id: Optional[str] = None      # if None, creates a new session
    document_ids: Optional[list[str]] = None  # limit search to specific docs


class QueryResponse(BaseModel):
    """What we return after the agent answers."""
    query_id: str
    session_id: str
    question: str
    answer: str
    sources: list[dict]
    nodes_invoked: list[str]
    agent_trace: list[dict]
    latency_ms: int
    tokens_used: int


@router.post("/", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    current_user: User = Depends(get_current_user_with_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """
    Main chat endpoint — sends a question to the LangGraph agent.

    Flow:
    1. Get or create chat session
    2. Invoke LangGraph agent
    3. Save query + trace to PostgreSQL
    4. Return answer + sources + trace
    """
    start_time = time.time()

    # Validate question
    if not payload.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty",
        )

    # Step 1 — get or create session
    session = await get_or_create_session(
        db=db,
        user_id=current_user.id,
        session_id=payload.session_id,
        question=payload.question,
    )

    logger.info(
        "Query received",
        user_id=str(current_user.id),
        session_id=str(session.id),
        question=payload.question[:100],
    )

    # Step 2 — invoke the LangGraph agent
    try:
        initial_state = {
            "question": payload.question,
            "user_id": str(current_user.id),
            "session_id": str(session.id),
            "document_ids": payload.document_ids,
            "route": None,
            "retrieved_chunks": None,
            "summary": None,
            "final_answer": "",
            "sources": [],
            "nodes_invoked": [],
            "agent_trace": [],
            "tokens_used": 0,
            "latency_ms": 0,
        }

        # Run the agent graph
        result = await agent_graph.ainvoke(initial_state)

    except Exception as e:
        logger.error("Agent invocation failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent failed: {str(e)}",
        )

    total_latency = int((time.time() - start_time) * 1000)

    # Step 3 — save query + trace to PostgreSQL
    query_record = Query(
        id=uuid.uuid4(),
        session_id=session.id,
        question=payload.question,
        answer=result.get("final_answer", ""),
        agent_trace=result.get("agent_trace", []),
        nodes_invoked=result.get("nodes_invoked", []),
        tokens_used=result.get("tokens_used", 0),
        latency_ms=total_latency,
    )
    db.add(query_record)

    # Set session title from first question if not set
    if not session.title:
        session.title = payload.question[:60]

    await db.commit()

    logger.info(
        "Query complete",
        query_id=str(query_record.id),
        nodes=result.get("nodes_invoked"),
        latency_ms=total_latency,
    )

    # Step 4 — return response
    return QueryResponse(
        query_id=str(query_record.id),
        session_id=str(session.id),
        question=payload.question,
        answer=result.get("final_answer", ""),
        sources=result.get("sources") or [],
        nodes_invoked=result.get("nodes_invoked") or [],
        agent_trace=result.get("agent_trace") or [],
        latency_ms=total_latency,
        tokens_used=result.get("tokens_used", 0),
    )


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists all chat sessions for the current user."""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "title": s.title or "Untitled session",
            "created_at": s.created_at.isoformat(),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the full message history for a session."""
    # Verify session belongs to user
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == uuid.UUID(session_id),
            ChatSession.user_id == current_user.id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get all queries for this session
    queries_result = await db.execute(
        select(Query)
        .where(Query.session_id == uuid.UUID(session_id))
        .order_by(Query.created_at.asc())
    )
    queries = queries_result.scalars().all()

    return {
        "session_id": session_id,
        "title": session.title,
        "messages": [
            {
                "id": str(q.id),
                "question": q.question,
                "answer": q.answer,
                "nodes_invoked": q.nodes_invoked,
                "latency_ms": q.latency_ms,
                "created_at": q.created_at.isoformat(),
            }
            for q in queries
        ]
    }


async def get_or_create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: Optional[str],
    question: str,
) -> ChatSession:
    """
    Returns existing session or creates a new one.
    Session title is set from the first question automatically.
    """
    if session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == uuid.UUID(session_id),
                ChatSession.user_id == user_id,
            )
        )
        session = result.scalar_one_or_none()
        if session:
            return session

    # Create new session
    session = ChatSession(
        id=uuid.uuid4(),
        user_id=user_id,
        title=question[:60],
    )
    db.add(session)
    await db.flush()
    return session
