from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..access import owned_or_404, project_or_404
from ..database import get_db
from ..security import get_current_user
from ..services.events import publish

router = APIRouter(tags=["incidents"])
User = models.User


@router.get("/projects/{project_id}/incidents", response_model=list[schemas.IncidentOut])
def list_incidents(project_id: int, status: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    q = select(models.Incident).where(models.Incident.project_id == project_id)
    if status == "open":
        q = q.where(models.Incident.status != "resolved")
    elif status:
        q = q.where(models.Incident.status == status)
    return db.scalars(q.order_by(models.Incident.started_at.desc())).all()


@router.post("/projects/{project_id}/incidents", response_model=schemas.IncidentOut, status_code=201)
def create_incident(project_id: int, body: schemas.IncidentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    inc = models.Incident(project_id=project_id, auto_detected=False, **body.model_dump())
    db.add(inc)
    db.flush()
    db.add(models.IncidentEvent(incident_id=inc.id, service_id=inc.root_cause_service_id, event_type="detected",
                                message=f"Incident opened manually by {user.name}."))
    db.commit()
    publish(project_id, "incident_opened", {"incident_id": inc.id, "title": inc.title})
    return inc


@router.get("/incidents/{incident_id}", response_model=schemas.IncidentDetail)
def get_incident(incident_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    inc = owned_or_404(db, user, models.Incident, incident_id)
    events = db.scalars(
        select(models.IncidentEvent).where(models.IncidentEvent.incident_id == incident_id)
        .order_by(models.IncidentEvent.created_at, models.IncidentEvent.id)
    ).all()
    detail = schemas.IncidentDetail.model_validate(inc)
    detail.events = [schemas.IncidentEventOut.model_validate(e) for e in events]
    return detail


@router.patch("/incidents/{incident_id}", response_model=schemas.IncidentOut)
def update_incident(incident_id: int, body: schemas.IncidentUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    inc = owned_or_404(db, user, models.Incident, incident_id)
    changes = body.model_dump(exclude_unset=True)
    old_status = inc.status
    for field, value in changes.items():
        setattr(inc, field, value)
    if "status" in changes and changes["status"] != old_status:
        if changes["status"] == "resolved":
            inc.resolved_at = models.utcnow()
        else:
            inc.resolved_at = None
        db.add(models.IncidentEvent(incident_id=inc.id, event_type="resolved" if changes["status"] == "resolved" else "status_change",
                                    message=f"{user.name} changed status: {old_status} → {changes['status']}."))
    db.commit()
    publish(inc.project_id, "incident_updated", {"incident_id": inc.id})
    return inc


@router.post("/incidents/{incident_id}/events", response_model=schemas.IncidentEventOut, status_code=201)
def add_event(incident_id: int, body: schemas.IncidentEventCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    inc = owned_or_404(db, user, models.Incident, incident_id)
    ev = models.IncidentEvent(incident_id=inc.id, **body.model_dump())
    db.add(ev)
    db.commit()
    publish(inc.project_id, "incident_updated", {"incident_id": inc.id})
    return ev


# ------------------------------------------------------------------ alerts
@router.get("/projects/{project_id}/alerts", response_model=list[schemas.AlertOut])
def list_alerts(project_id: int, unacknowledged: bool = False, limit: int = 100, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    q = select(models.Alert).where(models.Alert.project_id == project_id)
    if unacknowledged:
        q = q.where(models.Alert.acknowledged.is_(False))
    return db.scalars(q.order_by(models.Alert.created_at.desc(), models.Alert.id.desc()).limit(min(limit, 500))).all()


@router.post("/alerts/{alert_id}/ack", response_model=schemas.AlertOut)
def ack_alert(alert_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    alert = owned_or_404(db, user, models.Alert, alert_id)
    alert.acknowledged = True
    db.commit()
    return alert


@router.post("/projects/{project_id}/alerts/ack-all")
def ack_all(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    rows = db.scalars(select(models.Alert).where(models.Alert.project_id == project_id, models.Alert.acknowledged.is_(False))).all()
    for a in rows:
        a.acknowledged = True
    db.commit()
    return {"acknowledged": len(rows)}
