"""Pipeline progress cache (case:{id}:progress, 24h TTL — Section 2).

Default backend is Redis (production/Docker deployment). PROGRESS_BACKEND=file
switches to a plain JSON-file store under PROGRESS_DIR, for the no-Redis local
runner (deploy/run_local.py) where a Redis server isn't available.
"""
import json
import pathlib
import time

from app.core.config import settings

_TTL_SECONDS = 86400


def _redis():
    import redis

    if not hasattr(_redis, "_pool"):
        _redis._pool = redis.ConnectionPool.from_url(settings.redis_url)
    return redis.Redis(connection_pool=_redis._pool)


def _file_path(case_id: str) -> pathlib.Path:
    d = pathlib.Path(settings.progress_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{case_id}.json"


def set_progress(case_id: str, stage: str, pct: int) -> None:
    if settings.progress_backend == "file":
        payload = {"stage": stage, "pct": int(pct), "expires_at": time.time() + _TTL_SECONDS}
        _file_path(case_id).write_text(json.dumps(payload))
        return
    _redis().set(f"case:{case_id}:progress", json.dumps({"stage": stage, "pct": int(pct)}), ex=_TTL_SECONDS)


def get_progress(case_id: str) -> dict | None:
    if settings.progress_backend == "file":
        p = _file_path(case_id)
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        if data.get("expires_at", 0) < time.time():
            p.unlink(missing_ok=True)
            return None
        return {"stage": data["stage"], "pct": data["pct"]}
    raw = _redis().get(f"case:{case_id}:progress")
    return json.loads(raw) if raw else None
