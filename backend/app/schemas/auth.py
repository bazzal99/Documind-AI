from pydantic import BaseModel, EmailStr, field_validator
import re


class UserRegister(BaseModel):
    """
    Data required to create a new account.
    EmailStr automatically validates email format.
    """
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """
        Enforces basic password rules.
        Runs automatically before the data reaches our route handler.
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        return v


class UserLogin(BaseModel):
    """
    Data required to log in.
    """
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """
    What we return after successful register or login.
    access_token: short-lived (15 min), used for all API calls
    refresh_token: long-lived (7 days), used only to get a new access token
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """
    Data required to refresh an expired access token.
    """
    refresh_token: str


class UserResponse(BaseModel):
    """
    What we return when someone asks for their profile.
    Never includes the password — not even the hash.
    """
    id: str
    email: str
    is_active: bool

    class Config:
        from_attributes = True   # allows creating this from a SQLAlchemy model
