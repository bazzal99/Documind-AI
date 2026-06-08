import os
import uuid
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from backend.app.db.session import get_db
from backend.app.db.models import Document, DocumentStatus, User
from backend.app.api.deps import get_current_user
from backend.app.services.document_service import document_service
from backend.app.services.vector_service import vector_service
from backend.app.core.config import settings

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = structlog.get_logger()

# Allowed file types
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


def save_upload_file(upload_file: UploadFile, destination: str) -> int:
    """Saves uploaded file to disk. Returns file size in bytes."""
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return os.path.getsize(destination)


async def run_ingestion(
    file_path: str,
    filename: str,
    user_id: str,
    document_id: str,
):
    """
    Background task — runs after the API already responded to the user.
    Creates its own DB session since the request session is already closed.
    """
    from backend.app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await document_service.ingest_document(
            file_path=file_path,
            filename=filename,
            user_id=user_id,
            document_id=document_id,
            db=db,
        )


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Uploads a document and starts background indexing.

    Flow:
    1. Validate file type and size
    2. Save file to disk
    3. Create DB record with status=pending
    4. Return 202 immediately
    5. Embedding runs in background (pending → indexing → indexed)
    """
    # Validate file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not supported. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Validate file size
    file.file.seek(0, 2)  # seek to end
    file_size = file.file.tell()
    file.file.seek(0)     # reset to start
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024

    if file_size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB",
        )

    # Generate unique document ID and file path
    document_id = str(uuid.uuid4())
    safe_filename = f"{document_id}{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, str(current_user.id), safe_filename)

    # Save file to disk
    actual_size = save_upload_file(file, file_path)

    # Create DB record
    document = Document(
        id=uuid.UUID(document_id),
        user_id=current_user.id,
        filename=safe_filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size_bytes=actual_size,
        status=DocumentStatus.pending,
    )
    db.add(document)
    await db.commit()

    # Start background ingestion — user doesn't wait for this
    background_tasks.add_task(
        run_ingestion,
        file_path=file_path,
        filename=file.filename,
        user_id=str(current_user.id),
        document_id=document_id,
    )

    logger.info(
        "Document uploaded",
        document_id=document_id,
        filename=file.filename,
        user_id=str(current_user.id),
    )

    return {
        "document_id": document_id,
        "filename": file.filename,
        "status": "pending",
        "message": "Document uploaded. Indexing started in background.",
    }


@router.get("/")
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lists all documents for the current user with their indexing status.
    Poll this endpoint to check when a document is ready (status=indexed).
    """
    result = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    documents = result.scalars().all()

    return [
        {
            "id": str(doc.id),
            "filename": doc.original_filename,
            "status": doc.status.value,
            "chunk_count": doc.chunk_count,
            "file_size_bytes": doc.file_size_bytes,
            "created_at": doc.created_at.isoformat(),
            "error": doc.error_message,
        }
        for doc in documents
    ]


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Gets a single document by ID."""
    result = await db.execute(
        select(Document).where(
            Document.id == uuid.UUID(document_id),
            Document.user_id == current_user.id,
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": str(doc.id),
        "filename": doc.original_filename,
        "status": doc.status.value,
        "chunk_count": doc.chunk_count,
        "file_size_bytes": doc.file_size_bytes,
        "created_at": doc.created_at.isoformat(),
        "error": doc.error_message,
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deletes a document:
    1. Remove vectors from Qdrant
    2. Delete file from disk
    3. Delete record from PostgreSQL
    """
    result = await db.execute(
        select(Document).where(
            Document.id == uuid.UUID(document_id),
            Document.user_id == current_user.id,
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete vectors from Qdrant
    await vector_service.delete_document_chunks(document_id)

    # Delete file from disk
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    # Delete from PostgreSQL
    await db.delete(doc)
    await db.commit()

    logger.info("Document deleted", document_id=document_id)
