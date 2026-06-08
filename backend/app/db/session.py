from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from backend.app.core.config import settings

# The engine is the actual connection to PostgreSQL
# pool_pre_ping=True means it checks the connection is alive before using it
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,       # logs all SQL queries in debug mode
    pool_pre_ping=True,
    pool_size=10,              # max 10 simultaneous DB connections
    max_overflow=20,           # allow 20 extra connections under heavy load
)

# Session factory — creates a new session for each request
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,    # keep objects usable after commit
)

# Base class that all our DB models will inherit from
class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """
    Dependency function injected into FastAPI routes.
    Yields a DB session and closes it automatically when the request ends.
    Usage in a route: db: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
