#!/usr/bin/env bash
# No-Docker local runner (for WSL / native Linux / macOS with apt or brew).
# Brings up the whole app with lightweight substitutes so nothing but Python,
# Node, and a package manager is required:
#   - SQLite instead of PostgreSQL (no pgvector — fine for demo/dev scale)
#   - moto's S3 server instead of MinIO (pure Python, no separate binary)
#   - PIPELINE_FAKE=1 / LLM_FAKE=1 by default — full demo, no GPU, no API key
#
# Usage:
#   cd deploy
#   ./run_local.sh
# Then open http://localhost:3000 (Ctrl+C stops everything).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
RUNDIR="$ROOT/.run_local"
mkdir -p "$RUNDIR"

echo "== Checking system dependencies =="
MISSING=()
command -v python3 >/dev/null || MISSING+=("python3")
command -v node >/dev/null || MISSING+=("nodejs")
command -v npm >/dev/null || MISSING+=("npm")
command -v ffmpeg >/dev/null || MISSING+=("ffmpeg")
command -v redis-server >/dev/null || MISSING+=("redis-server")
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "Missing: ${MISSING[*]}"
  echo "On Ubuntu/WSL, install with:"
  echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip nodejs npm ffmpeg redis-server"
  exit 1
fi

echo "== Python venv =="
if [ ! -d "$RUNDIR/venv" ]; then
  python3 -m venv "$RUNDIR/venv"
fi
source "$RUNDIR/venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt 'moto[server]'

echo "== Environment =="
export DATABASE_URL="sqlite:///$RUNDIR/app.db"
export REDIS_URL="redis://localhost:6379/0"
export S3_ENDPOINT_URL="http://localhost:9000"
export S3_PUBLIC_ENDPOINT_URL="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export PIPELINE_FAKE="${PIPELINE_FAKE:-1}"
export LLM_FAKE="${LLM_FAKE:-1}"
export JWT_SECRET="${JWT_SECRET:-local-dev-secret-change-me}"
export APP_ENCRYPTION_KEY="${APP_ENCRYPTION_KEY:-0000000000000000000000000000000000000000000000000000000000000000}"

PIDS=()
cleanup() {
  echo; echo "Stopping…"
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

echo "== Starting Redis =="
redis-server --daemonize no --port 6379 --logfile "$RUNDIR/redis.log" &
PIDS+=($!)
sleep 1

echo "== Starting fake S3 (moto) =="
(cd backend && python3 -m moto.server -p 9000 > "$RUNDIR/moto.log" 2>&1) &
PIDS+=($!)
sleep 2

echo "== DB migrate + seed =="
cd backend
python3 -c "from app.services.storage import ensure_bucket; ensure_bucket()"
python3 -m scripts.seed
cd "$ROOT"

echo "== Starting Celery worker =="
(cd backend && celery -A app.pipeline.celery_app.celery worker -Q cpu,gpu -l info --concurrency 1 > "$RUNDIR/celery.log" 2>&1) &
PIDS+=($!)

echo "== Starting API =="
(cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$RUNDIR/api.log" 2>&1) &
PIDS+=($!)
sleep 3

echo "== Starting frontend =="
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install --no-audit --no-fund)
fi
(cd frontend && npm run dev -- --host 0.0.0.0 > "$RUNDIR/vite.log" 2>&1) &
PIDS+=($!)
sleep 3

cat <<EOF

============================================================
 CrimeScene AI is running.

 Open:  http://localhost:3000
 Login: investigator@example.gov / Password123!
        (also supervisor@example.gov / admin@example.gov)

 Logs:  $RUNDIR/{api,celery,vite,moto,redis}.log
 Press Ctrl+C here to stop everything.
============================================================
EOF

wait
