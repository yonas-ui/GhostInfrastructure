from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..access import owned_or_404, project_or_404
from ..database import get_db
from ..security import get_current_user
from ..services import health as H
from ..services.events import publish

router = APIRouter(tags=["services"])
User = models.User


# ---------------------------------------------------------------- services
@router.get("/projects/{project_id}/services", response_model=list[schemas.ServiceOut])
def list_services(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    return db.scalars(select(models.Service).where(models.Service.project_id == project_id).order_by(models.Service.name)).all()


@router.post("/projects/{project_id}/services", response_model=schemas.ServiceOut, status_code=201)
def create_service(project_id: int, body: schemas.ServiceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    svc = models.Service(project_id=project_id, **body.model_dump())
    db.add(svc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"A service named '{body.name}' already exists in this project")
    publish(project_id, "graph_changed", {"reason": "service_created", "service_id": svc.id})
    return svc


@router.get("/services/{service_id}")
def get_service(service_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc = owned_or_404(db, user, models.Service, service_id)
    names = {s.id: s.name for s in db.scalars(select(models.Service).where(models.Service.project_id == svc.project_id))}
    deps_out = db.scalars(select(models.Dependency).where(models.Dependency.source_id == service_id)).all()
    deps_in = db.scalars(select(models.Dependency).where(models.Dependency.target_id == service_id)).all()
    history = db.scalars(
        select(models.HealthCheck).where(models.HealthCheck.service_id == service_id)
        .order_by(models.HealthCheck.checked_at.desc()).limit(60)
    ).all()
    deploys = db.scalars(
        select(models.Deployment).where(models.Deployment.service_id == service_id)
        .order_by(models.Deployment.deployed_at.desc()).limit(10)
    ).all()
    return {
        "service": schemas.ServiceOut.model_validate(svc),
        "depends_on": [
            {**schemas.DependencyOut.model_validate(d).model_dump(), "service_id": d.target_id, "service_name": names.get(d.target_id)}
            for d in deps_out
        ],
        "depended_on_by": [
            {**schemas.DependencyOut.model_validate(d).model_dump(), "service_id": d.source_id, "service_name": names.get(d.source_id)}
            for d in deps_in
        ],
        "health": [schemas.HealthCheckOut.model_validate(h) for h in reversed(history)],
        "deployments": [schemas.DeploymentOut.model_validate(d) for d in deploys],
    }


@router.patch("/services/{service_id}", response_model=schemas.ServiceOut)
def update_service(service_id: int, body: schemas.ServiceUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc = owned_or_404(db, user, models.Service, service_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(svc, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Name already in use")
    publish(svc.project_id, "graph_changed", {"reason": "service_updated", "service_id": svc.id})
    return svc


@router.delete("/services/{service_id}", status_code=204)
def delete_service(service_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc = owned_or_404(db, user, models.Service, service_id)
    project_id = svc.project_id
    db.delete(svc)
    db.commit()
    H.reconcile_incidents(db, project_id)
    db.commit()
    publish(project_id, "graph_changed", {"reason": "service_deleted"})


# ------------------------------------------------------------------ health
@router.post("/services/{service_id}/health", response_model=schemas.HealthCheckOut, status_code=201)
def report_health(service_id: int, body: schemas.HealthReport, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Push-based health report (also used by the UI to simulate an outage)."""
    svc = owned_or_404(db, user, models.Service, service_id)
    return H.record_health(db, svc, body.status, body.latency_ms, body.status_code, body.error, source="push")


@router.post("/services/{service_id}/check", response_model=schemas.HealthCheckOut)
def check_now(service_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc = owned_or_404(db, user, models.Service, service_id)
    if not svc.health_url:
        raise HTTPException(400, "This service has no health_url to probe")
    return H.record_health(db, svc, **H.probe(svc.health_url))


@router.get("/services/{service_id}/health", response_model=list[schemas.HealthCheckOut])
def health_history(service_id: int, limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_or_404(db, user, models.Service, service_id)
    rows = db.scalars(
        select(models.HealthCheck).where(models.HealthCheck.service_id == service_id)
        .order_by(models.HealthCheck.checked_at.desc()).limit(min(limit, 1000))
    ).all()
    return list(reversed(rows))


# ------------------------------------------------------------ dependencies
@router.get("/projects/{project_id}/dependencies", response_model=list[schemas.DependencyOut])
def list_dependencies(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    return db.scalars(select(models.Dependency).where(models.Dependency.project_id == project_id)).all()


@router.post("/projects/{project_id}/dependencies", response_model=schemas.DependencyOut, status_code=201)
def create_dependency(project_id: int, body: schemas.DependencyCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    if body.source_id == body.target_id:
        raise HTTPException(400, "A service cannot depend on itself")
    for sid in (body.source_id, body.target_id):
        svc = db.get(models.Service, sid)
        if svc is None or svc.project_id != project_id:
            raise HTTPException(400, f"Service {sid} is not part of this project")
    dep = models.Dependency(project_id=project_id, **body.model_dump(), discovered_by="manual")
    db.add(dep)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That dependency already exists")
    publish(project_id, "graph_changed", {"reason": "dependency_created"})
    return dep


@router.patch("/dependencies/{dep_id}", response_model=schemas.DependencyOut)
def update_dependency(dep_id: int, body: schemas.DependencyUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    dep = owned_or_404(db, user, models.Dependency, dep_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(dep, field, value)
    db.commit()
    publish(dep.project_id, "graph_changed", {"reason": "dependency_updated"})
    return dep


@router.delete("/dependencies/{dep_id}", status_code=204)
def delete_dependency(dep_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    dep = owned_or_404(db, user, models.Dependency, dep_id)
    project_id = dep.project_id
    db.delete(dep)
    db.commit()
    H.reconcile_incidents(db, project_id)
    db.commit()
    publish(project_id, "graph_changed", {"reason": "dependency_deleted"})


# ------------------------------------------------------------- deployments
@router.get("/projects/{project_id}/deployments", response_model=list[schemas.DeploymentOut])
def list_deployments(project_id: int, limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    return db.scalars(
        select(models.Deployment).where(models.Deployment.project_id == project_id)
        .order_by(models.Deployment.deployed_at.desc()).limit(min(limit, 500))
    ).all()


@router.post("/services/{service_id}/deployments", response_model=schemas.DeploymentOut, status_code=201)
def record_deployment(service_id: int, body: schemas.DeploymentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    svc = owned_or_404(db, user, models.Service, service_id)
    data = body.model_dump()
    when = data.pop("deployed_at") or models.utcnow()
    dep = models.Deployment(project_id=svc.project_id, service_id=svc.id, deployed_at=when, **data)
    db.add(dep)
    db.commit()
    publish(svc.project_id, "deployment", {"service_id": svc.id, "version": dep.version})
    return dep
