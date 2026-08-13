#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "🚀 Starting Voice AI Agent..."

# Terminate on exit
trap 'kill $(jobs -p) 2>/dev/null' EXIT

# ── 1. Start token server (port 8000) ──────────────────────────────
echo "📡 Starting token server (port 8000)..."
uv run python server.py &
SERVER_PID=$!

# Wait for server to be ready
for i in $(seq 1 30); do
  if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
    echo "✅ Token server ready"
    break
  fi
  sleep 1
done

# ── 2. Start agent worker ───────────────────────────────────────────
echo "🤖 Starting agent worker..."
uv run python agent.py dev &
AGENT_PID=$!

# ── 3. Start frontend (port 3000) ───────────────────────────────────
echo "🌐 Starting frontend (port 3000)..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "=========================================================="
echo "   Voice AI Agent is running!                         "
echo "=========================================================="
echo "   Browser:      http://localhost:3000"
echo "   Token server: http://localhost:8000"
echo "   Agent worker: running in background"
echo ""
echo "   Press Ctrl+C to stop all services"
echo "=========================================================="

# Wait for any process to exit
wait -n

# If we get here, one process died - kill the others
kill "$SERVER_PID" "$AGENT_PID" "$FRONTEND_PID" 2>/dev/null
exit 1