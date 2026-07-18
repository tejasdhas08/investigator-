"""Pipeline progress in Redis: key case:{id}:progress, 24h TTL (Section 2)."""
import json

import redis

from app.core.config import settings

_pool = redis.ConnectionPool.from_url(settings.redis_url)


def _r() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


def set_progress(case_id: str, stage: str, pct: int) -> None:
    _r().set(f"case:{case_id}:progress", json.dumps({"stage": stage, "pct": int(pct)}), ex=86400)


def get_progress(case_id: str) -> dict | None:
    raw = _r().get(f"case:{case_id}:progress")
    return json.loads(raw) if raw else None
