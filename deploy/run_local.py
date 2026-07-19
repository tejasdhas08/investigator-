#!/usr/bin/env python3
"""Simplest possible local run: no Docker, no Node, no Redis, no WSL.

Requires only Python 3.10+ (with pip). Everything else — a venv, ffmpeg, a fake S3
server, the frontend — is handled by this one script, all inside a single process.

Usage (Windows cmd, macOS/Linux shell — identical either way):
    python run_local.py

Then open the URL it prints. Ctrl+C stops everything. All state lives under
deploy/.run_local/ — delete that folder to start over from scratch.

What this trades away vs. the Docker stack (deploy/docker-compose.yml) or the
Redis-based deploy/run_local.sh: PostgreSQL -> SQLite, MinIO -> an in-process fake S3
server (moto), a Celery worker+Redis -> synchronous in-process task execution
("eager" mode), and nginx+Vite -> the pre-built SPA served by FastAPI itself on the
same port as the API. Functionally equivalent for a single local user; not what you'd
run in production or for a multi-user deployment (see docker-compose.yml for that).
"""
import os
import pathlib
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
RUNDIR = ROOT / "deploy" / ".run_local"
VENV = RUNDIR / "venv"
IS_WINDOWS = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python3")
PORT = int(os.environ.get("PORT", "8000"))
S3_PORT = 9000


def bootstrap_venv_and_reexec() -> None:
    """First run: create a venv and re-launch this same script inside it, so every
    pip install below lands in an isolated environment rather than the system Python."""
    RUNDIR.mkdir(parents=True, exist_ok=True)
    if not VENV_PY.exists():
        print("[1/5] Creating a virtual environment (first run only)...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    if pathlib.Path(sys.executable).resolve() != VENV_PY.resolve():
        os.execv(str(VENV_PY), [str(VENV_PY), str(pathlib.Path(__file__).resolve()), *sys.argv[1:]])


def install_dependencies() -> None:
    marker = RUNDIR / "deps_installed.marker"
    req_hash = str((BACKEND / "requirements.txt").stat().st_mtime)
    if marker.exists() and marker.read_text() == req_hash:
        return
    print("[2/5] Installing Python dependencies (first run only, ~1-2 min)...")
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run(
        [str(VENV_PY), "-m", "pip", "install", "--quiet",
         "-r", str(BACKEND / "requirements.txt"), "moto[server]>=5", "static-ffmpeg>=2.5"],
        check=True,
    )
    marker.write_text(req_hash)


def ensure_ffmpeg() -> None:
    import shutil

    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        print("[3/5] ffmpeg found on PATH, skipping download.")
        return
    print("[3/5] Downloading a static ffmpeg build (first run only, needs internet)...")
    import static_ffmpeg

    try:
        static_ffmpeg.add_paths()  # prepends bundled ffmpeg/ffprobe to os.environ["PATH"]
    except Exception as exc:
        print(f"""
Could not download ffmpeg automatically ({exc}).
Install it yourself and re-run this script:
  - Windows: winget install ffmpeg   (or download from https://www.gyan.dev/ffmpeg/builds/
    and add its bin/ folder to your PATH)
  - macOS:   brew install ffmpeg
  - Linux:   sudo apt install ffmpeg
""")
        raise SystemExit(1)


def configure_environment() -> None:
    db_path = (RUNDIR / "app.db").resolve()
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    os.environ.setdefault("S3_ENDPOINT_URL", f"http://127.0.0.1:{S3_PORT}")
    os.environ.setdefault("S3_PUBLIC_ENDPOINT_URL", f"http://127.0.0.1:{S3_PORT}")
    os.environ.setdefault("S3_ACCESS_KEY", "minioadmin")
    os.environ.setdefault("S3_SECRET_KEY", "minioadmin")
    os.environ.setdefault("PROGRESS_BACKEND", "file")
    os.environ.setdefault("PROGRESS_DIR", str((RUNDIR / "progress").resolve()))
    os.environ.setdefault("CELERY_EAGER", "1")
    os.environ.setdefault("PIPELINE_FAKE", "1")
    os.environ.setdefault("LLM_FAKE", "1")
    os.environ.setdefault("JWT_SECRET", "local-dev-secret-change-me")
    os.environ.setdefault(
        "APP_ENCRYPTION_KEY",
        "0000000000000000000000000000000000000000000000000000000000000000",
    )
    frontend_dist = ROOT / "frontend" / "dist"
    if frontend_dist.is_dir():
        os.environ.setdefault("FRONTEND_DIST_DIR", str(frontend_dist.resolve()))
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)


def start_fake_s3() -> None:
    from moto.moto_server.threaded_moto_server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=S3_PORT, verbose=False)
    server.start()
    from app.services.storage import ensure_bucket

    ensure_bucket()


def seed_database() -> None:
    from app.core.db import Base, engine
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    from scripts.seed import main as seed_main

    seed_main()


def open_browser_when_ready(url: str) -> None:
    import urllib.request

    def wait_and_open():
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{url}/healthz", timeout=1)
                webbrowser.open(url)
                return
            except Exception:
                time.sleep(0.5)

    threading.Thread(target=wait_and_open, daemon=True).start()


def main() -> None:
    bootstrap_venv_and_reexec()
    install_dependencies()
    ensure_ffmpeg()
    configure_environment()

    print("[4/5] Starting fake S3 storage and seeding the database...")
    start_fake_s3()
    seed_database()

    url = f"http://localhost:{PORT}"
    print(f"""[5/5] Starting the app...

============================================================
 CrimeScene AI is running (no Docker, no Node, no Redis).

 Open:  {url}
 Login: investigator@example.gov / Password123!
        (also supervisor@example.gov / admin@example.gov)

 Everything runs in this one process/window. Press Ctrl+C to stop.
 State lives in deploy/.run_local/ — delete that folder to reset.
============================================================
""")
    open_browser_when_ready(url)

    import uvicorn
    from app.main import app

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
