#!/usr/bin/env bash
# ============================================================
# AerialClaw — 启动仿真云台桥接节点 (rclpy)
# ============================================================
# 把 photo_function ROS2 云台服务桥接到 Gazebo Transport 关节/变焦命令。
# 仿真时用这个替代真实 photo_function (a8_mini)，AerialClaw 技能代码不变。
#
# 前提: photo_function 已 colcon 构建 (install/setup.bash 存在)。
# 用法: ./scripts/start_gimbal_bridge.sh        # 前台运行
#       ./scripts/start_gimbal_bridge.sh --bg   # 后台运行
# ============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

IFC_PRO_DIR="${IFC_PRO_DIR:-/home/ubuntu/ifc_pro}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
# The bridge is the ROS2 simulation path; the real-vehicle launcher uses
# scripts/start_real.sh and ROS1 Noetic instead.
export GIMBAL_ROS_VERSION=2
export GIMBAL_SERVICE_PREFIX=common/camera

# ── 环境: ROS2 + photo_function srv + gz 绑定需要纯 Python protobuf ──
# ROS2 setup 脚本里有未绑定变量，sourcing 前关掉 set -u
set +u
# shellcheck disable=SC1091
source "$ROS_SETUP"
# shellcheck disable=SC1091
source "$IFC_PRO_DIR/install/setup.bash"
set -u
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

# 用系统 python3.10 (默认能看到 /usr/lib/python3/dist-packages 的 gz 绑定)
PY="${PYTHON_BIN:-python3.10}"

echo "[INFO] gimbal bridge: ROS2=$(rosversion -d 2>/dev/null || echo humble) python=$($PY --version)"
echo "[INFO] 启动 ros2/gimbal_sim_bridge.py (服务在 /common/camera/*, gz topics gimbal/*_cmd)"

if [ "${1:-}" = "--bg" ]; then
  nohup "$PY" "$PROJECT_DIR/ros2/gimbal_sim_bridge.py" >/tmp/aerialclaw_gimbal_bridge.log 2>&1 &
  echo $! > /tmp/aerialclaw_gimbal_bridge.pid
  echo "[OK] 后台启动 PID $(cat /tmp/aerialclaw_gimbal_bridge.pid), 日志 /tmp/aerialclaw_gimbal_bridge.log"
else
  exec "$PY" "$PROJECT_DIR/ros2/gimbal_sim_bridge.py"
fi
