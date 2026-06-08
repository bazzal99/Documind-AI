from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
import structlog

from backend.app.core.config import settings
from backend.app.db.session import engine, Base

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup and shutdown.
    Startup: create DB tables, test Redis connection.
    Shutdown: close DB engine.
    """
    # --- STARTUP ---
    logger.info("Starting DocuMind AI...", version=settings.APP_VERSION)

    # Create all database tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    # Test Redis connection
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis connection failed", error=str(e))

    # Create uploads directory if it doesn't exist
    import os
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    logger.info("Upload directory ready", path=settings.UPLOAD_DIR)

    yield  # <-- server runs here

    # --- SHUTDOWN ---
    await engine.dispose()
    logger.info("DocuMind AI shut down cleanly")


# Create the FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Multi-agent document intelligence platform powered by Gemini + LangGraph",
    docs_url="/docs",        # Swagger UI at http://localhost:8000/docs
    redoc_url="/redoc",      # ReDoc UI at http://localhost:8000/redoc
    lifespan=lifespan,
)

# CORS — allows frontend (Streamlit on port 8501) to call our API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check endpoint ─────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Checks that all services are reachable.
    Returns status of PostgreSQL, Redis, and Qdrant.
    """
    from sqlalchemy import text
    from backend.app.db.session import AsyncSessionLocal
    from qdrant_client import QdrantClient

    status = {
        "app": "ok",
        "postgres": "unknown",
        "redis": "unknown",
        "qdrant": "unknown",
    }

    # Check PostgreSQL
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = f"error: {str(e)}"

    # Check Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {str(e)}"

    # Check Qdrant
    try:
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        client.get_collections()
        status["qdrant"] = "ok"
    except Exception as e:
        status["qdrant"] = f"error: {str(e)}"

    # Overall status
    all_ok = all(v == "ok" for k, v in status.items() if k != "app")
    status["overall"] = "healthy" if all_ok else "degraded"

    return status


# Routers
from backend.app.api.routes import auth, documents, query
app.include_router(auth.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")

@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Welcome to DocuMind AI",
        "docs": "/docs",
        "health": "/health",
        "version": settings.APP_VERSION,
    }
