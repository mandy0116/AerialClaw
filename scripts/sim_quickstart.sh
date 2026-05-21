#!/usr/bin/env bash
# ============================================================
# AerialClaw — Full PX4/Gazebo Research Demo Quickstart
# ============================================================
# Starts the full local research demo stack:
#   1) optional PX4/Gazebo setup
#   2) PX4 + Gazebo + Micro XRCE-DDS Agent
#   3) AerialClaw backend with PX4 adapter
#   4) UI/API/sensor health checks
#
# Usage:
#   ./scripts/sim_quickstart.sh --setup          # first run: install/build prerequisites managed by this repo
#   ./scripts/sim_quickstart.sh                  # next runs: start simulator + backend
#   ./scripts/sim_quickstart.sh --restart        # stop previous repo-started stack, then start again
#   ./scripts/sim_quickstart.sh default x500     # control-debug fallback only; not the research showcase
#
# This script is intentionally conservative: it only kills processes that were
# started through its own pid files unless --restart is given.
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

SETUP=0
RESTART=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --setup) SETUP=1 ;;
    --restart) RESTART=1 ;;
    -h|--help)
      sed -n '1,36p' "$0"
      exit 0
      ;;
    *) ARGS+=("$arg") ;;
  esac
done

WORLD="${PX4_GZ_WORLD:-${ARGS[0]:-urban_rescue}}"
MODEL="${PX4_SIM_MODEL:-${ARGS[1]:-x500_lidar_2d_cam}}"
HOST="${SERVER_HOST:-127.0.0.1}"
PORT="${SERVER_PORT:-5001}"
BASE_URL="http://${HOST}:${PORT}"
GZ_PYTHONPATH="${GZ_PYTHONPATH:-}"

SIM_PID_FILE="/tmp/aerialclaw_full_sim.pid"
SERVER_PID_FILE="/tmp/aerialclaw_full_server.pid"
SIM_LOG="/tmp/aerialclaw_full_sim_launcher.log"
SERVER_LOG="/tmp/aerialclaw_full_server.log"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; RED=$'\033[0;31m'; NC=$'\033[0m'
else
  GREEN=''; YELLOW=''; BLUE=''; RED=''; NC=''
fi

info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$1"; }
ok() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$1"; }
warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$1"; }
err() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$1"; }

python_version_tuple() {
  "$1" - <<'PYVER' 2>/dev/null
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PYVER
}

python_is_supported() {
  "$1" - <<'PYVER' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PYVER
}

find_supported_python() {
  local candidates=()
  if [ -n "${AERIALCLAW_PYTHON:-}" ]; then candidates+=("$AERIALCLAW_PYTHON"); fi
  candidates+=("python3.12" "python3.11" "python3.10" "python3")
  [ -x "${HOME}/.pyenv/shims/python3" ] && candidates+=("${HOME}/.pyenv/shims/python3")
  [ -x "/opt/homebrew/bin/python3" ] && candidates+=("/opt/homebrew/bin/python3")
  local candidate resolved
  for candidate in "${candidates[@]}"; do
    resolved=""
    if [[ "$candidate" = /* ]] && [ -x "$candidate" ]; then resolved="$candidate"; elif command -v "$candidate" >/dev/null 2>&1; then resolved="$(command -v "$candidate")"; fi
    if [ -n "$resolved" ] && python_is_supported "$resolved"; then printf "%s" "$resolved"; return 0; fi
  done
  return 1
}

is_pid_alive() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1
}

stop_from_pid_file() {
  local file="$1"
  local label="$2"
  if [ -f "$file" ]; then
    local pid
    pid="$(cat "$file" 2>/dev/null || true)"
    if is_pid_alive "$pid"; then
      info "Stopping previous ${label} process (PID ${pid})"
      kill "$pid" >/dev/null 2>&1 || true
      sleep 2
      if is_pid_alive "$pid"; then
        warn "${label} did not stop gracefully; sending SIGTERM again"
        kill -TERM "$pid" >/dev/null 2>&1 || true
        sleep 1
      fi
    fi
    rm -f "$file"
  fi
}

wait_http() {
  local url="$1"
  local name="$2"
  local max_wait="${3:-90}"
  for i in $(seq 1 "$max_wait"); do
    if curl -fsS "$url" >/tmp/aerialclaw_quickstart_http.json 2>/dev/null; then
      ok "$name is ready: $url"
      return 0
    fi
    sleep 1
  done
  err "$name did not become ready: $url"
  return 1
}

ensure_python_env() {
  local base_python
  base_python="$(find_supported_python || true)"
  if [ -z "$base_python" ]; then
    err "Python >=3.10 is required. Set AERIALCLAW_PYTHON=/path/to/python3.11 and retry."
    exit 1
  fi

  local existing_python=""
  if [ -x "$PROJECT_DIR/venv/bin/python" ]; then
    existing_python="$PROJECT_DIR/venv/bin/python"
  elif [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    existing_python="$PROJECT_DIR/.venv/bin/python"
  fi

  if [ -n "$existing_python" ]; then
    if python_is_supported "$existing_python"; then
      PYTHON="$existing_python"
      ok "Using existing Python environment: $PYTHON ($(python_version_tuple "$PYTHON"))"
      return
    fi
    if [ "$SETUP" = "1" ]; then
      warn "Existing virtualenv uses unsupported Python $(python_version_tuple "$existing_python"); recreating venv with $base_python"
      rm -rf "$PROJECT_DIR/venv"
    else
      err "Existing virtualenv uses unsupported Python $(python_version_tuple "$existing_python"). Run ./scripts/sim_quickstart.sh --setup to recreate it."
      exit 1
    fi
  fi

  if [ "$SETUP" = "1" ]; then
    info "Creating Python virtual environment with $base_python ($(python_version_tuple "$base_python"))"
    "$base_python" -m venv "$PROJECT_DIR/venv"
    PYTHON="$PROJECT_DIR/venv/bin/python"
    "$PYTHON" -m pip install --upgrade pip wheel setuptools
    "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
    ok "Python dependencies installed"
    return
  fi

  PYTHON="$base_python"
  warn "No venv/.venv found; using Python: $PYTHON ($(python_version_tuple "$PYTHON"))"
}

ensure_app_python_deps() {
  if "$PYTHON" -c "import flask, flask_socketio, flask_cors, mavsdk" >/dev/null 2>&1; then
    ok "Backend Python dependencies are importable"
    return
  fi
  if [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
    err "requirements.txt not found; cannot install backend Python dependencies."
    exit 1
  fi
  info "Installing backend Python dependencies"
  "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
  ok "Backend Python dependencies installed"
}

ensure_gazebo_python_path() {
  if "$PYTHON" -c "import gz.transport13, gz.msgs10.image_pb2" >/dev/null 2>&1; then
    ok "Gazebo Python bindings are importable"
    return
  fi

  local pyver transport_site msgs_site msgs_legacy_site combo
  pyver="$($PYTHON - <<'PYVER'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PYVER
)"

  # Use only Gazebo Cellar paths. Do not add /opt/homebrew/lib/pythonX/site-packages,
  # because that can shadow the venv with unrelated Homebrew packages.
  local transport_candidates=("/opt/homebrew/Cellar/gz-transport13"/*"/lib/python${pyver}/site-packages")
  local msgs_candidates=("/opt/homebrew/Cellar/gz-msgs10"/*"/lib/python${pyver}/site-packages")
  local msgs_legacy_candidates=("/opt/homebrew/Cellar/gz-msgs10"/*"/lib/python")

  for transport_site in "${transport_candidates[@]}"; do
    [ -d "$transport_site/gz" ] || continue
    for msgs_site in "${msgs_candidates[@]}"; do
      [ -d "$msgs_site/gz" ] || continue
      for msgs_legacy_site in "${msgs_legacy_candidates[@]}"; do
        [ -d "$msgs_legacy_site/gz" ] || msgs_legacy_site=""
        combo="$transport_site:$msgs_site${msgs_legacy_site:+:$msgs_legacy_site}"
        if PYTHONPATH="$combo:${PYTHONPATH:-}" "$PYTHON" -c "import gz.transport13, gz.msgs10.image_pb2" >/dev/null 2>&1; then
          GZ_PYTHONPATH="$combo${GZ_PYTHONPATH:+:$GZ_PYTHONPATH}"
          export PYTHONPATH="$combo:${PYTHONPATH:-}"
          ok "Gazebo Python bindings found: $combo"
          return
        fi
      done
    done
  done

  warn "Gazebo Python bindings are not importable from the current Python environment; camera panels may show NO SIGNAL."
}

ensure_frontend_build() {
  if [ -f "$PROJECT_DIR/ui/dist/index.html" ]; then
    ok "Frontend build exists: ui/dist/index.html"
    return
  fi
  if ! command -v npm >/dev/null 2>&1; then
    warn "npm not found; backend can still run, but build the frontend later with: cd ui && npm install && npm run build"
    return
  fi
  info "Building Web UI"
  (cd "$PROJECT_DIR/ui" && npm install --no-audit --no-fund && npm run build)
  ok "Frontend built"
}

printf "============================================================\n"
printf " AerialClaw full simulator quickstart\n"
printf " Project: %s\n" "$PROJECT_DIR"
printf " World:   %s\n" "$WORLD"
printf " Model:   %s\n" "$MODEL"
printf " UI:      %s\n" "$BASE_URL"
printf "============================================================\n\n"

cd "$PROJECT_DIR"

if [ "$RESTART" = "1" ]; then
  stop_from_pid_file "$SERVER_PID_FILE" "AerialClaw backend"
  stop_from_pid_file "$SIM_PID_FILE" "simulation launcher"
fi

ensure_python_env
ensure_app_python_deps
ensure_gazebo_python_path
ensure_frontend_build

if [ "$SETUP" = "1" ]; then
  info "Running first-time PX4/Gazebo setup"
  "$SCRIPT_DIR/setup_px4.sh"
fi

info "Running preflight doctor"
if ! "$SCRIPT_DIR/doctor_gazebo.sh" "$WORLD" "$MODEL"; then
  err "Preflight doctor found blocking issues."
  echo ""
  if [ ! -x "$PROJECT_DIR/PX4-Autopilot/build/px4_sitl_default/bin/px4" ]; then
    echo "PX4 SITL binary is missing. Run the setup path once; it now installs PX4 Python build dependencies automatically:"
  else
    echo "First-time setup command:"
  fi
  echo "  ./scripts/sim_quickstart.sh --setup"
  echo ""
  echo "Control-debug fallback only, not the research showcase:"
  echo "  ./scripts/sim_quickstart.sh default x500"
  exit 1
fi

if [ -f "$SIM_PID_FILE" ] && is_pid_alive "$(cat "$SIM_PID_FILE")"; then
  warn "Simulation launcher already running (PID $(cat "$SIM_PID_FILE")). Use --restart to restart it."
else
  info "Starting PX4 + Gazebo simulation launcher"
  WORLD="$WORLD" MODEL="$MODEL" "$SCRIPT_DIR/start_sim.sh" "$WORLD" "$MODEL" >"$SIM_LOG" 2>&1 &
  echo $! > "$SIM_PID_FILE"
  ok "Simulation launcher started (PID $(cat "$SIM_PID_FILE"), log: $SIM_LOG)"
fi

info "Waiting for simulator startup"
sleep 18
if ! is_pid_alive "$(cat "$SIM_PID_FILE" 2>/dev/null || true)"; then
  err "Simulation launcher exited early. Last log lines:"
  tail -120 "$SIM_LOG" 2>/dev/null || true
  exit 1
fi

if [ -f "$SERVER_PID_FILE" ] && is_pid_alive "$(cat "$SERVER_PID_FILE")"; then
  warn "AerialClaw backend already running (PID $(cat "$SERVER_PID_FILE")). Use --restart to restart it."
else
  info "Starting AerialClaw backend with PX4 adapter"
  PYTHONPATH="${GZ_PYTHONPATH:+$GZ_PYTHONPATH:}${PYTHONPATH:-}" \
  SIM_ADAPTER=px4 PX4_GZ_WORLD="$WORLD" PX4_SIM_MODEL="$MODEL" SERVER_HOST="$HOST" SERVER_PORT="$PORT" \
    "$PYTHON" server.py >"$SERVER_LOG" 2>&1 &
  echo $! > "$SERVER_PID_FILE"
  ok "Backend started (PID $(cat "$SERVER_PID_FILE"), log: $SERVER_LOG)"
fi

wait_http "$BASE_URL/api/status" "AerialClaw backend" 90 || {
  tail -120 "$SERVER_LOG" 2>/dev/null || true
  exit 1
}

info "Initializing AerialClaw runtime"
if curl -fsS -X POST "$BASE_URL/api/init" >/tmp/aerialclaw_quickstart_init.json 2>/dev/null; then
  ok "Runtime initialized"
else
  warn "Runtime init endpoint did not return success yet. You can still click Initialize System in the UI."
fi

info "Checking sensor bridge"
SENSOR_READY=0
for i in $(seq 1 45); do
  if curl -fsS "$BASE_URL/api/sensor/status" >/tmp/aerialclaw_quickstart_sensor.json 2>/dev/null; then
    if "$PYTHON" - <<'PYSENSOR'
import json
from pathlib import Path
try:
    data = json.loads(Path('/tmp/aerialclaw_quickstart_sensor.json').read_text())
    raise SystemExit(0 if data.get('running') else 1)
except Exception:
    raise SystemExit(1)
PYSENSOR
    then
      SENSOR_READY=1
      break
    fi
  fi
  sleep 1
done
if [ "$SENSOR_READY" = "1" ]; then
  ok "Sensor bridge is running"
  cat /tmp/aerialclaw_quickstart_sensor.json
  echo ""
else
  warn "Sensor bridge endpoint is reachable but not running yet. Latest status:"
  cat /tmp/aerialclaw_quickstart_sensor.json 2>/dev/null || true
  echo ""
  warn "Run live diagnostics: ./scripts/doctor_gazebo.sh ${WORLD} ${MODEL} --live"
fi

printf "\n============================================================\n"
printf "%bFull simulator stack is running.%b\n" "$GREEN" "$NC"
printf "\n"
printf "Open Web UI:\n  %s\n\n" "$BASE_URL"
printf "Camera check:\n  Open Cockpit / camera panels. If they show NO SIGNAL, run:\n"
printf "  ./scripts/doctor_gazebo.sh %s %s --live\n\n" "$WORLD" "$MODEL"
printf "LLM setup for autonomous flight:\n"
printf "  1) cp .env.example .env\n"
printf "  2) edit ACTIVE_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL\n"
printf "  3) restart with: ./scripts/sim_quickstart.sh --restart\n"
printf "  4) or configure providers in the Web UI Model Configuration panel\n\n"
printf "Try after LLM is configured:\n"
printf "  Initialize System → AI mode → 'Take off to 15 meters and observe the surroundings.'\n\n"
printf "Logs:\n"
printf "  Simulator launcher: %s\n" "$SIM_LOG"
printf "  Backend:            %s\n" "$SERVER_LOG"
printf "  DDS/Gazebo/PX4:     /tmp/aerialclaw_dds.log /tmp/aerialclaw_gz.log /tmp/aerialclaw_px4.log\n\n"
printf "Stop this stack:\n"
printf "  kill \$(cat %s) \$(cat %s) 2>/dev/null || true\n" "$SERVER_PID_FILE" "$SIM_PID_FILE"
printf "============================================================\n"
