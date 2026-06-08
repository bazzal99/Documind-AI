import uuid
from datetime import datetime
from sqlalchemy import (
    String, Boolean, Integer, Text, DateTime,
    ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.db.session import Base
import enum


class DocumentStatus(str, enum.Enum):
    pending = "pending"       # just uploaded, not yet processed
    indexing = "indexing"     # currently being chunked and embedded
    indexed = "indexed"       # ready for search
    failed = "failed"         # something went wrong


class User(Base):
    """
    Stores user accounts.
    hashed_password: we never store plain passwords — always bcrypt hashed.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships — makes it easy to access user.documents, user.sessions
    documents: Mapped[list["Document"]] = relationship("Document", back_populates="user")
    sessions: Mapped[list["ChatSession"]] = relationship("ChatSession", back_populates="user")


class Document(Base):
    """
    Stores metadata about uploaded files.
    The actual file lives on disk (uploads/ folder).
    The text chunks live in Qdrant.
    This table just tracks the metadata.
    """
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), default=DocumentStatus.pending
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship("User", back_populates="documents")


class ChatSession(Base):
    """
    A conversation session — groups multiple queries together.
    A user can have many sessions, each scoped to specific documents.
    """
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    queries: Mapped[list["Query"]] = relationship("Query", back_populates="session")


class Query(Base):
    """
    Stores every question + answer pair.
    agent_trace: full JSON log of which agent nodes ran and what they returned.
    nodes_invoked: quick list of node names (e.g. ["supervisor", "retriever", "synthesizer"])
    This is what makes DocuMind look production-grade to recruiters.
    """
    __tablename__ = "queries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=True)
    agent_trace: Mapped[dict] = mapped_column(JSON, nullable=True)   # full execution log
    nodes_invoked: Mapped[list] = mapped_column(JSON, nullable=True) # e.g. ["retriever", "summarizer"]
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="queries")
