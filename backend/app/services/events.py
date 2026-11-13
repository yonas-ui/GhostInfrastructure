"""Real-time fan-out.

Workers (Celery) and the API both call publish(). Events go through Redis pub/sub so that a
health check recorded in a Celery worker reaches WebSocket clients connected to the API.
If Redis is unavailable (or REDIS_URL is empty) events are delivered in-process instead.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket

from ..config import settings

log = logging.getLogger("ghost.events")
CHANNEL = "ghost:events"


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, project_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self.rooms[project_id].add(ws)

    def disconnect(self, project_id: int, ws: WebSocket) -> None:
        self.rooms[project_id].discard(ws)

    async def broadcast(self, project_id: int, payload: dict) -> None:
        for ws in list(self.rooms.get(project_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(project_id, ws)


manager = ConnectionManager()


def publish(project_id: int, event_type: str, data: dict | None = None) -> None:
    payload = {
        "project_id": project_id,
        "type": event_type,
        "data": data or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if settings.redis_url:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            client.publish(CHANNEL, json.dumps(payload))
            return
        except Exception as exc:  # fall through to in-process delivery
            log.debug("redis publish failed (%s); delivering locally", exc)
    if manager.loop is not None and manager.loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(project_id, payload), manager.loop)


async def redis_listener() -> None:
    """Runs inside the API process: forwards Redis messages to WebSocket clients."""
    if not settings.redis_url:
        return
    import redis.asyncio as aioredis

    while True:
        try:
            client = aioredis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL)
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    data = json.loads(msg["data"])
                    await manager.broadcast(data["project_id"], data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("redis listener error: %s; retrying in 3s", exc)
            await asyncio.sleep(3)
