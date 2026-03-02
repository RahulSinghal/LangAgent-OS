"""Auth and org management routes — Phase 3B."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.auth import (
    create_org,
    create_user,
    get_org,
    list_orgs,
    login_for_access_token,
)

router = APIRouter(tags=["auth", "orgs"])

DbDep = Annotated[Session, Depends(get_db)]


# ── Request / response schemas ────────────────────────────────────────────────

class RegisterOrgRequest(BaseModel):
    name: str
    plan: str = "free"


class OrgResponse(BaseModel):
    id: int
    name: str
    slug: str
    plan: str

    model_config = {"from_attributes": True}


class RegisterUserRequest(BaseModel):
    org_id: int
    email: str
    password: str
    role: str = "viewer"


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    org_id: int

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/auth/register-org", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
def register_org(body: RegisterOrgRequest, db: DbDep) -> OrgResponse:
    """Create a new organisation and return its details."""
    org = create_org(db, name=body.name, plan=body.plan)
    return OrgResponse.model_validate(org)


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(body: RegisterUserRequest, db: DbDep) -> UserResponse:
    """Register a new user within an organisation."""
    # Verify org exists
    org = get_org(db, body.org_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {body.org_id} not found",
        )
    user = create_user(
        db,
        org_id=body.org_id,
        email=body.email,
        password=body.password,
        role=body.role,
    )
    return UserResponse.model_validate(user)


@router.post("/auth/token", response_model=TokenResponse)
def get_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbDep,
) -> TokenResponse:
    """Issue a JWT access token via OAuth2 password flow."""
    token = login_for_access_token(db, email=form_data.username, password=form_data.password)
    return TokenResponse(access_token=token, token_type="bearer")


@router.get("/orgs", response_model=list[OrgResponse])
def get_orgs(db: DbDep) -> list[OrgResponse]:
    """List all organisations."""
    orgs = list_orgs(db)
    return [OrgResponse.model_validate(o) for o in orgs]


@router.get("/orgs/{org_id}", response_model=OrgResponse)
def get_org_by_id(org_id: int, db: DbDep) -> OrgResponse:
    """Get a single organisation by ID."""
    org = get_org(db, org_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {org_id} not found",
        )
    return OrgResponse.model_validate(org)
