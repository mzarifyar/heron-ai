#!/usr/bin/env bash
set -Eeuo pipefail

trap 'echo "[cortex-ai] ERROR: failed at line ${LINENO}" >&2' ERR

log() {
  echo "[cortex-ai] $*"
}

die() {
  echo "[cortex-ai] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required but not installed"
}

echo "[cortex-ai] Bootstrapping local stack..."

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

require_cmd python3
require_cmd pip
require_cmd lsof

if [[ ! -d ".venv" ]]; then
  log "Creating virtual environment"
  python3 -m venv .venv
fi

source .venv/bin/activate

log "Installing Python dependencies"
python -m pip install -U pip wheel setuptools
python -m pip install -r requirements.txt

export CORTEX_API_HOST="${CORTEX_API_HOST:-0.0.0.0}"
export CORTEX_API_PORT="${CORTEX_API_PORT:-8080}"
export CORTEX_ENV="${CORTEX_ENV:-local}"
export CORTEX_REGION="${CORTEX_REGION:-phx}"
export CORTEX_ALARM_GUARD_SCRIPT="${CORTEX_ALARM_GUARD_SCRIPT:-tools/get_alarm_status.py}"

if [[ -n "${CORTEX_INGEST_TOKEN:-}" ]]; then
  log "Ingest token detected (CORTEX_INGEST_TOKEN)"
else
  log "No ingest token set; API accepts anonymous requests"
fi

if [[ -n "${OPERATOR_ACCESS_TOKEN:-}" ]]; then
  log "Using OPERATOR_ACCESS_TOKEN from environment"
else
  log "OPERATOR_ACCESS_TOKEN not set; alarm guard will return Unknown"
fi

log "Alarm guard script: ${CORTEX_ALARM_GUARD_SCRIPT}"

if lsof -nP -iTCP:"${CORTEX_API_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  PID="$(lsof -tn -iTCP:"${CORTEX_API_PORT}" -sTCP:LISTEN | head -n1)"
  if [[ -n "$PID" ]]; then
    log "Port ${CORTEX_API_PORT} is busy (pid ${PID}); terminating process"
    kill "$PID" >/dev/null 2>&1 || true
    sleep 1
  fi
fi

if lsof -nP -iTCP:"${CORTEX_API_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  PID="$(lsof -tn -iTCP:"${CORTEX_API_PORT}" -sTCP:LISTEN | head -n1)"
  die "Port ${CORTEX_API_PORT} is still busy after attempting to terminate pid ${PID}"
fi

log "Starting API on ${CORTEX_API_HOST}:${CORTEX_API_PORT}"

exec uvicorn app.main:create_app \
  --factory \
  --host "${CORTEX_API_HOST}" \
  --port "${CORTEX_API_PORT}"
