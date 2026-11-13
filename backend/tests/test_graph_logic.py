"""Pure graph logic - no database needed."""
from datetime import datetime, timedelta, timezone

import networkx as nx

from app.services import graph as G
from app.services import discovery


def make(nodes, edges):
    g = nx.DiGraph()
    for n, (typ, status) in nodes.items():
        g.add_node(n, name=f"n{n}", type=typ, status=status, criticality=3, owner="x", health_url="")
    for i, (u, v) in enumerate(edges):
        g.add_edge(u, v, id=i, kind="http", documented=True, discovered_by="manual", observed_count=0)
    return g


def test_blast_radius_follows_dependents_not_dependencies():
    # 1 -> 2 -> 3   (1 depends on 2 depends on 3)
    g = make({1: ("application", "healthy"), 2: ("api", "healthy"), 3: ("database", "healthy")}, [(1, 2), (2, 3)])
    r = G.blast_radius(g, [3])
    assert {a["id"] for a in r["affected"]} == {1, 2}
    assert G.blast_radius(g, [1])["affected"] == []
    by_id = {a["id"]: a for a in r["affected"]}
    assert by_id[2]["depth"] == 1 and by_id[1]["depth"] == 2
    assert by_id[1]["path"] == [1, 2, 3]


def test_blast_radius_handles_cycles_and_multiple_failures():
    g = make({i: ("api", "healthy") for i in range(1, 5)}, [(1, 2), (2, 1), (3, 1), (4, 3)])
    assert {a["id"] for a in G.blast_radius(g, [2])["affected"]} == {1, 3, 4}
    r = G.blast_radius(g, [2, 4])
    assert r["failed"] and len(r["failed"]) == 2


def test_root_cause_picks_deepest_unhealthy_dependency():
    g = make(
        {1: ("application", "down"), 2: ("api", "down"), 3: ("database", "down"), 4: ("api", "healthy")},
        [(1, 2), (2, 3), (4, 3)],
    )
    cands = G.root_cause_candidates(g)
    assert [c["service_id"] for c in cands] == [3]
    assert cands[0]["explains"] == [1, 2]


def test_root_cause_in_cycle():
    g = make({1: ("api", "down"), 2: ("api", "down"), 3: ("application", "down")}, [(1, 2), (2, 1), (3, 1)])
    cands = G.root_cause_candidates(g)
    assert {c["service_id"] for c in cands} == {1, 2}
    assert all(c["in_cycle"] for c in cands)


def test_effective_status_marks_downstream_impacted():
    g = make({1: ("application", "healthy"), 2: ("database", "down")}, [(1, 2)])
    assert G.effective_statuses(g) == {1: "impacted", 2: "down"}


def test_ghost_detection_kinds():
    g = make(
        {1: ("application", "healthy"), 2: ("api", "healthy"), 3: ("database", "healthy"), 4: ("worker", "healthy"),
         5: ("api", "healthy"), 6: ("external", "healthy")},
        [(1, 3), (2, 3), (5, 3), (4, 3), (1, 2), (2, 1), (1, 6), (2, 6), (5, 6)],
    )
    g.edges[2, 3]["documented"] = False
    g.nodes[4]["owner"] = ""
    kinds = {f["kind"] for f in G.detect_ghosts(g, {4: datetime.now(timezone.utc) - timedelta(days=400)})}
    assert {"undocumented_dependency", "shared_resource", "circular_dependency", "forgotten_worker", "third_party_risk"} <= kinds


def test_compose_parser_finds_env_wiring():
    yml = """
services:
  web:
    image: nginx
    depends_on: [api]
  api:
    build: .
    environment:
      DATABASE_URL: postgres://u:p@db:5432/app
      CACHE: redis://cache:6379
  db:
    image: postgres:16
  cache:
    image: redis:7
"""
    parsed = discovery.parse_compose(yml)
    edges = {(e["source"], e["target"]): e["kind"] for e in parsed["dependencies"]}
    assert edges == {("web", "api"): "other", ("api", "db"): "database", ("api", "cache"): "cache"}
    assert {s["name"]: s["type"] for s in parsed["services"]}["db"] == "database"
