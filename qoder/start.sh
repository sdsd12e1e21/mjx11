#!/usr/bin/env bash
# StudyRelay startup script for POSIX systems.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/.data/powercontext"
APP_PORT="${APP_PORT:-18080}"
PC_PORT="${PC_PORT:-18000}"
MAX_WAIT="${PC_START_TIMEOUT:-60}"
if ! [[ "$MAX_WAIT" =~ ^[1-9][0-9]*$ ]]; then
    echo "PC_START_TIMEOUT must be a positive number of seconds." >&2
    exit 1
fi
mkdir -p "$DATA_DIR"
export POWERCONTEXT_HOME="$DATA_DIR"
export POWERCONTEXT_URL="http://127.0.0.1:$PC_PORT"
PC_LOG="$DATA_DIR/server.log"
PC_PID=""
cleanup() {
    if [ -n "$PC_PID" ]; then
        kill "$PC_PID" 2>/dev/null || true
        wait "$PC_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ready() {
    curl --fail --silent --show-error --max-time 2 "$POWERCONTEXT_URL/health/live" > /dev/null 2>&1
}
if ready; then
    echo "Reusing PowerContext at $POWERCONTEXT_URL"
else
    echo "Starting PowerContext at $POWERCONTEXT_URL"
    powercontext server run --host 127.0.0.1 --port "$PC_PORT" --no-env-file > "$PC_LOG" 2>&1 &
    PC_PID=$!
    DEADLINE=$((SECONDS + MAX_WAIT))
    PC_READY=false
    while [ "$SECONDS" -lt "$DEADLINE" ]; do
        if ! kill -0 "$PC_PID" 2>/dev/null; then
            echo "PowerContext exited before becoming ready. Log: $PC_LOG" >&2
            exit 1
        fi
        if ready; then PC_READY=true; break; fi
        sleep 0.25
    done
    if [ "$PC_READY" = false ]; then
        echo "PowerContext did not become ready within ${MAX_WAIT}s. StudyRelay was not started. Log: $PC_LOG" >&2
        exit 1
    fi
fi
echo "Open http://127.0.0.1:$APP_PORT ; press Ctrl+C to stop."
cd "$SCRIPT_DIR"
python -m uvicorn app.main:app --host 127.0.0.1 --port "$APP_PORT" --reload
