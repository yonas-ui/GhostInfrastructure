"""Ownership checks: a user can only touch objects that belong to their projects."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models


def project_or_404(db: Session, user: models.User, project_id: int) -> models.Project:
    project = db.get(models.Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(404, "Project not found")
    return project


def owned_or_404(db: Session, user: models.User, model, obj_id: int):
    """Fetch an object that has a project_id column and make sure the user owns that project."""
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    project = db.get(models.Project, obj.project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj
