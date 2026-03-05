"""Artifact generator — Phase 1F.

Renders PRD.md and SOW.md from the SoT using Jinja2 templates.
Stores output at:  ./storage/artifacts/{project_id}/{type}/v{n}.md
Creates an Artifact DB record and updates the SoT artifacts_index.

Public API:
  render_artifact(artifact_type, state, db, run_id) -> tuple[Artifact, ProjectState]
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Artifact
from app.sot.patch import apply_patch
from app.sot.state import ArtifactRef, ProjectState


# ── Jinja2 environment ────────────────────────────────────────────────────────

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=("md.j2", "j2")),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ── Context builders ──────────────────────────────────────────────────────────

def _build_prd_context(sot: ProjectState, project_name: str, version: int) -> dict:
    return {
        "project_name": project_name,
        "version": version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scope": {
            "summary": f"Delivery of '{project_name}' as defined by the approved requirements.",
        },
        "objectives": [r.text for r in sot.requirements if r.category == "functional"][:5]
                      or ["To be defined."],
        "requirements": [
            {
                "requirement_id": i + 1,
                "text": r.text,
                "priority": r.priority.value.capitalize(),
                "acceptance_criteria": [f"System satisfies: {r.text}"],
            }
            for i, r in enumerate(sot.requirements)
        ],
        "assumptions": [{"text": a.text} for a in sot.assumptions],
        "risks": [
            {
                "title": f"Risk {i + 1}",
                "probability": r.likelihood,
                "impact": r.impact,
                "description": r.description,
            }
            for i, r in enumerate(sot.risks)
        ],
        "open_questions": [
            {"question": q.question, "owner": "TBD"}
            for q in sot.open_questions
            if not q.answered
        ],
    }


def _build_sow_context(sot: ProjectState, project_name: str, version: int) -> dict:
    in_scope = [r.text for r in sot.requirements if r.accepted] or ["To be defined."]
    return {
        "project_name": project_name,
        "version": version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scope": {
            "summary": f"Consulting delivery of '{project_name}'.",
            "in_scope": in_scope,
            "out_of_scope": ["Items not listed in In Scope above."],
        },
        "milestones": [
            {
                "name": "Discovery & PRD",
                "phase": "Phase 1",
                "estimated_weeks": 2,
                "payment_percentage": 20,
                "acceptance_criteria": "Signed PRD",
            },
            {
                "name": "Development & Integration",
                "phase": "Phase 2",
                "estimated_weeks": 8,
                "payment_percentage": 60,
                "acceptance_criteria": "Working system in UAT",
            },
            {
                "name": "UAT & Go-live",
                "phase": "Phase 3",
                "estimated_weeks": 2,
                "payment_percentage": 20,
                "acceptance_criteria": "Client sign-off",
            },
        ],
        "commercial_model": {
            "type": "Fixed Price",
            "total_estimated_effort_weeks": 12,
        },
        "payment_terms": {
            "schedule": "20% on PRD approval, 60% on delivery, 20% on go-live",
        },
        "assumptions": [{"text": a.text} for a in sot.assumptions],
        "risks": [
            {
                "title": f"Risk {i + 1}",
                "description": r.description,
                "mitigation": r.mitigation or "TBD",
            }
            for i, r in enumerate(sot.risks)
        ],
    }


def _build_server_details_context(
    sot: ProjectState,
    project_name: str,
    version: int,
    audience: str,
) -> dict:
    return {
        "project_name": project_name,
        "version": version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "audience": audience,
        "hosting_preference": sot.hosting_preference,
    }


def _build_user_guide_context(sot: ProjectState, project_name: str, version: int) -> dict:
    return {
        "content": sot.user_guide_content or "# User Guide\n\n> Guide content not yet generated.",
    }


_CONTEXT_BUILDERS = {
    "prd": _build_prd_context,
    "sow": _build_sow_context,
    # Server-details variants share one template, different audience label
    "server_details_client": lambda sot, project_name, version: _build_server_details_context(
        sot, project_name, version, audience="Client"
    ),
    "server_details_infra": lambda sot, project_name, version: _build_server_details_context(
        sot, project_name, version, audience="Infra Team"
    ),
    "user_guide": _build_user_guide_context,
}

_TEMPLATE_FILES = {
    "prd": "prd.md.j2",
    "sow": "sow.md.j2",
    "change_request": "change_request.md.j2",
    "server_details_client": "server_details.md.j2",
    "server_details_infra": "server_details.md.j2",
    "user_guide": "user_guide.md.j2",
}


# ── Main API ──────────────────────────────────────────────────────────────────

def render_artifact(
    artifact_type: str,
    state: ProjectState,
    db: Session,
    run_id: int | None = None,
) -> tuple[Artifact, ProjectState]:
    """Render a Jinja2 template → disk → DB record → updated SoT.

    Args:
        artifact_type: "prd" | "sow" | "change_request"
        state:         Current ProjectState.
        db:            Active DB session.
        run_id:        Optional run that triggered this generation.

    Returns:
        (Artifact ORM record, updated ProjectState with artifacts_index entry).

    Raises:
        ValueError: Unknown artifact_type or missing context builder.
    """
    if artifact_type not in _TEMPLATE_FILES:
        raise ValueError(f"Unknown artifact_type: {artifact_type!r}")

    # ── Project name ──────────────────────────────────────────────────────────
    from app.db.models import Project
    project = db.get(Project, state.project_id)
    project_name = project.name if project else f"Project {state.project_id}"

    # ── Version ───────────────────────────────────────────────────────────────
    existing_count = (
        db.query(Artifact)
        .filter(
            Artifact.project_id == state.project_id,
            Artifact.type == artifact_type,
        )
        .count()
    )
    version = existing_count + 1

    # ── Render ────────────────────────────────────────────────────────────────
    builder = _CONTEXT_BUILDERS.get(artifact_type)
    if builder is None:
        raise ValueError(f"No context builder for artifact_type: {artifact_type!r}")

    context = builder(state, project_name, version)
    template = _jinja_env.get_template(_TEMPLATE_FILES[artifact_type])
    rendered = template.render(**context)

    # ── Write to disk ─────────────────────────────────────────────────────────
    out_dir = Path(settings.ARTIFACTS_DIR) / str(state.project_id) / artifact_type
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"v{version}.md"
    file_path.write_text(rendered, encoding="utf-8")

    # ── DB record ─────────────────────────────────────────────────────────────
    artifact = Artifact(
        project_id=state.project_id,
        type=artifact_type,
        version=version,
        file_path=str(file_path),
        derived_from_snapshot_id=None,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)

    # ── Update SoT artifacts_index ────────────────────────────────────────────
    index = {k: v.model_dump() for k, v in state.artifacts_index.items()}
    index[artifact_type] = ArtifactRef(version=version, artifact_id=artifact.id).model_dump()
    updated_state = apply_patch(state, {"artifacts_index": index})

    # ── Trim old versions beyond the retention cap ─────────────────────────────
    try:
        from app.services.artifacts import cleanup_old_artifact_versions
        cleanup_old_artifact_versions(db, project_id=state.project_id, artifact_type=artifact_type)
    except Exception:
        pass  # Never block artifact rendering on cleanup failure

    return artifact, updated_state
