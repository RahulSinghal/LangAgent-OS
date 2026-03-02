"""System status endpoints (UI support)."""

from fastapi import APIRouter

from app.core.runtime import get_runtime_status, refresh_runtime_status

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def status() -> dict:
    s = get_runtime_status()
    return {
        "agent_mode": s.agent_mode,
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "llm_key_present": s.llm_key_present,
        "llm_key_validity": s.llm_key_validity,
        "reason": s.reason,
    }


@router.post("/recheck")
def recheck() -> dict:
    """Re-run LLM validation and update effective mode."""
    s = refresh_runtime_status(validate_llm=True)
    return {
        "agent_mode": s.agent_mode,
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "llm_key_present": s.llm_key_present,
        "llm_key_validity": s.llm_key_validity,
        "reason": s.reason,
    }

