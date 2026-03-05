"""Artifact service — Phase 1F.

Reads artifact records and serves file content.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re

from sqlalchemy.orm import Session

from app.db.models import Artifact
from app.core.config import settings

_log = logging.getLogger(__name__)


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


def cleanup_old_artifact_versions(
    db: Session,
    project_id: int,
    artifact_type: str,
    keep: int | None = None,
) -> int:
    """Delete artifact files and DB records beyond the version retention cap.

    Keeps the *keep* most recent versions (by DB id) and permanently deletes
    older ones from both disk and the database.

    Args:
        db:            Active DB session.
        project_id:    Project whose artifacts to clean.
        artifact_type: Artifact type (e.g. "prd", "sow", "input_document").
        keep:          Number of versions to retain.  Defaults to
                       settings.ARTIFACT_MAX_VERSIONS.  Pass 0 to delete all.

    Returns:
        Number of artifact records deleted.
    """
    if keep is None:
        keep = settings.ARTIFACT_MAX_VERSIONS
    if keep <= 0:
        return 0  # Cleanup disabled

    all_versions = (
        db.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.type == artifact_type)
        .order_by(Artifact.id.desc())  # newest first
        .all()
    )

    to_delete = all_versions[keep:]  # everything beyond the keep window
    if not to_delete:
        return 0

    deleted = 0
    for artifact in to_delete:
        # Delete the file from disk first (best-effort)
        if artifact.file_path:
            try:
                p = Path(artifact.file_path)
                if p.exists():
                    p.unlink()
            except Exception as exc:
                _log.warning(
                    "artifact.cleanup.file_delete_failed path=%s err=%s",
                    artifact.file_path,
                    exc,
                )
        db.delete(artifact)
        deleted += 1

    db.commit()
    _log.info(
        "artifact.cleanup project_id=%d type=%s deleted=%d kept=%d",
        project_id,
        artifact_type,
        deleted,
        len(all_versions) - deleted,
    )
    return deleted


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
    After creating the new artifact, old versions beyond ARTIFACT_MAX_VERSIONS
    are automatically deleted to prevent unbounded disk growth.
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

    # Trim old versions beyond the retention cap (best-effort)
    try:
        cleanup_old_artifact_versions(db, project_id=project_id, artifact_type=artifact_type)
    except Exception as exc:
        _log.warning("artifact.cleanup.failed project_id=%d type=%s err=%s", project_id, artifact_type, exc)

    return artifact
