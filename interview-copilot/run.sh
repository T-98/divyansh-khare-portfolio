#!/usr/bin/env bash
# One-command local startup: backend on :8000, frontend on :5173.
# First run creates the venv and installs everything.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example. Add your OPENAI_API_KEY to it."
  cp .env.example .env
fi

if ! grep -qE '^OPENAI_API_KEY=.+' .env; then
  echo "warning: OPENAI_API_KEY is empty in .env — the UI will load but turns will fail."
fi

if [ ! -d backend/.venv ]; then
  echo "→ creating backend venv"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -d frontend/node_modules ]; then
  echo "→ installing frontend dependencies"
  (cd frontend && npm install --silent)
fi

cleanup() {
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "→ backend  http://localhost:8000"
(cd backend && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!

echo "→ frontend http://localhost:5173"
(cd frontend && exec npm run dev -- --host) &
FRONTEND_PID=$!

wait
