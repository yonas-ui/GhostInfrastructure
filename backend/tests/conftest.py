import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["REDIS_URL"] = ""          # in-process events only
os.environ["SEED_DEMO"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client):
    r = client.post("/api/auth/register", json={"email": "t@example.com", "name": "T", "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def project(client, auth):
    r = client.post("/api/projects", json={"name": "P"}, headers=auth)
    return r.json()["id"]


def make_estate(client, auth, pid):
    """web -> api -> db ; web -> api2 -> db ; worker -> db (nobody depends on worker) ; ext (third party) <- api2"""
    ids = {}
    spec = [("web", "application", 5), ("api", "api", 4), ("api2", "api", 3), ("db", "database", 5),
            ("worker", "worker", 2), ("ext", "external", 3)]
    for name, typ, crit in spec:
        r = client.post(f"/api/projects/{pid}/services", json={"name": name, "type": typ, "criticality": crit, "owner": "team" if name != "worker" else ""}, headers=auth)
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    edges = [("web", "api", True), ("web", "api2", True), ("api", "db", True), ("api2", "db", False),
             ("worker", "db", False), ("api2", "ext", True)]
    for s, t, documented in edges:
        r = client.post(f"/api/projects/{pid}/dependencies",
                        json={"source_id": ids[s], "target_id": ids[t], "documented": documented}, headers=auth)
        assert r.status_code == 201, r.text
    return ids
