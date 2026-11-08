#!/usr/bin/env bash
# StudyRelay startup script for POSIX systems
# Starts PowerContext Server and the StudyRelay application.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/.data/powercontext"
APP_PORT="${APP_PORT:-18080}"
PC_PORT="${PC_PORT:-18000}"

echo "=== StudyRelay Startup ==="

# Create data directory
mkdir -p "$DATA_DIR"

# Set environment
export POWERCONTEXT_HOME="$DATA_DIR"
export POWERCONTEXT_URL="http://127.0.0.1:$PC_PORT"

# Track child processes for cleanup
PC_PID=""
PC_ALREADY_RUNNING=false

cleanup() {
    echo ""
    echo "Shutting down..."
    if [ -n "$PC_PID" ] && [ "$PC_ALREADY_RUNNING" = false ]; then
        echo "Stopping PowerContext Server (PID $PC_PID)..."
        kill "$PC_PID" 2>/dev/null || true
        wait "$PC_PID" 2>/dev/null || true
    fi
    echo "StudyRelay stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check if PowerContext server is already running
if curl --fail --silent --show-error --max-time 2 "http://127.0.0.1:$PC_PORT/health/live" > /dev/null 2>&1; then
    echo "PowerContext Server already running on port $PC_PORT"
    PC_ALREADY_RUNNING=true
else
    echo "Starting PowerContext Server on port $PC_PORT..."
    powercontext server run --port "$PC_PORT" --no-env-file &
    PC_PID=$!
    echo "PowerContext Server PID: $PC_PID"

    # Wait for server to be ready
    MAX_WAIT=30
    WAITED=0
    while [ $WAITED -lt $MAX_WAIT ]; do
        sleep 1
        WAITED=$((WAITED + 1))
        if curl --fail --silent --show-error --max-time 2 "http://127.0.0.1:$PC_PORT/health/live" > /dev/null 2>&1; then
            echo "PowerContext Server ready (waited ${WAITED}s)"
            break
        fi
    done
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "WARNING: PowerContext Server did not become ready within ${MAX_WAIT}s"
        echo "The application will start but memory operations may fail."
    fi
fi

# Start the StudyRelay application
echo "Starting StudyRelay application on port $APP_PORT..."
echo "Open http://127.0.0.1:$APP_PORT in your browser"
echo ""
echo "Press Ctrl+C to stop"

cd "$SCRIPT_DIR"
python -m uvicorn app.main:app --host 127.0.0.1 --port "$APP_PORT" --reload
