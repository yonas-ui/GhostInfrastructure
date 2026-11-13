from sqlalchemy.orm import Session

from .. import models
from . import graph as G


def run_simulation(
    db: Session,
    project: models.Project,
    user: models.User,
    failed_ids: list[int],
    name: str = "",
) -> models.Simulation:
    """'What breaks if these services fail?' Stored so results can be revisited and compared."""
    graph = G.build_graph(db, project.id)
    result = G.blast_radius(graph, failed_ids)
    result["failed_ids"] = [f["id"] for f in result["failed"]]
    label = name or "Failure of " + ", ".join(f["name"] for f in result["failed"])
    sim = models.Simulation(
        project_id=project.id,
        created_by=user.id,
        name=label[:160],
        failed_service_ids=result["failed_ids"],
        result=result,
    )
    db.add(sim)
    db.commit()
    db.refresh(sim)
    return sim
