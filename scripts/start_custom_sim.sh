#!/usr/bin/env bash
# ============================================================
# AerialClaw — 自定义飞机/世界 Gazebo 仿真启动器
# ============================================================
# 用你自己的无人机模型和世界在 Gazebo 里跑 PX4 SITL + AerialClaw 后端。
# 复用 sim_quickstart.sh 的全栈编排（含 offload/protobuf 修复 + doctor）。
#
# 用法:
#   ./scripts/start_custom_sim.sh <world> <model>
#   ./scripts/start_custom_sim.sh my_world my_uav
#   ./scripts/start_custom_sim.sh --restart my_world my_uav   # 干净重启
#
# 前提:
#   - 飞机模型放: sim/models/<model>/  (model.sdf + model.config)
#   - 世界文件放: sim/worlds/<world>.sdf
#   本脚本会自动把它们安装到 gz/PX4 能解析的位置（幂等）。
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PX4_DIR="${PX4_DIR:-${PROJECT_DIR}/PX4-Autopilot}"

# 解析 --restart（透传给 sim_quickstart）
RESTART=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --restart) RESTART=1 ;;
    *) ARGS+=("$a") ;;
  esac
done

WORLD="${ARGS[0]:-${PX4_GZ_WORLD:-my_world}}"
MODEL="${ARGS[1]:-${PX4_SIM_MODEL:-my_uav}}"

LOCAL_MODELS="${HOME}/.simulation-gazebo/models"
PX4_MODELS="${PX4_DIR}/Tools/simulation/gz/models"
PX4_WORLDS="${PX4_DIR}/Tools/simulation/gz/worlds"

# ── 安装自定义模型到 gz/PX4 可解析位置 ──────────────────────
install_model() {
  local src="${PROJECT_DIR}/sim/models/${MODEL}"
  if [ ! -d "$src" ] || [ ! -f "${src}/model.sdf" ] || [ ! -f "${src}/model.config" ]; then
    echo "[ERROR] 模型源缺失: ${src}"
    echo "  请把 model.sdf 和 model.config 放到 sim/models/${MODEL}/"
    exit 1
  fi
  mkdir -p "$LOCAL_MODELS"
  rm -rf "${LOCAL_MODELS:?}/${MODEL}"
  cp -r "$src" "${LOCAL_MODELS}/${MODEL}"
  rm -rf "${PX4_MODELS:?}/${MODEL}"
  cp -r "$src" "${PX4_MODELS}/${MODEL}"
  echo "[OK] 模型已安装: ${MODEL}  (→ ${LOCAL_MODELS} 和 ${PX4_MODELS})"
}

# ── 安装自定义世界到 PX4 世界目录 ──────────────────────────
install_world() {
  local src="${PROJECT_DIR}/sim/worlds/${WORLD}.sdf"
  if [ ! -f "$src" ]; then
    echo "[ERROR] 世界源缺失: ${src}"
    echo "  请把世界 SDF 放到 sim/worlds/${WORLD}.sdf"
    exit 1
  fi
  cp "$src" "${PX4_WORLDS}/${WORLD}.sdf"
  echo "[OK] 世界已安装: ${WORLD}  (→ ${PX4_WORLDS})"
}

install_model
install_world

echo "============================================================"
echo " 自定义仿真"
echo " World: ${WORLD}"
echo " Model: ${MODEL}"
echo " UI:    http://127.0.0.1:5001"
echo "============================================================"

cd "$PROJECT_DIR"
if [ "$RESTART" = "1" ]; then
  exec ./scripts/sim_quickstart.sh --restart "$WORLD" "$MODEL"
else
  exec ./scripts/sim_quickstart.sh "$WORLD" "$MODEL"
fi