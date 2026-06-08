from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from backend.app.db.session import get_db
from backend.app.db.models import User
from backend.app.core.security import decode_token
from backend.app.services.cache_service import cache_service
from backend.app.core.config import settings

# Extracts the Bearer token from the Authorization header automatically
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency injected into every protected route.
    Validates the JWT token and returns the logged-in User object.

    Usage in a route:
        @router.get("/me")
        async def get_me(current_user: User = Depends(get_current_user)):
            return current_user
    """
    token = credentials.credentials

    # Reusable 401 error
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Step 1 — check if token was blacklisted (user logged out)
    if await cache_service.is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again.",
        )

    # Step 2 — decode and validate JWT signature + expiry
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    # Step 3 — make sure it's an access token, not a refresh token
    if payload.get("type") != "access":
        raise credentials_exception

    # Step 4 — extract user ID from token payload
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    # Step 5 — load user from database
    try:
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()
    except Exception:
        raise credentials_exception

    if user is None:
        raise credentials_exception

    # Step 6 — make sure account is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    return user


async def get_current_user_with_rate_limit(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Same as get_current_user but also enforces rate limiting.
    Use this on expensive endpoints like /query.
    """
    is_allowed, remaining = await cache_service.check_rate_limit(
        str(current_user.id),
        limit=settings.RATE_LIMIT_PER_MINUTE,
    )

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Max {settings.RATE_LIMIT_PER_MINUTE} requests per minute.",
            headers={"X-RateLimit-Remaining": "0"},
        )

    return current_user
