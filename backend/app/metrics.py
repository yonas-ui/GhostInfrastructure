"""Prometheus metrics, computed from the database at scrape time.

A custom collector (instead of in-process gauges) means the numbers are right no matter which
process (API, Celery worker, beat) recorded the underlying health check.
"""
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select

from . import models
from .database import SessionLocal


class GhostCollector:
    def collect(self):
        up = GaugeMetricFamily("ghost_service_up", "1 if the service is healthy, 0.5 if degraded, 0 if down", labels=["project", "service", "type"])
        crit = GaugeMetricFamily("ghost_service_criticality", "Business criticality 1-5", labels=["project", "service"])
        latency = GaugeMetricFamily("ghost_service_latency_ms", "Latest probe latency", labels=["project", "service"])
        incidents = GaugeMetricFamily("ghost_open_incidents", "Open incidents", labels=["project"])
        deps = GaugeMetricFamily("ghost_dependencies", "Registered dependencies", labels=["project", "documented"])
        alerts = GaugeMetricFamily("ghost_unacknowledged_alerts", "Unacknowledged alerts", labels=["project"])
        score = {"healthy": 1.0, "degraded": 0.5, "down": 0.0}

        with SessionLocal() as db:
            projects = {p.id: p.name for p in db.scalars(select(models.Project))}
            latest_ids = select(func.max(models.HealthCheck.id)).group_by(models.HealthCheck.service_id)
            latest = {
                h.service_id: h
                for h in db.scalars(select(models.HealthCheck).where(models.HealthCheck.id.in_(latest_ids)))
            }
            for s in db.scalars(select(models.Service)):
                pname = projects.get(s.project_id, str(s.project_id))
                if s.status in score:
                    up.add_metric([pname, s.name, s.type], score[s.status])
                crit.add_metric([pname, s.name], s.criticality)
                h = latest.get(s.id)
                if h is not None and h.latency_ms is not None:
                    latency.add_metric([pname, s.name], h.latency_ms)
            for pid, pname in projects.items():
                n = db.scalar(select(func.count()).select_from(models.Incident).where(
                    models.Incident.project_id == pid, models.Incident.status != "resolved"))
                incidents.add_metric([pname], n or 0)
                a = db.scalar(select(func.count()).select_from(models.Alert).where(
                    models.Alert.project_id == pid, models.Alert.acknowledged.is_(False)))
                alerts.add_metric([pname], a or 0)
                for documented in (True, False):
                    c = db.scalar(select(func.count()).select_from(models.Dependency).where(
                        models.Dependency.project_id == pid, models.Dependency.documented.is_(documented)))
                    deps.add_metric([pname, str(documented).lower()], c or 0)
        yield from (up, crit, latency, incidents, deps, alerts)


_registered = False


def register() -> None:
    global _registered
    if not _registered:
        REGISTRY.register(GhostCollector())
        _registered = True


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
