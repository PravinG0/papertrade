#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/backend"
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" "${FRONTEND_PID:-}" 2>/dev/null || true' EXIT
cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1 --port 5173 &
FRONTEND_PID=$!
wait -n "$BACKEND_PID" "$FRONTEND_PID"
