from tests.conftest import make_estate


def test_auth_and_isolation(client, auth):
    assert client.get("/api/projects").status_code == 401
    r = client.post("/api/auth/login", json={"email": "t@example.com", "password": "password123"})
    assert r.status_code == 200
    assert client.post("/api/auth/login", json={"email": "t@example.com", "password": "wrong-pass"}).status_code == 401
    pid = client.post("/api/projects", json={"name": "mine"}, headers=auth).json()["id"]
    other = client.post("/api/auth/register", json={"email": "o@example.com", "name": "O", "password": "password123"}).json()
    h2 = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/projects/{pid}", headers=h2).status_code == 404
    assert client.get(f"/api/projects/{pid}/graph", headers=h2).status_code == 404


def test_dependency_validation(client, auth, project):
    ids = make_estate(client, auth, project)
    dup = client.post(f"/api/projects/{project}/dependencies", json={"source_id": ids["web"], "target_id": ids["api"]}, headers=auth)
    assert dup.status_code == 409
    selfdep = client.post(f"/api/projects/{project}/dependencies", json={"source_id": ids["web"], "target_id": ids["web"]}, headers=auth)
    assert selfdep.status_code == 400


def test_graph_impact_and_sql_agree(client, auth, project):
    ids = make_estate(client, auth, project)
    g = client.get(f"/api/projects/{project}/graph", headers=auth).json()
    assert len(g["nodes"]) == 6 and len(g["edges"]) == 6

    nx_res = client.get(f"/api/projects/{project}/impact/{ids['db']}", headers=auth).json()
    sql_res = client.get(f"/api/projects/{project}/impact/{ids['db']}?engine=sql", headers=auth).json()
    nx_ids = {a["id"] for a in nx_res["affected"]}
    assert nx_ids == {ids["web"], ids["api"], ids["api2"], ids["worker"]}
    assert {r["id"] for r in sql_res["dependents"]} == nx_ids
    depth = {r["id"]: r["depth"] for r in sql_res["dependents"]}
    assert depth[ids["web"]] == 2 and depth[ids["api"]] == 1

    down = client.get(f"/api/projects/{project}/impact/{ids['web']}?engine=sql", headers=auth).json()
    assert {r["id"] for r in down["dependencies"]} == {ids["api"], ids["api2"], ids["db"], ids["ext"]}


def test_sql_recursion_survives_cycles(client, auth, project):
    a = client.post(f"/api/projects/{project}/services", json={"name": "a"}, headers=auth).json()["id"]
    b = client.post(f"/api/projects/{project}/services", json={"name": "b"}, headers=auth).json()["id"]
    for s, t in ((a, b), (b, a)):
        client.post(f"/api/projects/{project}/dependencies", json={"source_id": s, "target_id": t}, headers=auth)
    r = client.get(f"/api/projects/{project}/impact/{a}?engine=sql", headers=auth).json()
    assert {x["id"] for x in r["dependents"]} == {b, a} or {x["id"] for x in r["dependents"]} == {b}


def test_ghosts_endpoint(client, auth, project):
    ids = make_estate(client, auth, project)
    kinds = {f["kind"] for f in client.get(f"/api/projects/{project}/ghosts", headers=auth).json()}
    assert "undocumented_dependency" in kinds
    assert "shared_resource" in kinds
    assert "forgotten_worker" in kinds  # worker: no owner, no dependents, never deployed
    graph = client.get(f"/api/projects/{project}/graph", headers=auth).json()
    node = next(n for n in graph["nodes"] if n["id"] == ids["worker"])
    assert node["ghost"] is True


def test_outage_opens_and_recovery_resolves_incident(client, auth, project):
    ids = make_estate(client, auth, project)
    r = client.post(f"/api/services/{ids['db']}/health", json={"status": "down", "error": "conn refused"}, headers=auth)
    assert r.status_code == 201

    graph = client.get(f"/api/projects/{project}/graph", headers=auth).json()
    eff = {n["name"]: n["effective_status"] for n in graph["nodes"]}
    assert eff["db"] == "down" and eff["web"] == "impacted" and eff["api"] == "impacted" and eff["ext"] == "unknown"

    incidents = client.get(f"/api/projects/{project}/incidents?status=open", headers=auth).json()
    assert len(incidents) == 1 and incidents[0]["root_cause_service_id"] == ids["db"] and incidents[0]["auto_detected"]
    detail = client.get(f"/api/incidents/{incidents[0]['id']}", headers=auth).json()
    assert {e["event_type"] for e in detail["events"]} >= {"detected", "impact"}

    rc = client.get(f"/api/projects/{project}/root-cause", headers=auth).json()
    assert [c["service_id"] for c in rc["candidates"]] == [ids["db"]]

    # the API also goes down because of the db -> still ONE incident, rooted at db
    client.post(f"/api/services/{ids['api']}/health", json={"status": "down"}, headers=auth)
    assert len(client.get(f"/api/projects/{project}/incidents?status=open", headers=auth).json()) == 1

    alerts = client.get(f"/api/projects/{project}/alerts", headers=auth).json()
    assert any(a["kind"] == "incident" for a in alerts)

    client.post(f"/api/services/{ids['api']}/health", json={"status": "healthy"}, headers=auth)
    client.post(f"/api/services/{ids['db']}/health", json={"status": "healthy"}, headers=auth)
    assert client.get(f"/api/projects/{project}/incidents?status=open", headers=auth).json() == []
    resolved = client.get(f"/api/projects/{project}/incidents?status=resolved", headers=auth).json()
    assert len(resolved) == 1 and resolved[0]["resolved_at"]


def test_recent_deployment_is_correlated(client, auth, project):
    ids = make_estate(client, auth, project)
    client.post(f"/api/services/{ids['db']}/deployments", json={"version": "v9.9.9", "deployed_by": "bob"}, headers=auth)
    client.post(f"/api/services/{ids['db']}/health", json={"status": "down"}, headers=auth)
    inc = client.get(f"/api/projects/{project}/incidents", headers=auth).json()[0]
    events = client.get(f"/api/incidents/{inc['id']}", headers=auth).json()["events"]
    assert any(e["event_type"] == "deployment" and "v9.9.9" in e["message"] for e in events)


def test_simulation_is_stored(client, auth, project):
    ids = make_estate(client, auth, project)
    r = client.post(f"/api/projects/{project}/simulations", json={"failed_service_ids": [ids["db"], ids["ext"]]}, headers=auth)
    assert r.status_code == 201
    sim = r.json()
    assert sim["result"]["affected_count"] == 4
    assert sim["result"]["severity"] in ("low", "medium", "high", "critical")
    assert len(client.get(f"/api/projects/{project}/simulations", headers=auth).json()) == 1
    assert client.post(f"/api/projects/{project}/simulations", json={"failed_service_ids": [99999]}, headers=auth).status_code == 400
    # simulations must not change real service state
    graph = client.get(f"/api/projects/{project}/graph", headers=auth).json()
    assert all(n["status"] == "unknown" for n in graph["nodes"])


def test_discovery_observations_create_ghost_edges(client, auth, project):
    ids = make_estate(client, auth, project)
    body = {"observations": [
        {"source": "web", "target": "ext", "kind": "http"},
        {"source": "web", "target": "ext", "kind": "http"},
        {"source": "cron-job", "target": "db", "kind": "database"},
    ]}
    r = client.post(f"/api/projects/{project}/discover/observations", json=body, headers=auth).json()
    assert sorted(r["new_dependencies"]) == ["cron-job -> db", "web -> ext"]
    deps = client.get(f"/api/projects/{project}/dependencies", headers=auth).json()
    web_ext = next(d for d in deps if d["source_id"] == ids["web"] and d["target_id"] == ids["ext"])
    assert web_ext["documented"] is False and web_ext["observed_count"] == 2


def test_compose_import(client, auth, project):
    yml = "services:\n  api:\n    environment:\n      DB: postgres://x@db/app\n  db:\n    image: postgres\n"
    r = client.post(f"/api/projects/{project}/discover/compose", json={"content": yml}, headers=auth).json()
    assert sorted(r["new_services"]) == ["api", "db"] and r["new_dependencies"] == ["api -> db"]
    assert client.post(f"/api/projects/{project}/discover/compose", json={"content": "::: not yaml ["}, headers=auth).status_code == 400


def test_summary_metrics_and_delete_cascade(client, auth, project):
    ids = make_estate(client, auth, project)
    s = client.get(f"/api/projects/{project}/summary", headers=auth).json()
    assert s["services"] == 6 and s["dependencies"] == 6 and s["undocumented_dependencies"] == 2
    text = client.get("/metrics").text
    assert "ghost_service_up" in text and "ghost_dependencies" in text
    assert client.delete(f"/api/services/{ids['db']}", headers=auth).status_code == 204
    s = client.get(f"/api/projects/{project}/summary", headers=auth).json()
    assert s["services"] == 5 and s["dependencies"] == 3  # edges to the deleted db are gone


def test_websocket_receives_events(client, auth, project):
    ids = make_estate(client, auth, project)
    token = auth["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/projects/{project}?token={token}") as ws:
        client.post(f"/api/services/{ids['db']}/health", json={"status": "down"}, headers=auth)
        seen = set()
        for _ in range(4):
            seen.add(ws.receive_json()["type"])
            if "status_changed" in seen:
                break
        assert "status_changed" in seen
    try:
        with client.websocket_connect(f"/ws/projects/{project}?token=bad"):
            raise AssertionError("should have been rejected")
    except Exception as exc:  # starlette raises WebSocketDisconnect
        assert "AssertionError" not in type(exc).__name__


def test_downstream_failure_reported_first_is_merged_into_root_incident(client, auth, project):
    """Probe order must not matter: api (depends on db) reports down BEFORE db does."""
    ids = make_estate(client, auth, project)
    client.post(f"/api/services/{ids['api']}/health", json={"status": "down"}, headers=auth)
    assert len(client.get(f"/api/projects/{project}/incidents?status=open", headers=auth).json()) == 1  # api looks like the root for now
    client.post(f"/api/services/{ids['db']}/health", json={"status": "down"}, headers=auth)

    open_ = client.get(f"/api/projects/{project}/incidents?status=open", headers=auth).json()
    assert [i["root_cause_service_id"] for i in open_] == [ids["db"]]
    resolved = client.get(f"/api/projects/{project}/incidents?status=resolved", headers=auth).json()
    assert len(resolved) == 1 and resolved[0]["root_cause_service_id"] == ids["api"]
    events = client.get(f"/api/incidents/{resolved[0]['id']}", headers=auth).json()["events"]
    assert any("Merged" in e["message"] for e in events)
