from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import admin, audit_api, auth, cases, chat, exports, media, results, review, suspects
from app.core.config import settings
from app.core.limiter import limiter

app = FastAPI(title=settings.app_name, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "internal", "message": "Internal server error"})


@app.get("/healthz")
def healthz():
    return {"ok": True}


prefix = settings.api_v1_prefix
app.include_router(auth.router, prefix=prefix)
app.include_router(cases.router, prefix=prefix)
app.include_router(media.router, prefix=prefix)
app.include_router(results.router, prefix=prefix)
app.include_router(review.router, prefix=prefix)
app.include_router(suspects.router, prefix=prefix)
app.include_router(chat.router, prefix=prefix)
app.include_router(exports.router, prefix=prefix)
app.include_router(audit_api.router, prefix=prefix)
app.include_router(admin.router, prefix=prefix)

# Optional single-process deployment: serve the pre-built SPA from this same FastAPI
# process (used by deploy/run_local.py so no Node/nginx is required). No effect on the
# normal Docker deployment, where nginx serves the frontend and this dir is never set.
if settings.frontend_dist_dir:
    import pathlib

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = pathlib.Path(settings.frontend_dist_dir)
    if dist.is_dir():
        assets_dir = dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="spa-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Registered last: /api/*, /healthz, /assets/* above already matched first.
            requested = dist / full_path
            if requested.is_file():
                return FileResponse(str(requested))
            return FileResponse(str(dist / "index.html"))
