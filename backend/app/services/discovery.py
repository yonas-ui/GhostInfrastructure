"""Dependency discovery: turn observations into (undocumented) dependencies.

Two sources are supported:
  * runtime observations  - e.g. exported from distributed traces / service meshes / access logs
  * docker-compose files  - depends_on, links and hostnames hiding in environment variables
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models

_DB_SCHEMES = {"postgres", "postgresql", "mysql", "mariadb", "mongodb", "mongodb+srv"}
_KIND_BY_SCHEME = {
    "redis": "cache", "rediss": "cache", "amqp": "queue", "amqps": "queue", "kafka": "queue",
    "http": "http", "https": "http", "grpc": "grpc",
}
_TYPE_BY_IMAGE = [
    ("postgres", "database"), ("mysql", "database"), ("mariadb", "database"), ("mongo", "database"),
    ("redis", "cache"), ("memcached", "cache"), ("rabbitmq", "queue"), ("kafka", "queue"),
    ("minio", "storage"), ("nginx", "other"),
]


def _find_service(db: Session, project_id: int, name: str) -> models.Service | None:
    return db.scalar(
        select(models.Service).where(models.Service.project_id == project_id, models.Service.name == name)
    )


def upsert_dependency(
    db: Session,
    project_id: int,
    source: models.Service,
    target: models.Service,
    kind: str,
    discovered_by: str,
    description: str = "",
) -> tuple[models.Dependency, bool]:
    """Create an undocumented dependency, or bump the observation counter of an existing one."""
    dep = db.scalar(
        select(models.Dependency).where(
            models.Dependency.source_id == source.id, models.Dependency.target_id == target.id
        )
    )
    created = dep is None
    if dep is None:
        dep = models.Dependency(
            project_id=project_id,
            source_id=source.id,
            target_id=target.id,
            kind=kind,
            description=description,
            documented=False,
            discovered_by=discovered_by,
        )
        db.add(dep)
    dep.observed_count = (dep.observed_count or 0) + 1
    dep.last_seen_at = models.utcnow()
    db.flush()  # autoflush is off: make this row visible to the next lookup in the same batch
    return dep, created


def ingest_observations(db: Session, project_id: int, observations: list[dict], create_missing: bool = True) -> dict:
    created, seen, unknown = [], 0, set()
    for obs in observations:
        names = {}
        for role in ("source", "target"):
            svc = _find_service(db, project_id, obs[role])
            if svc is None and create_missing:
                svc = models.Service(
                    project_id=project_id, name=obs[role], type="other",
                    description="Auto-created from discovery", criticality=2,
                )
                db.add(svc)
                db.flush()
            if svc is None:
                unknown.add(obs[role])
            names[role] = svc
        if names["source"] is None or names["target"] is None or names["source"].id == names["target"].id:
            continue
        dep, new = upsert_dependency(
            db, project_id, names["source"], names["target"], obs.get("kind", "http"), "trace"
        )
        seen += 1
        if new:
            created.append(f"{names['source'].name} -> {names['target'].name}")
    db.commit()
    return {"observations": seen, "new_dependencies": created, "unknown_services": sorted(unknown)}


def _guess_type(image: str | None, name: str) -> str:
    probe = f"{image or ''} {name}".lower()
    for needle, typ in _TYPE_BY_IMAGE:
        if needle in probe:
            return typ
    return "application"


def parse_compose(content: str) -> dict:
    """Extract services + edges from a docker-compose.yml. Pure function."""
    data = yaml.safe_load(content)
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        raise ValueError("expected a docker-compose file with a top-level 'services' mapping")
    services = data["services"]
    nodes = {name: _guess_type((cfg or {}).get("image"), name) for name, cfg in services.items()}
    edges: dict[tuple[str, str], tuple[str, str]] = {}

    for name, cfg in services.items():
        cfg = cfg or {}
        deps = cfg.get("depends_on") or []
        for target in (deps.keys() if isinstance(deps, dict) else deps):
            if target in nodes:
                edges[(name, target)] = ("other", "depends_on")
        for link in cfg.get("links") or []:
            target = str(link).split(":")[0]
            if target in nodes:
                edges.setdefault((name, target), ("other", "links"))
        env = cfg.get("environment") or {}
        if isinstance(env, list):
            env = dict(e.split("=", 1) for e in env if "=" in e)
        for key, value in env.items():
            value = str(value)
            parsed = urlparse(value) if "://" in value else None
            host = parsed.hostname if parsed else None
            if host is None and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value.lower()) and value in nodes:
                host = value
            if host and host in nodes and host != name:
                scheme = (parsed.scheme if parsed else "").lower()
                kind = "database" if scheme in _DB_SCHEMES else _KIND_BY_SCHEME.get(scheme, "http")
                # env-var wiring is exactly the kind of dependency that is rarely documented
                edges[(name, host)] = (kind, f"env {key}")
    return {
        "services": [{"name": n, "type": t} for n, t in nodes.items()],
        "dependencies": [
            {"source": s, "target": t, "kind": kind, "via": via} for (s, t), (kind, via) in edges.items()
        ],
    }


def import_compose(db: Session, project_id: int, content: str) -> dict:
    parsed = parse_compose(content)
    created_services, created_deps = [], []
    for svc in parsed["services"]:
        if _find_service(db, project_id, svc["name"]) is None:
            db.add(models.Service(project_id=project_id, name=svc["name"], type=svc["type"],
                                  description="Imported from docker-compose", criticality=3))
            created_services.append(svc["name"])
    db.flush()
    for edge in parsed["dependencies"]:
        source = _find_service(db, project_id, edge["source"])
        target = _find_service(db, project_id, edge["target"])
        if source and target:
            _, new = upsert_dependency(db, project_id, source, target, edge["kind"], "compose", f"via {edge['via']}")
            if new:
                created_deps.append(f"{source.name} -> {target.name}")
    db.commit()
    return {"new_services": created_services, "new_dependencies": created_deps}
