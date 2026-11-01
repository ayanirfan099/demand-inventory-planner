#!/usr/bin/env bash
# Boots the API and the web app against a throwaway SQLite database for Playwright.
# Never point this at a real database: it deletes and recreates the e2e database.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

E2E_DIR="${FORECASTOPS_E2E_DATA_DIR:-$ROOT/data/e2e}"
PYTHON="${FORECASTOPS_PYTHON:-$ROOT/.venv/bin/python}"
ALEMBIC="${FORECASTOPS_ALEMBIC:-$ROOT/.venv/bin/alembic}"
API_PORT="${FORECASTOPS_API_PORT:-8000}"
WEB_PORT="${FORECASTOPS_WEB_PORT:-3000}"

export FORECASTOPS_ENVIRONMENT=development
export FORECASTOPS_DATABASE_URL="sqlite:///$E2E_DIR/e2e.db"
export FORECASTOPS_DATA_DIR="$E2E_DIR"
export FORECASTOPS_EXECUTION_MODE=thread
export FORECASTOPS_ALLOWED_ORIGINS="http://127.0.0.1:$WEB_PORT,http://localhost:$WEB_PORT"
export FORECASTOPS_LOG_LEVEL=WARNING
export FORECASTOPS_SKIP_ALEMBIC_LOGGING=1

mkdir -p "$E2E_DIR"
rm -f "$E2E_DIR/e2e.db" "$E2E_DIR/e2e.db-wal" "$E2E_DIR/e2e.db-shm"

echo "[e2e] migrating $FORECASTOPS_DATABASE_URL"
"$ALEMBIC" -c services/api/alembic.ini upgrade head >/dev/null

echo "[e2e] seeding demo data"
"$PYTHON" services/api/scripts/seed_demo.py >/dev/null

echo "[e2e] starting API on :$API_PORT"
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --app-dir services/api &
API_PID=$!

cleanup() {
  echo "[e2e] stopping API"
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$API_PORT/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[e2e] starting web on :$WEB_PORT"
cd apps/web
FORECASTOPS_API_ORIGIN="http://127.0.0.1:$API_PORT" exec npx next dev --hostname 127.0.0.1 --port "$WEB_PORT"
