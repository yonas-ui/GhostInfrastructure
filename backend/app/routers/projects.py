from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..access import project_or_404
from ..database import get_db
from ..security import get_current_user
from ..services import graph as G

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.scalars(
        select(models.Project).where(models.Project.owner_id == user.id).order_by(models.Project.id)
    ).all()


@router.post("", response_model=schemas.ProjectOut, status_code=201)
def create_project(body: schemas.ProjectCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    project = models.Project(name=body.name, description=body.description, owner_id=user.id)
    db.add(project)
    db.commit()
    return project


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return project_or_404(db, user, project_id)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.delete(project_or_404(db, user, project_id))
    db.commit()


@router.get("/{project_id}/summary")
def summary(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    g = G.build_graph(db, project_id)
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for _, d in g.nodes(data=True):
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    last_deploy = dict(
        db.execute(
            select(models.Deployment.service_id, func.max(models.Deployment.deployed_at))
            .where(models.Deployment.project_id == project_id)
            .group_by(models.Deployment.service_id)
        ).all()
    )
    ghosts = G.detect_ghosts(g, last_deploy)
    ghost_counts: dict[str, int] = {}
    for f in ghosts:
        ghost_counts[f["severity"]] = ghost_counts.get(f["severity"], 0) + 1
    open_incidents = db.scalar(
        select(func.count()).select_from(models.Incident).where(
            models.Incident.project_id == project_id, models.Incident.status != "resolved"
        )
    )
    unacked = db.scalar(
        select(func.count()).select_from(models.Alert).where(
            models.Alert.project_id == project_id, models.Alert.acknowledged.is_(False)
        )
    )
    return {
        "services": g.number_of_nodes(),
        "dependencies": g.number_of_edges(),
        "undocumented_dependencies": sum(1 for *_, d in g.edges(data=True) if not d["documented"]),
        "by_type": by_type,
        "by_status": by_status,
        "ghost_findings": len(ghosts),
        "ghost_by_severity": ghost_counts,
        "open_incidents": open_incidents,
        "unacknowledged_alerts": unacked,
    }
