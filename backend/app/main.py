import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import metrics, models
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .routers import analysis, auth, incidents, projects, services
from .security import decode_token
from .services.events import manager, redis_listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    if settings.seed_demo:
        from .seed import seed_demo

        with SessionLocal() as db:
            seed_demo(db)
    metrics.register()
    manager.loop = asyncio.get_running_loop()
    listener = asyncio.create_task(redis_listener())
    try:
        yield
    finally:
        listener.cancel()


app = FastAPI(
    title="Ghost Infrastructure",
    description="The invisible dependency detector - a digital X-ray for software infrastructure.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, projects.router, services.router, incidents.router, analysis.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["meta"])
def api_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    body, content_type = metrics.render()
    return Response(body, media_type=content_type)


@app.websocket("/ws/projects/{project_id}")
async def project_events(ws: WebSocket, project_id: int, token: str = Query("")):
    """Live events for one project. Authenticate with ?token=<JWT>."""
    user_id = decode_token(token)
    allowed = False
    if user_id:
        with SessionLocal() as db:
            project = db.get(models.Project, project_id)
            allowed = project is not None and project.owner_id == user_id
    if not allowed:
        await ws.close(code=4401)
        return
    await manager.connect(project_id, ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive; clients may send "ping"
    except WebSocketDisconnect:
        manager.disconnect(project_id, ws)
