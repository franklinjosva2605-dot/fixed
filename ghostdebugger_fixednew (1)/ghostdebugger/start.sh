#!/bin/bash
# GhostDebugger — Container start script
# Runs FastAPI backend + Streamlit frontend concurrently

set -e

echo "======================================"
echo "  👻 GhostDebugger v1.0.0"
echo "  AMD AI Developer Hackathon Act II"
echo "======================================"

# Start FastAPI backend
echo "[1/2] Starting FastAPI backend on :8000..."
python -m uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..20}; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "Backend ready ✓"
        break
    fi
    sleep 1
done

# Start Streamlit frontend
echo "[2/2] Starting Streamlit frontend on :8501..."
streamlit run frontend/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false \
    --theme.base dark &
FRONTEND_PID=$!

echo ""
echo "GhostDebugger is running:"
echo "  API:      http://localhost:8000"
echo "  UI:       http://localhost:8501"
echo "  Docs:     http://localhost:8000/docs"
echo "  Health:   http://localhost:8000/health"
echo ""

# Wait for either process to exit
wait -n $BACKEND_PID $FRONTEND_PID
EXIT_CODE=$?
echo "Process exited with code $EXIT_CODE"
exit $EXIT_CODE
