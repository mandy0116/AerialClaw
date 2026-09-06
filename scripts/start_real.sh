#!/usr/bin/env bash
# Start AerialClaw against the ROS1 Noetic real-vehicle stack.
#
# This script only prepares the process environment and starts server.py.  It
# does not arm, take off, or issue any motion command by itself.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ROS_SETUP="${ROS_SETUP:-/opt/ros/noetic/setup.bash}"
if [[ ! -f "$ROS_SETUP" ]]; then
  echo "ERROR: ROS setup file not found: $ROS_SETUP" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ROS_SETUP"

# Real vehicle defaults discovered on 10.106.167.219:
#   ROS1 photo_function services under /camera
#   SIYI A8 Mini control/video endpoint 192.168.144.25
export GIMBAL_ROS_VERSION="${GIMBAL_ROS_VERSION:-1}"
export GIMBAL_SERVICE_PREFIX="${GIMBAL_SERVICE_PREFIX:-camera}"
export AERIALCLAW_REAL_CAMERA_BRIDGE="${AERIALCLAW_REAL_CAMERA_BRIDGE:-1}"
export REAL_CAMERA_GIMBAL_URL="${REAL_CAMERA_GIMBAL_URL:-rtsp://192.168.144.25:8554/live}"
export SIM_ADAPTER="${SIM_ADAPTER:-mavros}"
export MAVROS_NAMESPACE="${MAVROS_NAMESPACE:-/mavros}"

# Read-only preflight visibility.  Do not fail startup when a node is still
# coming up, but make a missing ROS1 endpoint obvious in the console.
if command -v rosnode >/dev/null 2>&1; then
  if rosnode list 2>/dev/null | grep -qx "$MAVROS_NAMESPACE"; then
    echo "  check:     MAVROS node present ($MAVROS_NAMESPACE)"
  else
    echo "  WARNING:   MAVROS node $MAVROS_NAMESPACE not found (start mavros first)" >&2
  fi
else
  echo "  WARNING:   rosnode not found after sourcing ROS_SETUP" >&2
fi
if command -v rosservice >/dev/null 2>&1; then
  if rosservice list 2>/dev/null | grep -q "^/$GIMBAL_SERVICE_PREFIX/get_connection_status$"; then
    echo "  check:     gimbal ROS1 services present (/$GIMBAL_SERVICE_PREFIX)"
  else
    echo "  WARNING:   gimbal service /$GIMBAL_SERVICE_PREFIX/get_connection_status not found" >&2
  fi
fi

PYTHON="${PYTHON:-$PROJECT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "ERROR: AerialClaw requires Python >=3.10 (set PYTHON to the project venv)." >&2
  exit 1
fi

echo "AerialClaw real-vehicle launcher"
echo "  ROS:       $ROS_DISTRO (version $ROS_VERSION)"
echo "  adapter:   $SIM_ADAPTER"
echo "  MAVROS:    $MAVROS_NAMESPACE"
echo "  gimbal:    ROS1 /$GIMBAL_SERVICE_PREFIX/*"
echo "  camera:    $REAL_CAMERA_GIMBAL_URL"
echo ""
echo "Safety: verify props-off/RC takeover and run a preflight before any flight command."

cd "$PROJECT_DIR"
exec "$PYTHON" server.py
