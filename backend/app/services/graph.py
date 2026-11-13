"""Graph analysis: blast radius, root cause, ghost detection.

Convention: edge A -> B means "A depends on B".
  * dependents of B   = predecessors (who breaks when B breaks)
  * dependencies of A = successors   (what A needs in order to work)
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

import networkx as nx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models
from ..config import settings

UNHEALTHY = {"down", "degraded"}
SHARED_TYPES = {"database", "cache", "queue", "storage"}


# ------------------------------------------------------------------ build
def build_graph(db: Session, project_id: int) -> nx.DiGraph:
    g = nx.DiGraph()
    for s in db.scalars(select(models.Service).where(models.Service.project_id == project_id)):
        g.add_node(
            s.id,
            name=s.name,
            type=s.type,
            status=s.status,
            criticality=s.criticality,
            owner=s.owner or "",
            health_url=s.health_url or "",
        )
    for d in db.scalars(select(models.Dependency).where(models.Dependency.project_id == project_id)):
        if d.source_id in g and d.target_id in g:
            g.add_edge(
                d.source_id,
                d.target_id,
                id=d.id,
                kind=d.kind,
                documented=d.documented,
                discovered_by=d.discovered_by,
                observed_count=d.observed_count,
            )
    return g


def _name(g: nx.DiGraph, n: int) -> str:
    return g.nodes[n]["name"]


# --------------------------------------------------------- blast radius
def severity_for(score: int) -> str:
    if score >= 60:
        return "critical"
    if score >= 30:
        return "high"
    if score >= 10:
        return "medium"
    return "low"


def blast_radius(g: nx.DiGraph, failed: list[int]) -> dict:
    """Everything that transitively depends on the failed services (multi-source BFS)."""
    failed = [f for f in dict.fromkeys(failed) if f in g]
    dist: dict[int, int] = {f: 0 for f in failed}
    via: dict[int, int | None] = {f: None for f in failed}
    queue = deque(failed)
    while queue:
        node = queue.popleft()
        for dependent in g.predecessors(node):
            if dependent not in dist:
                dist[dependent] = dist[node] + 1
                via[dependent] = node
                queue.append(dependent)

    def chain(n: int) -> list[int]:
        out = [n]
        while via[out[-1]] is not None:
            out.append(via[out[-1]])  # type: ignore[arg-type]
        return out

    affected = []
    for n in sorted(dist, key=lambda x: (dist[x], _name(g, x))):
        if n in failed:
            continue
        path = chain(n)
        affected.append(
            {
                "id": n,
                "name": _name(g, n),
                "type": g.nodes[n]["type"],
                "criticality": g.nodes[n]["criticality"],
                "depth": dist[n],
                "via": via[n],
                "path": path,
                "path_names": [_name(g, p) for p in path],
            }
        )

    total_crit = sum(d["criticality"] for _, d in g.nodes(data=True)) or 1
    lost_crit = sum(g.nodes[n]["criticality"] for n in dist)
    score = round(100 * lost_crit / total_crit)
    by_type: dict[str, int] = {}
    for a in affected:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1

    return {
        "failed": [{"id": f, "name": _name(g, f), "type": g.nodes[f]["type"]} for f in failed],
        "affected": affected,
        "affected_count": len(affected),
        "total_services": g.number_of_nodes(),
        "percent_affected": round(100 * len(dist) / g.number_of_nodes()) if g.number_of_nodes() else 0,
        "impact_score": score,
        "severity": severity_for(score),
        "by_type": by_type,
        "user_facing": [a["name"] for a in affected if a["type"] == "application"],
        "max_depth": max((a["depth"] for a in affected), default=0),
    }


# ------------------------------------------------------- effective state
def effective_statuses(g: nx.DiGraph) -> dict[int, str]:
    """Own status, except healthy services that sit downstream of a failure become 'impacted'."""
    eff = {n: d["status"] for n, d in g.nodes(data=True)}
    for n, d in g.nodes(data=True):
        if d["status"] in UNHEALTHY:
            for dependent in nx.ancestors(g, n):
                if g.nodes[dependent]["status"] not in UNHEALTHY:
                    eff[dependent] = "impacted"
    return eff


# ------------------------------------------------------------ root cause
def root_cause_candidates(g: nx.DiGraph) -> list[dict]:
    """Unhealthy services none of whose dependencies are unhealthy.

    Uses the condensation DAG so circular dependencies (A<->B) are handled:
    an unhealthy strongly-connected component with no unhealthy component below it is a root.
    """
    unhealthy = {n for n, d in g.nodes(data=True) if d["status"] in UNHEALTHY}
    if not unhealthy:
        return []
    cond = nx.condensation(g)
    out: list[dict] = []
    for comp, data in cond.nodes(data=True):
        members: set[int] = set(data["members"])
        bad = members & unhealthy
        if not bad:
            continue
        if any(set(cond.nodes[s]["members"]) & unhealthy for s in cond.successors(comp)):
            continue  # something it depends on is also broken -> not the origin
        for n in bad:
            explained = (nx.ancestors(g, n) & unhealthy) - {n}
            out.append(
                {
                    "service_id": n,
                    "name": _name(g, n),
                    "type": g.nodes[n]["type"],
                    "status": g.nodes[n]["status"],
                    "criticality": g.nodes[n]["criticality"],
                    "explains": sorted(explained),
                    "explains_count": len(explained),
                    "confidence": round((len(explained) + 1) / len(unhealthy), 2),
                    "in_cycle": len(members) > 1,
                }
            )
    out.sort(key=lambda c: (-c["explains_count"], -c["criticality"], c["name"]))
    return out


# ------------------------------------------------------------ node metrics
def node_metrics(g: nx.DiGraph) -> dict[int, dict]:
    return {
        n: {
            "dependents": g.in_degree(n),
            "dependencies": g.out_degree(n),
            "transitive_dependents": len(nx.ancestors(g, n)),
            "transitive_dependencies": len(nx.descendants(g, n)),
        }
        for n in g.nodes
    }


# -------------------------------------------------------- ghost detection
def detect_ghosts(
    g: nx.DiGraph,
    last_deploy: dict[int, datetime | None] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Find hidden / risky structure. Pure function of the graph (easy to test)."""
    last_deploy = last_deploy or {}
    now = now or datetime.now(timezone.utc)
    findings: list[dict] = []
    n_nodes = g.number_of_nodes()

    def add(kind, severity, title, detail, services=(), edges=()):
        findings.append(
            {
                "kind": kind,
                "severity": severity,
                "title": title,
                "detail": detail,
                "service_ids": list(services),
                "edge_ids": list(edges),
            }
        )

    # 1. undocumented (discovered) dependencies
    for u, v, d in g.edges(data=True):
        if not d["documented"]:
            seen = f" Observed {d['observed_count']}x." if d["observed_count"] else ""
            add(
                "undocumented_dependency",
                "high" if g.nodes[v]["criticality"] >= 4 else "medium",
                f"{_name(g, u)} → {_name(g, v)}",
                f"{_name(g, u)} depends on {_name(g, v)} but nobody documented it "
                f"(found via {d['discovered_by']}).{seen}",
                [u, v],
                [d["id"]],
            )

    # 2. shared data stores
    for n, d in g.nodes(data=True):
        if d["type"] in SHARED_TYPES:
            users = list(g.predecessors(n))
            if len(users) >= 2:
                owners = {g.nodes[u]["owner"] for u in users if g.nodes[u]["owner"]}
                sev = "high" if len(users) >= 4 or len(owners) >= 3 else "medium"
                add(
                    "shared_resource",
                    sev,
                    f"{d['name']} is shared by {len(users)} services",
                    "A slow query, lock or outage here hits all of: "
                    + ", ".join(sorted(_name(g, u) for u in users))
                    + ".",
                    [n, *users],
                )

    # 3. single points of failure (large transitive blast radius)
    threshold = max(5, round(n_nodes * 0.35))
    for n in g.nodes:
        deps = nx.ancestors(g, n)
        if len(deps) >= threshold:
            add(
                "single_point_of_failure",
                "critical" if len(deps) >= n_nodes * 0.5 else "high",
                f"{_name(g, n)} is a single point of failure",
                f"{len(deps)} of {n_nodes} services ({round(100 * len(deps) / n_nodes)}%) "
                f"depend on it directly or indirectly.",
                [n],
            )

    # 4. circular dependencies
    for cycle in nx.simple_cycles(g):
        if len(cycle) > 8:
            continue
        names = " → ".join(_name(g, c) for c in cycle + [cycle[0]])
        add("circular_dependency", "high", "Circular dependency", names, cycle)

    # 5. forgotten workers / zombie services
    stale_cutoff = now - timedelta(days=settings.stale_days)
    for n, d in g.nodes(data=True):
        deployed = models.aware(last_deploy.get(n))
        stale = deployed is None or deployed < stale_cutoff
        if d["type"] == "worker" and g.in_degree(n) == 0 and (stale or not d["owner"]):
            why = []
            if not d["owner"]:
                why.append("has no owner")
            if deployed is None:
                why.append("has no deployment on record")
            elif stale:
                why.append(f"was last deployed {(now - deployed).days} days ago")
            add(
                "forgotten_worker",
                "high",
                f"{d['name']} looks forgotten",
                "Nothing declares a dependency on this worker, yet it "
                + " and ".join(why)
                + ". It may still be running and touching: "
                + (", ".join(sorted(_name(g, t) for t in g.successors(n))) or "nothing known")
                + ".",
                [n, *g.successors(n)],
            )
        elif d["type"] != "worker" and g.degree(n) == 0:
            add(
                "isolated_service",
                "low",
                f"{d['name']} has no known relationships",
                "Either it is genuinely standalone or its dependencies are still undiscovered.",
                [n],
            )

    # 6. unowned important services
    for n, d in g.nodes(data=True):
        if not d["owner"] and d["criticality"] >= 4 and d["type"] != "external":
            add(
                "unowned_service",
                "medium",
                f"{d['name']} has no owner",
                f"Criticality {d['criticality']}/5 and nobody to page.",
                [n],
            )

    # 7. third-party risk
    for n, d in g.nodes(data=True):
        if d["type"] == "external" and g.in_degree(n) > 0:
            deps = nx.ancestors(g, n)
            if len(deps) >= 3:
                add(
                    "third_party_risk",
                    "medium",
                    f"{d['name']} (third party) is relied on by {len(deps)} services",
                    "You do not control its uptime. Check whether you have a fallback.",
                    [n],
                )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (order[f["severity"]], f["kind"], f["title"]))
    return findings


# ------------------------------------------------- recursive SQL variants
_UP = """
WITH RECURSIVE walk(service_id, depth, path) AS (
    SELECT d.source_id, 1,
           ',' || CAST(:sid AS VARCHAR(20)) || ',' || CAST(d.source_id AS VARCHAR(20)) || ','
    FROM dependencies d
    WHERE d.target_id = :sid AND d.project_id = :pid
  UNION ALL
    SELECT d.source_id, w.depth + 1,
           w.path || CAST(d.source_id AS VARCHAR(20)) || ','
    FROM dependencies d
    JOIN walk w ON d.target_id = w.service_id
    WHERE d.project_id = :pid
      AND w.depth < :maxdepth
      AND w.path NOT LIKE '%,' || CAST(d.source_id AS VARCHAR(20)) || ',%'
)
SELECT s.id, s.name, s.type, MIN(w.depth) AS depth
FROM walk w JOIN services s ON s.id = w.service_id
GROUP BY s.id, s.name, s.type
ORDER BY depth, s.name
"""

_DOWN = _UP.replace("d.source_id", "@@").replace("d.target_id", "d.source_id").replace("@@", "d.target_id")


def _run(db: Session, sql: str, project_id: int, service_id: int, max_depth: int) -> list[dict]:
    rows = db.execute(
        text(sql), {"pid": project_id, "sid": service_id, "maxdepth": max_depth}
    ).mappings()
    return [dict(r) for r in rows]


def dependents_sql(db: Session, project_id: int, service_id: int, max_depth: int = 25) -> list[dict]:
    """Recursive CTE: all services that (transitively) depend on `service_id`."""
    return _run(db, _UP, project_id, service_id, max_depth)


def dependencies_sql(db: Session, project_id: int, service_id: int, max_depth: int = 25) -> list[dict]:
    """Recursive CTE: everything `service_id` (transitively) needs."""
    return _run(db, _DOWN, project_id, service_id, max_depth)
