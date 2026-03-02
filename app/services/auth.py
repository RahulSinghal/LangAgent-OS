"""Auth service — Phase 3B.

Provides organisation and user management plus JWT token issuance.
"""

from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import Organization, User


# ── Slug helper ───────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convert an org name into a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


# ── Organization CRUD ─────────────────────────────────────────────────────────

def create_org(db: Session, name: str, plan: str = "free") -> Organization:
    """Create a new organization.  Slug is derived from *name*."""
    slug = _slugify(name)
    # Make slug unique by appending a counter if needed
    base_slug = slug
    counter = 1
    while db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    org = Organization(name=name, slug=slug, plan=plan, settings_jsonb={})
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def get_org(db: Session, org_id: int) -> Organization | None:
    """Return an org by primary key, or None."""
    return db.query(Organization).filter(Organization.id == org_id).first()


def list_orgs(db: Session) -> list[Organization]:
    """Return all organisations."""
    return db.query(Organization).order_by(Organization.id).all()


# ── User CRUD ─────────────────────────────────────────────────────────────────

def create_user(
    db: Session,
    org_id: int,
    email: str,
    password: str,
    role: str = "viewer",
) -> User:
    """Create a new user in the given org.  Password is bcrypt-hashed."""
    user = User(
        org_id=org_id,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Return the user if credentials are valid, else None."""
    user = get_user_by_email(db, email)
    if user is None:
        return None
    if not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    """Return the user with the given email address, or None."""
    return db.query(User).filter(User.email == email).first()


def login_for_access_token(db: Session, email: str, password: str) -> str:
    """Authenticate user and return a signed JWT access token.

    Raises HTTP 401 if credentials are invalid.
    """
    user = authenticate_user(db, email, password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return create_access_token(
        subject=user.email,
        org_id=user.org_id,
        role=user.role,
    )
