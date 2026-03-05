"""Tech-stack compatibility validation service.

Checks that the user-selected technology choices are appropriate for the
detected project type and returns a list of human-readable warning strings.
Warnings are surfaced as RiskItems in the SoT so reviewers see them at the
approval gate — they never block the workflow automatically.

Usage::

    from app.services.tech_stack_validation import validate_tech_stack

    warnings = validate_tech_stack(project_type, tech_stack)
    # Returns [] when everything is compatible.
"""

from __future__ import annotations

from app.sot.state import TechStackSpec

# ── Compatibility rules ────────────────────────────────────────────────────────
#
# Each rule is a dict with:
#   "check"   : callable(TechStackSpec) → bool  — True when the problem exists
#   "message" : str                             — human-readable warning text

_RULES: dict[str, list[dict]] = {
    "rag_pipeline": [
        {
            "check": lambda ts: ts.vector_store is None,
            "message": (
                "RAG Pipeline project has no vector_store selected. "
                "Choose one (e.g. pgvector, Pinecone, Chroma) before coding starts."
            ),
        },
        {
            "check": lambda ts: ts.embedding_model is None,
            "message": (
                "RAG Pipeline project has no embedding_model selected. "
                "Specify a model (e.g. text-embedding-3-small) for consistent retrieval."
            ),
        },
        {
            "check": lambda ts: ts.frontend_framework is not None
                and (ts.backend_framework or "").lower() not in ("fastapi", "flask", "django", "express", ""),
            "message": (
                "RAG Pipeline projects typically use a lightweight backend "
                "(FastAPI/Flask). Verify the selected backend_framework is appropriate."
            ),
        },
    ],
    "voice_chatbot": [
        {
            "check": lambda ts: ts.telephony is None,
            "message": (
                "Voice Chatbot project has no telephony provider selected. "
                "Choose one (e.g. Twilio, Vonage) before coding starts."
            ),
        },
        {
            "check": lambda ts: ts.tts_provider is None,
            "message": (
                "Voice Chatbot project has no TTS (text-to-speech) provider. "
                "Specify one (e.g. ElevenLabs, Azure TTS, Google TTS)."
            ),
        },
        {
            "check": lambda ts: (ts.frontend_framework or "").lower()
                in ("react", "vue", "angular", "next", "nuxt"),
            "message": (
                "Voice Chatbot projects typically do not need a heavy frontend framework. "
                "Consider whether a lightweight UI or telephony-only interface is sufficient."
            ),
        },
        {
            "check": lambda ts: (ts.database or "").lower()
                in ("sqlite",),
            "message": (
                "SQLite is not recommended for Voice Chatbot projects that handle "
                "concurrent call sessions. Use PostgreSQL or MySQL instead."
            ),
        },
    ],
    "crm": [
        {
            "check": lambda ts: ts.auth_method is None,
            "message": (
                "CRM project has no auth_method selected. "
                "CRMs require robust authentication (e.g. JWT, OAuth2, SAML)."
            ),
        },
        {
            "check": lambda ts: (ts.database or "").lower() in ("sqlite",),
            "message": (
                "SQLite is not suitable for CRM projects with multiple users and "
                "large datasets. Use PostgreSQL or MySQL."
            ),
        },
    ],
    "web_app": [
        {
            "check": lambda ts: (ts.database or "").lower() in ("sqlite",)
                and ts.frontend_framework is not None,
            "message": (
                "SQLite is not recommended for production web applications. "
                "Consider PostgreSQL or MySQL for multi-user workloads."
            ),
        },
        {
            "check": lambda ts: ts.auth_method is None
                and ts.frontend_framework is not None,
            "message": (
                "Web App project with a frontend has no auth_method selected. "
                "Most web apps require authentication (JWT, OAuth2, or session-based)."
            ),
        },
    ],
}

# Cross-type rules that apply to all project types
_UNIVERSAL_RULES: list[dict] = [
    {
        "check": lambda ts: (ts.language or "").lower() == "typescript"
            and (ts.backend_framework or "").lower() in ("fastapi", "django", "flask"),
        "message": (
            "Language is TypeScript but backend_framework is a Python framework "
            "(FastAPI/Django/Flask). Check that the language and framework are consistent."
        ),
    },
    {
        "check": lambda ts: (ts.language or "").lower() == "python"
            and (ts.backend_framework or "").lower() in ("express", "nest", "nestjs", "koa"),
        "message": (
            "Language is Python but backend_framework is a Node.js framework. "
            "Check that the language and framework are consistent."
        ),
    },
]


def validate_tech_stack(
    project_type: str,
    tech_stack: TechStackSpec | None,
) -> list[str]:
    """Check tech-stack choices for compatibility with the project type.

    Args:
        project_type: One of "rag_pipeline", "web_app", "crm", "voice_chatbot",
                      or "generic".
        tech_stack:   The TechStackSpec from the SoT (may be None if not yet set).

    Returns:
        A list of human-readable warning strings.  Empty means no issues found.
    """
    if tech_stack is None:
        return []

    warnings: list[str] = []

    # Project-type-specific rules
    for rule in _RULES.get(project_type, []):
        try:
            if rule["check"](tech_stack):
                warnings.append(rule["message"])
        except Exception:
            pass  # Never block on validation errors

    # Universal cross-type rules
    for rule in _UNIVERSAL_RULES:
        try:
            if rule["check"](tech_stack):
                warnings.append(rule["message"])
        except Exception:
            pass

    return warnings
