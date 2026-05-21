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
#   ./scripts/sim_quickstart.sh default x500     # fallback standard PX4 world/model
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
  if [ -x "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/venv/bin/python"
    ok "Using existing venv: $PYTHON"
    return
  fi

  if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
    ok "Using existing .venv: $PYTHON"
    return
  fi

  if [ "$SETUP" = "1" ]; then
    info "Creating Python virtual environment"
    python3 -m venv "$PROJECT_DIR/venv"
    PYTHON="$PROJECT_DIR/venv/bin/python"
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
    ok "Python dependencies installed"
    return
  fi

  PYTHON="$(command -v python3 || true)"
  if [ -z "$PYTHON" ]; then
    err "python3 not found. Install Python >=3.10 or run with --setup after installing Python."
    exit 1
  fi
  warn "No venv/.venv found; using system python: $PYTHON"
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
  (cd "$PROJECT_DIR/ui" && npm install && npm run build)
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

if [ "$SETUP" = "1" ]; then
  info "Running first-time PX4/Gazebo setup"
  "$SCRIPT_DIR/setup_px4.sh"
fi

ensure_python_env
ensure_frontend_build

info "Running preflight doctor"
if ! "$SCRIPT_DIR/doctor_gazebo.sh" "$WORLD" "$MODEL"; then
  err "Preflight doctor found blocking issues."
  echo ""
  echo "First-time setup command:"
  echo "  ./scripts/sim_quickstart.sh --setup"
  echo ""
  echo "Fallback standard PX4 path:"
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
if curl -fsS "$BASE_URL/api/sensor/status" >/tmp/aerialclaw_quickstart_sensor.json 2>/dev/null; then
  ok "Sensor status endpoint reachable"
  cat /tmp/aerialclaw_quickstart_sensor.json
  echo ""
else
  warn "Sensor status endpoint is not ready yet. Open the UI and inspect camera panels after PX4/Gazebo finishes spawning."
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
