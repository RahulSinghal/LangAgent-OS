"""Project service — Phase 1B.

All DB operations for projects. Routes call these functions.
"""

from sqlalchemy.orm import Session

from app.db.models import Project


def create_project(db: Session, name: str) -> Project:
    project = Project(name=name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: int) -> Project | None:
    return db.get(Project, project_id)


def list_projects(db: Session) -> list[Project]:
    return db.query(Project).order_by(Project.created_at.desc()).all()


def delete_project(db: Session, project_id: int) -> bool:
    project = db.get(Project, project_id)
    if not project:
        return False
    db.delete(project)
    db.commit()
    return True
