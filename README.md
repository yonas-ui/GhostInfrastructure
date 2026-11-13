# Ghost Infrastructure — The Invisible Dependency Detector

A digital X-ray for software infrastructure. It maps what depends on what, shows what breaks when something fails, finds the dependencies nobody documented, and traces an outage back to its likely origin.

## Quick start (Docker)

```bash
cp .env.example .env        # optional
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:3000 | Web app (React) |
| http://localhost:8000/docs | API docs (Swagger) |
| http://localhost:9090 | Prometheus |

Demo login: `demo@ghostinfra.dev` / `demo1234` (click "Use demo account").
The demo project is the scenario from the brief: 30 apps, 15 APIs, 4 databases, 5 third-party services, a cache, a queue and workers, with hidden dependencies planted and one live incident.

## Run without Docker

```bash
# backend (SQLite fallback; Redis is optional and disabled by default)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Tests: `cd backend && python -m pytest` (20 tests).

## Stack

| Layer | Used |
|---|---|
| Frontend | React + TypeScript, Vite |
| Graph | React Flow (`@xyflow/react`) + dagre layout |
| Styling | Tailwind CSS |
| Backend | FastAPI, SQLAlchemy |
| Database | PostgreSQL (SQLite for local/tests) |
| Graph queries | NetworkX **and** recursive SQL (`/impact/{id}?engine=sql`) |
| Real-time | WebSockets, fed by Redis pub/sub |
| Background | Celery worker + beat |
| Cache / broker | Redis |
| Monitoring | Prometheus (`/metrics`) |
| Deployment | Docker Compose |

## Database (10 tables)

`users`, `projects`, `services`, `dependencies`, `health_checks`, `incidents`, `incident_events`, `deployments`, `simulations`, `alerts`. See `backend/app/models.py`; a generated PostgreSQL DDL is in `backend/sql/schema.sql`. Tables are created automatically on startup.

Convention: a dependency row `source → target` means *source depends on target*.

## What it does

- **Map**: interactive graph, status colours, undocumented dependencies drawn as dashed amber lines.
- **Blast radius**: click a service to see everything that breaks if it fails, hop by hop.
- **Simulate**: fail several services at once; results are stored in `simulations` and never touch real state.
- **Ghost detection**: undocumented dependencies, shared databases, single points of failure, circular dependencies, forgotten workers, unowned critical services, third-party risk.
- **Root cause + incidents**: unhealthy services with no unhealthy dependency are the likely origin. Incidents open and resolve automatically, with a timeline that includes recent deployments. Probe order does not matter (downstream incidents are merged).
- **Discovery**: import runtime observations (`source -> target` pairs) or a docker-compose file (`depends_on`, links, hostnames in env vars).
- **Live**: WebSocket pushes refresh the UI; Celery probes every service with a `health_url` (`http(s)://` or `tcp://host:port`) every 30 s.
- **Metrics**: `ghost_service_up`, `ghost_open_incidents`, `ghost_dependencies{documented}`, … plus sample alert rules in `monitoring/alerts.yml`.

## Layout

```
backend/    FastAPI app, Celery tasks, services/graph.py (core analysis), tests, Dockerfile
frontend/   React + TS app, Dockerfile (nginx)
monitoring/ Prometheus config + alert rules
docker-compose.yml
```

## Notes

- Set a long random `SECRET_KEY` before any real deployment, and `SEED_DEMO=false` to skip demo data.
- Auth is JWT; every project is private to its owner.
