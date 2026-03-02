"""Artifact comment CRUD service — Phase 3F."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ArtifactComment


def add_comment(
    db: Session,
    artifact_id: int,
    project_id: int,
    author: str,
    body: str,
    section: str | None = None,
) -> ArtifactComment:
    """Add a review comment to an artifact."""
    comment = ArtifactComment(
        artifact_id=artifact_id,
        project_id=project_id,
        author=author,
        body=body,
        section=section,
        resolved=False,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def list_comments(
    db: Session,
    artifact_id: int,
    include_resolved: bool = True,
) -> list[ArtifactComment]:
    """List comments for an artifact.  Pass include_resolved=False to hide resolved ones."""
    q = db.query(ArtifactComment).filter(ArtifactComment.artifact_id == artifact_id)
    if not include_resolved:
        q = q.filter(ArtifactComment.resolved == False)  # noqa: E712
    return q.order_by(ArtifactComment.created_at).all()


def resolve_comment(db: Session, comment_id: int) -> ArtifactComment:
    """Mark a comment as resolved.

    Raises HTTPException 404 if the comment does not exist.
    """
    comment = db.query(ArtifactComment).filter(ArtifactComment.id == comment_id).first()
    if comment is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Comment {comment_id} not found",
        )
    comment.resolved = True
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(db: Session, comment_id: int) -> bool:
    """Delete a comment.  Returns True if deleted, False if not found."""
    comment = db.query(ArtifactComment).filter(ArtifactComment.id == comment_id).first()
    if comment is None:
        return False
    db.delete(comment)
    db.commit()
    return True
