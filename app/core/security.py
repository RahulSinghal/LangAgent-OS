"""JWT security utilities — Phase 3B.

Provides:
  - password hashing / verification  (passlib / bcrypt)
  - JWT token creation / decoding    (python-jose)
  - FastAPI dependency: get_current_user
  - FastAPI dependency: require_role(*roles)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = structlog.get_logger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return bcrypt hash of *plain* password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    return _pwd_context.verify(plain, hashed)


# ── JWT token ─────────────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def create_access_token(
    subject: str,
    org_id: int,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT with user email + org/role claims."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,          # user email
        "org_id": org_id,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode JWT and return payload dict.  Raises HTTPException on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── Parsed token claims ───────────────────────────────────────────────────────

class TokenData:
    """Typed JWT claims carrier."""
    __slots__ = ("email", "org_id", "role")

    def __init__(self, email: str, org_id: int, role: str) -> None:
        self.email = email
        self.org_id = org_id
        self.role = role

    def __repr__(self) -> str:
        return f"<TokenData {self.email!r} org={self.org_id} role={self.role!r}>"


# ── FastAPI dependencies ──────────────────────────────────────────────────────

def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> TokenData:
    """FastAPI dependency — decode JWT and return TokenData.

    Raises HTTP 401 if the token is missing, expired, or malformed.
    """
    payload = decode_access_token(token)
    email: str | None = payload.get("sub")
    org_id: int | None = payload.get("org_id")
    role: str | None = payload.get("role")

    if not email or org_id is None or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload incomplete",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenData(email=email, org_id=org_id, role=role)


def require_role(*allowed_roles: str):
    """Return a FastAPI dependency that enforces one of *allowed_roles*.

    Usage::

        @router.post("/admin/thing")
        def admin_thing(
            user: Annotated[TokenData, Depends(require_role("admin", "pm"))],
        ):
            ...
    """
    def _dependency(
        user: Annotated[TokenData, Depends(get_current_user)],
    ) -> TokenData:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role {user.role!r} is not permitted for this endpoint. "
                    f"Required one of: {allowed_roles}"
                ),
            )
        return user

    return _dependency
