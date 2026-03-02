"""Artifact service — Phase 1F.

Reads artifact records and serves file content.
"""

from __future__ import annotations

from pathlib import Path
import re

from sqlalchemy.orm import Session

from app.db.models import Artifact
from app.core.config import settings


def list_artifacts(db: Session, project_id: int) -> list[Artifact]:
    """List all artifacts for a project, ordered by creation date."""
    return (
        db.query(Artifact)
        .filter(Artifact.project_id == project_id)
        .order_by(Artifact.created_at.desc())
        .all()
    )


def get_artifact(db: Session, artifact_id: int) -> Artifact | None:
    return db.get(Artifact, artifact_id)


def read_artifact_content(db: Session, artifact_id: int) -> str:
    """Read and return the rendered Markdown content of an artifact.

    Args:
        db:          Active DB session.
        artifact_id: Artifact to read.

    Returns:
        File content as a string.

    Raises:
        ValueError: Artifact not found or file missing from disk.
    """
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise ValueError(f"Artifact {artifact_id} not found")
    if not artifact.file_path:
        raise ValueError(f"Artifact {artifact_id} has no file_path")

    path = Path(artifact.file_path)
    if not path.exists():
        raise ValueError(f"Artifact file not found on disk: {path}")

    return path.read_text(encoding="utf-8")


def _safe_name(name: str) -> str:
    name = name.strip() or "document"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return name[:80]


def create_text_artifact(
    db: Session,
    project_id: int,
    artifact_type: str,
    content: str,
    source_filename: str | None = None,
) -> Artifact:
    """Create a text artifact stored on disk and recorded in DB.

    Used for persisted uploads (e.g., extracted document text).
    """
    existing_count = (
        db.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.type == artifact_type)
        .count()
    )
    version = existing_count + 1

    out_dir = Path(settings.ARTIFACTS_DIR) / str(project_id) / artifact_type
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = _safe_name(source_filename or "")
    file_name = f"v{version}.txt" if not suffix else f"v{version}_{suffix}.txt"
    file_path = out_dir / file_name
    file_path.write_text(content or "", encoding="utf-8")

    artifact = Artifact(
        project_id=project_id,
        type=artifact_type,
        version=version,
        file_path=str(file_path),
        derived_from_snapshot_id=None,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact
