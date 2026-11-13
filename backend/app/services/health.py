"""Health probing, status transitions, alerts and automatic incident management."""
from __future__ import annotations

import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from . import graph as G
from .events import publish


# ----------------------------------------------------------------- probe
def probe(health_url: str, timeout: float | None = None) -> dict:
    """Probe an http(s):// or tcp://host:port endpoint. Returns kwargs for record_health()."""
    timeout = timeout or settings.health_timeout
    started = time.perf_counter()
    try:
        parsed = urlparse(health_url)
        if parsed.scheme == "tcp":
            with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout):
                pass
            latency = (time.perf_counter() - started) * 1000
            status = "degraded" if latency > settings.slow_ms else "healthy"
            return {"status": status, "latency_ms": round(latency, 1), "status_code": None, "error": None, "source": "probe"}
        resp = httpx.get(health_url, timeout=timeout, follow_redirects=True)
        latency = (time.perf_counter() - started) * 1000
        if resp.status_code >= 500:
            status, err = "down", f"HTTP {resp.status_code}"
        elif resp.status_code >= 400 or latency > settings.slow_ms:
            status, err = "degraded", (f"HTTP {resp.status_code}" if resp.status_code >= 400 else "slow response")
        else:
            status, err = "healthy", None
        return {"status": status, "latency_ms": round(latency, 1), "status_code": resp.status_code, "error": err, "source": "probe"}
    except Exception as exc:
        return {"status": "down", "latency_ms": None, "status_code": None, "error": f"{type(exc).__name__}: {exc}"[:300], "source": "probe"}


# ----------------------------------------------------------------- alerts
def create_alert(
    db: Session,
    project_id: int,
    level: str,
    message: str,
    *,
    kind: str = "status",
    service_id: int | None = None,
    incident_id: int | None = None,
    dedupe_key: str | None = None,
) -> models.Alert | None:
    if dedupe_key:
        existing = db.scalar(
            select(models.Alert).where(
                models.Alert.project_id == project_id,
                models.Alert.dedupe_key == dedupe_key,
                models.Alert.acknowledged.is_(False),
            )
        )
        if existing:
            return None
    alert = models.Alert(
        project_id=project_id,
        service_id=service_id,
        incident_id=incident_id,
        kind=kind,
        level=level,
        message=message,
        dedupe_key=dedupe_key,
    )
    db.add(alert)
    db.flush()
    return alert


# ---------------------------------------------------------- recording
def record_health(
    db: Session,
    service: models.Service,
    status: str,
    latency_ms: float | None = None,
    status_code: int | None = None,
    error: str | None = None,
    source: str = "probe",
) -> models.HealthCheck:
    previous = service.status
    check = models.HealthCheck(
        service_id=service.id,
        status=status,
        latency_ms=latency_ms,
        status_code=status_code,
        error=error,
        source=source,
    )
    db.add(check)
    service.status = status
    service.last_checked_at = models.utcnow()
    db.flush()

    changed = previous != status
    if changed and not (previous == "unknown" and status == "healthy"):
        if status in G.UNHEALTHY:
            create_alert(
                db,
                service.project_id,
                "critical" if status == "down" else "warning",
                f"{service.name} is {status}" + (f" ({error})" if error else ""),
                service_id=service.id,
            )
        elif previous in G.UNHEALTHY:
            create_alert(db, service.project_id, "info", f"{service.name} recovered", service_id=service.id)
    if changed:
        reconcile_incidents(db, service.project_id)
    db.commit()
    if changed:
        publish(
            service.project_id,
            "status_changed",
            {"service_id": service.id, "name": service.name, "from": previous, "to": status},
        )
    return check


# ------------------------------------------------------------- incidents
def reconcile_incidents(db: Session, project_id: int) -> None:
    """Open an incident for every root-cause service, resolve incidents whose root recovered."""
    graph = G.build_graph(db, project_id)
    candidates = G.root_cause_candidates(graph)
    candidate_ids = {c["service_id"] for c in candidates}

    open_auto = db.scalars(
        select(models.Incident).where(
            models.Incident.project_id == project_id,
            models.Incident.status != "resolved",
            models.Incident.root_cause_service_id.is_not(None),
            models.Incident.auto_detected.is_(True),
        )
    ).all()
    by_root = {i.root_cause_service_id: i for i in open_auto}

    for cand in candidates:
        sid = cand["service_id"]
        if sid in by_root:
            continue
        radius = G.blast_radius(graph, [sid])
        incident = models.Incident(
            project_id=project_id,
            title=f"{cand['name']} is {cand['status']}",
            severity=radius["severity"],
            status="investigating",
            root_cause_service_id=sid,
            auto_detected=True,
            summary=(
                f"Auto-detected root cause. {radius['affected_count']} downstream services are in the "
                f"blast radius ({radius['percent_affected']}% of the estate)."
            ),
        )
        db.add(incident)
        db.flush()
        _event(db, incident, "detected", f"{cand['name']} reported {cand['status']}; no dependency of it is unhealthy, so it is the likely origin.", sid)
        if radius["affected"]:
            names = ", ".join(a["name"] for a in radius["affected"][:12])
            more = f" (+{radius['affected_count'] - 12} more)" if radius["affected_count"] > 12 else ""
            _event(db, incident, "impact", f"Impacted services: {names}{more}.", sid)
        # Correlate with recent deployments of the root cause or anything it depends on.
        suspects = {sid, *graph.successors(sid)}
        since = models.utcnow() - timedelta(hours=2)
        for dep in db.scalars(
            select(models.Deployment)
            .where(models.Deployment.service_id.in_(suspects), models.Deployment.deployed_at >= since)
            .order_by(models.Deployment.deployed_at.desc())
        ):
            svc_name = G._name(graph, dep.service_id)
            _event(db, incident, "deployment", f"Recent deployment: {svc_name} {dep.version} by {dep.deployed_by or 'unknown'}.", dep.service_id)
        create_alert(
            db,
            project_id,
            "critical" if radius["severity"] in ("critical", "high") else "warning",
            f"Incident opened: {incident.title} — {radius['affected_count']} services impacted",
            kind="incident",
            service_id=sid,
            incident_id=incident.id,
        )
        publish(project_id, "incident_opened", {"incident_id": incident.id, "title": incident.title})

    for root_id, incident in by_root.items():
        if root_id in candidate_ids or root_id not in graph:
            continue
        if graph.nodes[root_id]["status"] in G.UNHEALTHY:
            # Still failing, but no longer the origin: something it depends on is now unhealthy too
            # (e.g. probes ran in an order that reported the downstream service first).
            upstream = sorted(
                G._name(graph, n) for n in nx.descendants(graph, root_id) if graph.nodes[n]["status"] in G.UNHEALTHY
            )
            incident.status = "resolved"
            incident.resolved_at = models.utcnow()
            _event(
                db, incident, "resolved",
                f"Merged: {graph.nodes[root_id]['name']} is failing because {', '.join(upstream) or 'a dependency'} "
                "is also unhealthy. Tracked under that incident instead.",
                root_id,
            )
            publish(project_id, "incident_resolved", {"incident_id": incident.id})
        elif graph.nodes[root_id]["status"] == "healthy":
            incident.status = "resolved"
            incident.resolved_at = models.utcnow()
            _event(db, incident, "resolved", f"{graph.nodes[root_id]['name']} is healthy again; incident auto-resolved.", root_id)
            publish(project_id, "incident_resolved", {"incident_id": incident.id})


def _event(db: Session, incident: models.Incident, kind: str, message: str, service_id: int | None = None) -> None:
    db.add(models.IncidentEvent(incident_id=incident.id, service_id=service_id, event_type=kind, message=message))


def prune_old_checks(db: Session) -> int:
    cutoff = models.utcnow() - timedelta(days=settings.health_retention_days)
    rows = db.scalars(select(models.HealthCheck).where(models.HealthCheck.checked_at < cutoff)).all()
    for r in rows:
        db.delete(r)
    db.commit()
    return len(rows)
