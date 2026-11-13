import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..access import owned_or_404, project_or_404
from ..database import get_db
from ..security import get_current_user
from ..services import discovery
from ..services import graph as G
from ..services.events import publish
from ..services.simulation import run_simulation

router = APIRouter(tags=["analysis"])
User = models.User


def _last_deploys(db: Session, project_id: int) -> dict:
    return dict(
        db.execute(
            select(models.Deployment.service_id, func.max(models.Deployment.deployed_at))
            .where(models.Deployment.project_id == project_id)
            .group_by(models.Deployment.service_id)
        ).all()
    )


@router.get("/projects/{project_id}/graph")
def get_graph(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Everything the UI needs to draw the map in one call."""
    project_or_404(db, user, project_id)
    g = G.build_graph(db, project_id)
    eff = G.effective_statuses(g)
    metrics = G.node_metrics(g)
    ghosts = G.detect_ghosts(g, _last_deploys(db, project_id))
    ghost_nodes: dict[int, list[str]] = {}
    ghost_edges: set[int] = set()
    for f in ghosts:
        if f["kind"] in ("forgotten_worker", "isolated_service", "unowned_service"):
            for sid in f["service_ids"][:1]:
                ghost_nodes.setdefault(sid, []).append(f["kind"])
        ghost_edges.update(f["edge_ids"])
    nodes = [
        {
            "id": n,
            "name": d["name"],
            "type": d["type"],
            "status": d["status"],
            "effective_status": eff[n],
            "criticality": d["criticality"],
            "owner": d["owner"],
            "ghost": n in ghost_nodes,
            "ghost_reasons": ghost_nodes.get(n, []),
            **metrics[n],
        }
        for n, d in g.nodes(data=True)
    ]
    edges = [
        {"id": d["id"], "source": u, "target": v, "kind": d["kind"], "documented": d["documented"],
         "discovered_by": d["discovered_by"], "observed_count": d["observed_count"]}
        for u, v, d in g.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/projects/{project_id}/impact/{service_id}")
def impact(
    project_id: int,
    service_id: int,
    engine: str = Query("networkx", pattern="^(networkx|sql)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Blast radius of a single service. `engine=sql` uses a recursive CTE instead of NetworkX."""
    project_or_404(db, user, project_id)
    svc = owned_or_404(db, user, models.Service, service_id)
    if svc.project_id != project_id:
        raise HTTPException(404, "Service not found")
    if engine == "sql":
        return {
            "engine": "sql",
            "dependents": G.dependents_sql(db, project_id, service_id),
            "dependencies": G.dependencies_sql(db, project_id, service_id),
        }
    g = G.build_graph(db, project_id)
    result = G.blast_radius(g, [service_id])
    result["engine"] = "networkx"
    result["dependencies"] = [
        {"id": n, "name": g.nodes[n]["name"], "type": g.nodes[n]["type"]}
        for n in sorted(nx.descendants(g, service_id))
    ]
    return result


@router.get("/projects/{project_id}/ghosts")
def ghosts(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    g = G.build_graph(db, project_id)
    return G.detect_ghosts(g, _last_deploys(db, project_id))


@router.get("/projects/{project_id}/root-cause")
def root_cause(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    g = G.build_graph(db, project_id)
    unhealthy = [n for n, d in g.nodes(data=True) if d["status"] in G.UNHEALTHY]
    return {"unhealthy_count": len(unhealthy), "candidates": G.root_cause_candidates(g)}


# -------------------------------------------------------------- simulations
@router.post("/projects/{project_id}/simulations", response_model=schemas.SimulationOut, status_code=201)
def create_simulation(project_id: int, body: schemas.SimulationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = project_or_404(db, user, project_id)
    valid = {s for s in db.scalars(select(models.Service.id).where(models.Service.project_id == project_id))}
    bad = [i for i in body.failed_service_ids if i not in valid]
    if bad:
        raise HTTPException(400, f"Unknown service ids: {bad}")
    return run_simulation(db, project, user, body.failed_service_ids, body.name)


@router.get("/projects/{project_id}/simulations", response_model=list[schemas.SimulationOut])
def list_simulations(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    return db.scalars(
        select(models.Simulation).where(models.Simulation.project_id == project_id)
        .order_by(models.Simulation.created_at.desc(), models.Simulation.id.desc()).limit(50)
    ).all()


@router.get("/simulations/{sim_id}", response_model=schemas.SimulationOut)
def get_simulation(sim_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return owned_or_404(db, user, models.Simulation, sim_id)


# ---------------------------------------------------------------- discovery
@router.post("/projects/{project_id}/discover/observations")
def discover_observations(project_id: int, body: schemas.ObservationBatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Feed runtime observations (traces, mesh telemetry, access logs). New edges are flagged undocumented."""
    project_or_404(db, user, project_id)
    result = discovery.ingest_observations(
        db, project_id, [o.model_dump() for o in body.observations], body.create_missing_services
    )
    publish(project_id, "graph_changed", {"reason": "discovery"})
    return result


@router.post("/projects/{project_id}/discover/compose")
def discover_compose(project_id: int, body: schemas.ComposeImport, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project_or_404(db, user, project_id)
    try:
        result = discovery.import_compose(db, project_id, body.content)
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, f"Could not parse docker-compose content: {exc}")
    publish(project_id, "graph_changed", {"reason": "discovery"})
    return result
