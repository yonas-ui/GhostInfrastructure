"""Celery background tasks.

  ghost.check_all_services   every HEALTH_INTERVAL_SECONDS  - probe every service that has a health_url
  ghost.scan_ghosts          every 5 minutes                - raise alerts for newly found hidden risks
  ghost.prune_health_history daily                          - enforce retention
"""
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from . import models
from .celery_app import celery
from .config import settings
from .database import SessionLocal
from .services import graph as G
from .services import health as H
from .services.events import publish

# Ghost findings worth an alert (noisy kinds such as shared_resource stay in the UI only).
ALERTING_KINDS = {"undocumented_dependency", "circular_dependency", "forgotten_worker"}


@celery.task(name="ghost.check_all_services")
def check_all_services() -> int:
    with SessionLocal() as db:
        services = db.scalars(
            select(models.Service).where(models.Service.health_url.is_not(None), models.Service.health_url != "")
        ).all()
        if not services:
            return 0
        # Probes are I/O bound and independent: run them concurrently, write results serially.
        with ThreadPoolExecutor(max_workers=min(32, len(services))) as pool:
            results = list(pool.map(lambda s: H.probe(s.health_url, settings.health_timeout), services))
        for svc, result in zip(services, results):
            H.record_health(db, svc, **result)
        return len(services)


@celery.task(name="ghost.scan_ghosts")
def scan_ghosts() -> int:
    created = 0
    with SessionLocal() as db:
        for project in db.scalars(select(models.Project)):
            graph = G.build_graph(db, project.id)
            last = {}
            for dep in db.scalars(select(models.Deployment).where(models.Deployment.project_id == project.id)):
                cur = last.get(dep.service_id)
                if cur is None or dep.deployed_at > cur:
                    last[dep.service_id] = dep.deployed_at
            for f in G.detect_ghosts(graph, last):
                if f["kind"] not in ALERTING_KINDS:
                    continue
                key = f"ghost:{f['kind']}:{','.join(map(str, sorted(f['service_ids'])))}"
                alert = H.create_alert(
                    db,
                    project.id,
                    "warning" if f["severity"] in ("high", "critical") else "info",
                    f"{f['title']}: {f['detail']}",
                    kind="ghost",
                    service_id=f["service_ids"][0] if f["service_ids"] else None,
                    dedupe_key=key,
                )
                if alert:
                    created += 1
            db.commit()
            if created:
                publish(project.id, "alerts_changed", {})
    return created


@celery.task(name="ghost.prune_health_history")
def prune_health_history() -> int:
    with SessionLocal() as db:
        return H.prune_old_checks(db)
