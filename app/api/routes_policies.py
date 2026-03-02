"""Policy engine routes — Phase 3C."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.policies import (
    create_policy,
    delete_policy,
    evaluate_policy,
    get_policy,
    list_policies,
    update_policy,
)

router = APIRouter(tags=["policies"])

DbDep = Annotated[Session, Depends(get_db)]


# ── Request / response schemas ────────────────────────────────────────────────

class CreatePolicyRequest(BaseModel):
    name: str
    policy_type: str
    rules: dict
    is_active: bool = True


class UpdatePolicyRequest(BaseModel):
    rules: dict | None = None
    is_active: bool | None = None


class PolicyResponse(BaseModel):
    id: int
    org_id: int
    name: str
    policy_type: str
    rules_jsonb: dict
    is_active: bool

    model_config = {"from_attributes": True}


class EvaluateRequest(BaseModel):
    context: dict


class EvaluateResponse(BaseModel):
    allowed: bool
    violations: list[str]
    applied_policies: list[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/orgs/{org_id}/policies",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_policy_route(org_id: int, body: CreatePolicyRequest, db: DbDep) -> PolicyResponse:
    """Create a governance policy for an organisation."""
    policy = create_policy(
        db,
        org_id=org_id,
        name=body.name,
        policy_type=body.policy_type,
        rules=body.rules,
        is_active=body.is_active,
    )
    return PolicyResponse.model_validate(policy)


@router.get("/orgs/{org_id}/policies", response_model=list[PolicyResponse])
def list_policies_route(
    org_id: int,
    db: DbDep,
    active_only: bool = False,
) -> list[PolicyResponse]:
    """List policies for an organisation."""
    policies = list_policies(db, org_id=org_id, active_only=active_only)
    return [PolicyResponse.model_validate(p) for p in policies]


@router.get("/policies/{policy_id}", response_model=PolicyResponse)
def get_policy_route(policy_id: int, db: DbDep) -> PolicyResponse:
    """Get a single policy by ID."""
    policy = get_policy(db, policy_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found",
        )
    return PolicyResponse.model_validate(policy)


@router.put("/policies/{policy_id}", response_model=PolicyResponse)
def update_policy_route(policy_id: int, body: UpdatePolicyRequest, db: DbDep) -> PolicyResponse:
    """Update a policy's rules or active status."""
    policy = update_policy(db, policy_id=policy_id, rules=body.rules, is_active=body.is_active)
    return PolicyResponse.model_validate(policy)


@router.delete("/policies/{policy_id}")
def delete_policy_route(policy_id: int, db: DbDep):
    """Delete a policy."""
    from fastapi import Response
    deleted = delete_policy(db, policy_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/orgs/{org_id}/policies/evaluate", response_model=EvaluateResponse)
def evaluate_policies_route(org_id: int, body: EvaluateRequest, db: DbDep) -> EvaluateResponse:
    """Evaluate all active org policies against a context dict."""
    result = evaluate_policy(db, org_id=org_id, context=body.context)
    return EvaluateResponse(**result)
