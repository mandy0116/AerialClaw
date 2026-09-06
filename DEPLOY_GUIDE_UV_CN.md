# AerialClaw 方案三部署指南（UV 保姆版 · 针对本机定制）

> 本指南根据**你这台机器的实际环境**定制，不是通用文档。
> 目标：用 **uv 虚拟环境**跑通 README「方案三：PX4 + Gazebo 完整仿真模式」。
> 适用对象：第一次部署、想要每一步都能照抄的人。
>
> 生成日期：2026-07-23

---

## 0. 你的机器现状（已自动检测）

| 组件 | 现状 | 是否适配方案三 | 说明 |
|---|---|---|---|
| 操作系统 | Ubuntu 22.04.5 LTS (jammy) / 内核 6.8 | ✅ | 官方支持 |
| Python | 系统自带 3.10.12（`/usr/bin/python3.10`） | ✅ | 满足 ≥3.10 |
| CMake | 3.22.1 | ✅ | 满足 ≥3.22 |
| Gazebo | `gz sim` 默认 **8.11.0 (Harmonic)** | ✅ | 项目要求 gz sim 8.x，正好命中 |
| Gazebo Python 绑定 | `gz.transport13` / `gz.msgs10` 已装 | ✅ | 但 **编译为 cpython-310**，只能在 Python 3.10 下导入 |
| PX4 Autopilot | 已在 `/home/ubuntu/TASK/PX4-Autopilot`，main 分支，**SITL 二进制已编译** | ⚠️ 路径不对 | 脚本默认去 `AerialClaw/PX4-Autopilot` 找，需做软链接 |
| Micro XRCE-DDS Agent | 已装 `/usr/local/bin/MicroXRCEAgent` | ✅ | 免重装 |
| MAVSDK (Python) | 未安装 | ⏳ 待装 | 装进 uv 环境即可 |
| 自定义模型/世界 | `sim/models/x500_lidar_2d_cam`、`sim/worlds/urban_rescue.sdf` 在仓库里有，**但还没安装到 Gazebo/PX4 目录** | ⏳ 待装 | 需跑一次 `setup_px4.sh` 的安装步骤 |
| GPU | NVIDIA RTX 5060 Laptop / 驱动 580.142 | ✅ | Gazebo ogre2 渲染无压力 |
| uv | 0.10.10 已装 | ✅ | |
| Node/npm | node v24.15.0 / npm 11.12.1 | ✅ | 前端构建可用 |

### 三个关键结论（决定后续每一步）

1. **uv 环境必须用 Python 3.10 + `--system-site-packages`**
   你系统里的 gz 绑定是 `_transport.cpython-310-x86_64-linux-gnu.so` 这种**编译扩展**，只能被 Python 3.10 导入。如果 uv 用 3.11/3.12，就算开 `--system-site-packages` 也加载不了，摄像头面板会 `NO SIGNAL`。你系统也只有 3.10，所以没得选，正好匹配。

2. **PX4 要软链接进项目目录**
   你的 PX4 在 `/home/ubuntu/TASK/PX4-Autopilot`，但 `sim_quickstart.sh` 第 428 行硬编码检查 `AerialClaw/PX4-Autopilot`，`setup_px4.sh` 也默认在这里 clone。最省事的做法是建一个软链接，所有脚本立刻就能用，且不会重复 clone/编译。

3. **Garden + Harmonic 双版本共存，但默认是 Harmonic，没问题**
   你机器上 gz-sim7(Garden) 和 gz-sim8(Harmonic) 都装了，`gz sim --version` 解析到 8.11.0，正是项目要的。不用动它们，但要知道这件事，排障时别找错版本。

---

## 1. 总体流程（先看全貌，再一步步做）

```
① 软链接 PX4  →  ② 建 uv 环境(3.10)  →  ③ 装 AerialClaw Python 依赖
④ 跑 setup_px4.sh(只装模型/世界，跳过编译)  →  ⑤ 构建前端
⑥ 配置 .env(可选,LLM)  →  ⑦ 启动  →  ⑧ 验证
```

预计耗时：①②③⑤⑥ 约 10 分钟；④ 主要是下载 PX4-gazebo-models，看网速 5–15 分钟；首次启动 Gazebo 加载模型 1–2 分钟。PX4 不需要重新编译（你已编好）。

---

## 2. 保姆级步骤

### 步骤 ①  把 PX4 软链接进项目

```bash
cd /home/ubuntu/AerialClaw
ln -s /home/ubuntu/TASK/PX4-Autopilot PX4-Autopilot
```

验证：
```bash
ls -l PX4-Autopilot
# 应显示: PX4-Autopilot -> /home/ubuntu/TASK/PX4-Autopilot
ls PX4-Autopilot/build/px4_sitl_default/bin/px4
# 应显示该二进制文件，说明链接生效
```

> 为什么不直接改脚本？脚本支持 `PX4_DIR` 环境变量（`start_sim.sh`、`doctor_gazebo.sh` 都认），但 `sim_quickstart.sh` 第 428 行有一处硬编码检查 `$PROJECT_DIR/PX4-Autopilot`，软链接是唯一能让**所有**脚本都不改就工作的方式。

### 步骤 ②  创建 uv 虚拟环境（关键三参数）

```bash
cd /home/ubuntu/AerialClaw
uv venv --python 3.10 --system-site-packages --seed
```

三个参数缺一不可：
- `--python 3.10`：匹配 gz 绑定的 cpython-310
- `--system-site-packages`：让 venv 看到系统的 `gz.transport13`/`gz.msgs10`
- `--seed`：注入 pip/setuptools/wheel（项目脚本用 `python -m pip install`，没 pip 会失败）

激活环境：
```bash
source .venv/bin/activate
```

验证环境正确：
```bash
python --version
# Python 3.10.x

python -c "import gz.transport13, gz.msgs10.image_pb2; print('gz 绑定 OK')"
# 应输出: gz 绑定 OK    ← 这一行通过，摄像头桥接才有戏
```

> ⚠️ 如果上面 `gz 绑定 OK` 没打印出来，说明 `--system-site-packages` 没生效或环境建错 Python 版本，**必须删掉重建**：`deactivate && rm -rf .venv`，回到步骤 ② 重来。

### 步骤 ③  安装 AerialClaw 的 Python 依赖

```bash
cd /home/ubuntu/AerialClaw
uv pip install -r requirements.txt
uv pip install pytest
```

验证关键依赖能导入：
```bash
python -c "import flask, flask_socketio, flask_cors, mavsdk, cv2; print('后端依赖 OK')"
# 应输出: 后端依赖 OK
```

> `requirements.txt` 已把 `numpy<2`、`opencv-python-headless==4.10.0.84` 锁好，和 PX4/symforce 兼容，别手动升级 numpy 到 2.x。

### 步骤 ④  安装自定义模型 + 世界（跑 setup_px4.sh）

由于你 PX4 已存在（软链接）、二进制已编译、XRCE Agent 已装，`setup_px4.sh` 会**自动跳过** clone/编译/XRCE，只做我们需要的：下载 PX4-gazebo-models、安装 `x500_lidar_2d_cam` 模型、安装 `urban_rescue` 世界、补装 PX4 Python 构建依赖、跑 doctor。

```bash
cd /home/ubuntu/AerialClaw
# 确保还在 .venv 激活状态
source .venv/bin/activate
./scripts/setup_px4.sh
```

脚本会复用你 `.venv`（它探测到 `.venv/bin/python` 且版本 ≥3.10 就直接用，不会重建覆盖你的 uv 环境）。

> 注意：这一步会往 `.venv` 里装 PX4 构建用的 `numpy<2`、`symforce>=0.10,<0.11` 等，和步骤 ③ 的依赖共存，没问题。
>
> 如果脚本中途尝试 clone PX4（说明软链接没建好），按 Ctrl+C，回步骤 ① 检查 `PX4-Autopilot` 软链接。

验证模型/世界已就位：
```bash
ls ~/.simulation-gazebo/models/x500_lidar_2d_cam/model.sdf
# 应存在

ls PX4-Autopilot/Tools/simulation/gz/worlds/urban_rescue.sdf
# 应存在（被 setup 脚本从 sim/worlds 拷过去）
```

### 步骤 ⑤  构建前端（Web UI）

```bash
cd /home/ubuntu/AerialClaw/ui
npm install --no-audit --no-fund
npm run build
cd ..
```

验证：
```bash
ls ui/dist/index.html
# 应存在
```

### 步骤 ⑥  配置 LLM（可选，但要 AI 自主飞行就必须配）

```bash
cd /home/ubuntu/AerialClaw
cp .env.example .env
```

编辑 `.env`。两种主推方案，**本机只有 Ollama 就用方案 B**（纯本地、零成本、无需 API key）。

#### 方案 A：云端 OpenAI 兼容服务（OpenAI / DeepSeek / Moonshot / 智谱）

```dotenv
ACTIVE_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-你的key
LLM_MODEL=gpt-4o
VLM_BASE_URL=https://api.openai.com/v1
VLM_API_KEY=sk-你的vlm-key
VLM_MODEL=gpt-4o
```

#### 方案 B：本地 Ollama（本机采用，RTX 5060 8GB 显存）

**关键认知**：AerialClaw 有两个模型角色——LLM（规划/工具调用，走 `ACTIVE_PROVIDER`）和 VLM（看摄像头画面，是**独立**的 `vlm` provider，**默认指 OpenAI**）。所以**光设 `ACTIVE_PROVIDER=ollama_local` 不够**，必须把 `VLM_*` 也指到 Ollama，否则一切 AI 模式调视觉就报 401/连接 OpenAI 失败。

1) 装 Ollama（自动起 systemd 服务，自动用 NVIDIA GPU）：
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
systemctl status ollama --no-pager
```
> 装卡就开代理 `export https_proxy=http://127.0.0.1:7897` 重跑。RTX 5060 是 Blackwell，务必装最新版 Ollama。

2) 拉模型（8GB 显存选型：语言用 qwen2.5:7b 支持工具调用，视觉用 qwen2.5-vl:7b）：
```bash
ollama pull qwen2.5:7b        # LLM
ollama pull qwen2.5-vl:7b     # VLM
```
> 两个 7b 同时驻留约 10GB > 8GB，Ollama 会自动换页（不崩，切换时多几秒）。想减少延迟设 `OLLAMA_KEEP_ALIVE=0`。显存真爆就改 LLM 为 `qwen2.5:3b`（3b+vl7b 能同驻 8GB）。

3) `.env` 配成：
```dotenv
ACTIVE_PROVIDER=ollama_local
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=qwen2.5:7b
# VLM 必须也指到 Ollama，否则视觉分析去找 OpenAI 失败
VLM_BASE_URL=http://127.0.0.1:11434/v1
VLM_API_KEY=ollama-local
VLM_MODEL=qwen2.5-vl:7b
SIM_ADAPTER=px4
```

4) 自测模型可用：
```bash
ollama run qwen2.5:7b "用一句话介绍你自己"
ollama run qwen2.5-vl:7b "描述这张图" /path/to/some.jpg
```

> 只做 smoke 测试、用 manual/mock 控制，可跳过 LLM。但方案三核心卖点是「自然语言自主飞行」，建议配上。详细见 `docs/LLM_CONFIG.md`。

### 步骤 ⑦  一键启动完整仿真栈

```bash
cd /home/ubuntu/AerialClaw
source .venv/bin/activate
./scripts/sim_quickstart.sh
```

> ⚠️ **不要用 `--setup`**，`--setup` 是首次装环境用的（步骤 ④ 已等效完成）。直接跑无参数版本即可启动。如果之前跑过还活着，想干净重启用 `./scripts/sim_quickstart.sh --restart`。
>
> 脚本会依次：启动 MicroXRCEAgent → Gazebo 服务器 → PX4 SITL → 等待 MAVSDK 控制链路 → 启动 AerialClaw 后端 → 健康检查。首次启动 Gazebo 加载模型要 1–2 分钟，耐心等 `OK` 行。

浏览器打开：
```
http://localhost:5001
```

### 步骤 ⑧  验证（按顺序确认每一层都通）

**浏览器侧：**
1. 点 **「⚡ 初始化系统」**
2. 看 cockpit/摄像头面板：前/后/左/右/下五路 + LiDAR 应有画面，不是 `NO SIGNAL`
3. 配了 LLM 的话，右上角切到 **「🤖 AI」** 模式
4. 试一句：`起飞至1.5米高度并观察周围环境`

**命令行侧（另开终端）：**
```bash
# 后端存活
curl -s http://localhost:5001/api/status

# 控制适配器必须是 px4 且 connected，否则电机指令没接 PX4
curl -s http://localhost:5001/api/adapter/status
# 期望: {"adapter":"px4","connected":true}

# 传感器桥接在跑、5 路相机 + LiDAR、frame_count 在涨
curl -s http://localhost:5001/api/sensor/status

# 摄像头 HTTP 端点返回 JPEG
curl -fsS http://localhost:5001/api/sensor/camera -o /tmp/cam.jpg && file /tmp/cam.jpg
# 期望: JPEG image data

# 实时诊断 Gazebo topic
./scripts/doctor_gazebo.sh urban_rescue x500_lidar_2d_cam --live
```

全部通过 = 部署成功 🎉

---

## 3. 排障速查（按现象对症）

### 现象 A：摄像头/LiDAR 面板 `NO SIGNAL`
最常见，99% 是 gz Python 绑定没被后端进程导入。
```bash
# 在 .venv 激活状态下
python -c "import gz.transport13, gz.msgs10.image_pb2; print('OK')"
```
- 报错 → uv 环境不是 3.10 或没加 `--system-site-packages`，删 `.venv` 重做步骤 ②。
- OK 但面板还是 NO SIGNAL → 手动指认绑定路径再启动：
  ```bash
  export GZ_PYTHONPATH=/usr/lib/python3/dist-packages
  ./scripts/sim_quickstart.sh --restart
  ```
- `/api/sensor/camera` 返回 500 且日志有 `ModuleNotFoundError: cv2` → `uv pip install opencv-python-headless==4.10.0.84`（别升 numpy 到 2.x）。

### 现象 B：UI 连上了但无人机不动
```bash
curl -s http://localhost:5001/api/adapter/status
```
- 显示 `mock` 或 `connected:false` → 控制链路没接上。`--restart` 重启；仍不行查 MAVSDK 端口：
  ```bash
  lsof -i :14540
  ```
  被占用就杀掉旧进程：`pkill -f mavsdk_server`。
- 解锁后 10 秒内必须发起飞指令，否则 PX4 自动 disarm（`COM_DISARM_PRFLT=10`）。

### 现象 C：`setup_px4.sh` 报 PX4 要重新 clone
说明步骤 ① 软链接没生效或 PX4 目录被误判。确认：
```bash
ls -ld /home/ubuntu/AerialClaw/PX4-Autopilot
readlink -f /home/ubuntu/AerialClaw/PX4-Autopilot
# 应指向 /home/ubuntu/TASK/PX4-Autopilot
```

### 现象 D：Gazebo 起不来 / 渲染黑屏
- 你有 NVIDIA RTX 5060 + 驱动 580，默认用 ogre2，一般没问题。
- 远程/无显示环境：`export START_GAZEBO_GUI=0` 用 headless，只看 Web UI。
- 详细日志：脚本日志在 `/tmp/aerialclaw_full_sim_launcher.log`、`/tmp/aerialclaw_full_server.log`、`/tmp/aerialclaw_gz_gui.log`，先 `tail -160` 这些。

### 现象 E：doctor 报 `python module 'mavsdk' missing`，但 pip 明明装了
这是本机特有的 **protobuf 版本冲突**，不是 mavsdk 没装：
- apt 的 gz Python 绑定按 protobuf <3.19 生成（系统是 3.12.4）
- pip 的 mavsdk 3.x 要 protobuf ≥6.32（venv 里是 7.35.1）
- C++ protobuf 实现下二者无法共存；`sim_quickstart` 为让 gz 可见会把 `PYTHONPATH` 指向系统 dist-packages，反而用旧 protobuf 把 mavsdk 顶挂。

**解法**：强制纯 Python protobuf 实现（绕过 C++ 描述符检查）。本指南部署时已在 `.env`、`scripts/sim_quickstart.sh`、`scripts/doctor_gazebo.sh` 三处写入：
```dotenv
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
```
若仍复现，手动确认变量已导出：
```bash
echo $PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION   # 应为 python
# 临时补: export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
```
代价：纯 Python protobuf 解析稍慢，摄像头帧可能有轻微延迟，但功能完整。验证：
```bash
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python python -c "import gz.transport13, gz.msgs10.image_pb2, mavsdk; print('共存 OK')"
```

### 现象 F：摄像头/LiDAR `frame_count=0`（topic 存在但没帧）
本机是**混合显卡笔记本**（AMD Radeon 核显接显示 + NVIDIA RTX 5060 独显，`prime-select on-demand`）。gz 传感器渲染默认走显示核显的 Mesa EGL，报 `libEGL warning: egl: failed to create dri2 screen`，导致所有 GPU 传感器（摄像头 + gpu_lidar）topic 已发布但**0 帧**；非渲染 topic（pose/clock）正常。

诊断：
```bash
xrandr --listproviders   # 看到 AMD + NVIDIA 两个 provider = 混合显卡
cat /tmp/aerialclaw_gz_gui.log   # 若有 "egl: failed to create dri2 screen" 即中招
timeout 5 gz topic -e -t /world/urban_rescue/model/x500_lidar_2d_cam_0/link/cam_front_link/sensor/cam_front/image -n 1
# 超时无输出 = 没出帧
```

**解法**：强制 gz 走 NVIDIA 独显（PRIME offload）。本指南部署时已在 `scripts/sim_quickstart.sh` 和 `scripts/start_sim.sh` 顶部写入：
```bash
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia
export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json
```
（用 `GZ_FORCE_NVIDIA_OFFLOAD=0 ./scripts/sim_quickstart.sh` 可关掉。）改完需 `--restart` 重启整栈才生效。

### 现象 G：gz 日志报 `Unable to find uri[.../PX4-Autopilot/Tools/simulation/gz/models/x500_lidar_2d_cam/model.sdf]`
PX4 按 `PX4_GZ_MODELS`（PX4 模型目录）找自定义模型，但 `setup_px4.sh` 把模型装到了 `~/.simulation-gazebo/models`。虽然 Gazebo 能经 `GZ_SIM_RESOURCE_PATH` 兜底加载（topic 能出现），但补一份到 PX4 模型目录可消除报错：
```bash
cp -r sim/models/x500_lidar_2d_cam PX4-Autopilot/Tools/simulation/gz/models/
```

### 现象 E：双 Gazebo 版本混淆
你同时装了 Garden(7) 和 Harmonic(8)。正常情况 `gz sim --version` 是 8.11.0 就行，别动。**只有**当 doctor 报版本不对、或 PX4 启动报 gz 库 ABI 不匹配时，才需要确认 PX4 编译时链的是哪个版本——但你的二进制 7 月 13 日已编好且能用，基本不用管。

### 现象 F：磁盘被 PX4 日志撑爆
脚本默认关掉 PX4 ULog 持久化并清旧 `.ulg`。如果手动跑过 PX4 想清理：
```bash
find PX4-Autopilot/build -type f -name '*.ulg' -delete
```

---

## 4. 日常使用速记

| 场景 | 命令 |
|---|---|
| 正常启动 | `source .venv/bin/activate && ./scripts/sim_quickstart.sh` |
| 干净重启 | `./scripts/sim_quickstart.sh --restart` |
| 只读体检(不启动) | `./scripts/doctor_gazebo.sh urban_rescue x500_lidar_2d_cam` |
| 控制调试兜底(非展示) | `./scripts/sim_quickstart.sh default x500` |
| 停掉整个栈 | `pkill -f "bin/px4"; pkill -f "gz sim"; pkill -f MicroXRCEAgent` |

> `default x500` 只是验证飞控链路，**不是**方案三的研究展示。完整展示必须用 `urban_rescue` + `x500_lidar_2d_cam`。

---

## 5. 与官方文档的对应关系

- 通用流程：`README_CN.md` 第 3 节 / `docs/SIMULATION_SETUP.md`
- 本指南的差异点（针对你本机）：
  1. 用 uv 代替 `python3 -m venv`，且强制 3.10 + `--system-site-packages` + `--seed`
  2. PX4 不在项目内，多了一步软链接
  3. PX4 已编译，跳过最耗时的 `make px4_sitl_default`
  4. XRCE Agent 已装，跳过其编译安装
- LLM 详细配置：`docs/LLM_CONFIG.md`
- 架构与传感器桥接原理：`docs/SIMULATION_SETUP.md` 的「Sensor Configuration」「Manual Start」两节

---

# 第二部分：Sim2Real 实机部署（Jetson NX + PX4 真机 + SIYI A8 Mini）

> 目标：把 AerialClaw 从 Gazebo 仿真迁到真机 —— Jetson Xavier/Orin NX 上跑 `server.py`，通过串口控制真实 PX4 飞控，用真实 SIYI A8 Mini 云台相机。
> 适用对象：仿真已跑通、要把同一套代码搬到无人机伴飞电脑上做实机的人。
> 生成日期：2026-07-27
>
> **本部分针对的机器是无人机上的 NX（用户 `nvidia`，家目录 `/home/nvidia`），不是第一部分那台开发/仿真机。** 凡是命令，都会标【在哪台机器上跑】。

---

## S0. 实机 vs 仿真：什么不变、什么要换（先建立认知）

| 环节 | 仿真（第一部分） | 实机（本部分） | 处理 |
|---|---|---|---|
| 飞控 | PX4 SITL（`udp://:14540`） | 真实 Pixhawk，ROS1 Noetic + MAVROS（串口由 MAVROS 独占） | `SIM_ADAPTER=mavros`，代码通过 `/mavros` 控制 |
| Gazebo / PX4-Autopilot 源码 / MicroXRCEAgent | 必需 | **不需要** | 实机不跑仿真，这三样在 NX 上不装 |
| GPU 渲染（PRIME offload） | 必需（相机/gpu_lidar 渲染） | **不需要** | 真机相机是真实视频流，不渲染；NX 有没有独显都行 |
| 传感器（IMU/GPS/mag） | gz 传感器 | 飞控真实传感器，经 MAVLink | `px4_adapter` 遥测照常工作，不用 gz |
| 相机画面 | `gz_sensor_bridge`（Gazebo topic） | SIYI 真实视频流 | **缺口**：需写 `RealSensorBridge`（见 S7） |
| 云台 | `ros2/gimbal_sim_bridge.py`（假桥） | 真实 `photo_function` 节点（a8_mini 后端） | 换节点，`gimbal_control` 技能代码不变 |
| LLM/VLM | 云端 glm/deepseek | 同（NX 需联网） | 配置文件手动拷（gitignore 了） |
| 安全 | 无所谓 | 真桨、必须 failsafe/RC 接管 | **S9 整节必读** |
| GPS 精度 | cm 级 | ±2-3m（无 RTK） | `fly_to` 会有米级偏差，见 S5 注 |

**一句话**：飞控和云台几乎"改个连接串/换个节点"就能上；相机可视化是唯一需要补代码的缺口；安全是新增的硬性要求。

---

## S1. 硬件清单与接线

| 部件 | 连到 NX 的方式 | 备注 |
|---|---|---|
| PX4 飞控（Pixhawk，固件推荐 **v1.15.4**） | UART → `/dev/ttyTHS0`（由 MAVROS 连接） | MAVROS `fcu_url=/dev/ttyTHS0:921600`，波特率按实际配置 |
| SIYI A8 Mini 云台相机 | 以太网（`192.168.144.25`） | ROS1 `photo_function` 提供 `/camera/*` 服务；视频 RTSP 8554 |
| RC 接收机 → 飞控 | 接飞控 RC 口 | **手动接管通道必配**，软件挂了能手动飞 |
| NX 电源 / 飞控电池 | 各自供电 | 共地 |

> ⚠️ 飞控固件版本：项目针对 **PX4 v1.15.4**，开发机仿真用的是 main（v1.17-alpha1），已逐个绕过 main 的不兼容。**实机飞控固件建议统一刷 v1.15.4**，避免参数/API 差异。若用 main 固件，需带上本会话对 start_sim/世界/模型的修复，但实机不跑 gz，多数修复不相关。

### 先在 NX 上确认硬件可见（已为你跑过，结论见下）

```bash
# 【NX】
ls -l /dev/ttyACM* /dev/ttyTHS* /dev/ttyUSB* 2>/dev/null   # 飞控/相机串口
ip addr | grep -E "192.168.144|usb"                        # SIYI 网口
ls /opt/ros/noetic/setup.bash                              # ROS1
rosnode list | grep /mavros                                  # MAVROS
rosservice list | grep '^/camera/'                          # 真机 photo_function
```

**你这次实测结论**：Ubuntu 20.04 + ROS1 Noetic ✅；MAVROS 已使用
`/dev/ttyTHS0:921600`，`/mavros/state.connected=true`；A8 Mini 服务在
`/camera/*`，设备地址 `192.168.144.25`，RTSP `8554/live`。因此 S5/S6 均按
ROS1 执行，不再使用旧的 ROS2/`ifc_pro` 步骤。

---

## S2. NX 环境准备

**需要装的**：Ubuntu 20.04 + Python 3.10（系统自带）+ ROS1 Noetic（已装）。
**不需要装的**（仿真专属，实机装了也是浪费）：Gazebo、PX4-Autopilot 源码、MicroXRCEAgent、NVIDIA PRIME offload 那套。

串口权限（飞控 `ttyTHS0` 是 `root:dialout`，运行用户要在 dialout 组里）：

```bash
# 【NX】
id | grep dialout
# 不在就加，加完必须注销重登（或 newgrp dialout）：
sudo usermod -aG dialout $USER
```

---

## S3. 同步代码 + 配置到 NX

代码用 rsync 从开发机传，**排除仿真专属的大目录**（在开发机上跑）：

```bash
# 【开发机】
rsync -avz --progress \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='PX4-Autopilot' \
  --exclude='ui/node_modules' \
  --exclude='logs' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  /home/ubuntu/AerialClaw/ nvidia@<NX的IP>:~/AerialClaw/
```

> 排除 `PX4-Autopilot`：实机不跑 SITL，这个几 GB 的编译产物不需要。
> 排除 `.venv`：x86 的 venv 在 arm64 NX 上用不了，S4 重建。
> `ui/dist` **不排除**：直接用构建好的前端，NX 上不用 npm build。

**两个 gitignore 配置文件必须单独拷**（rsync 默认会传，但要确认；若用 git clone 则不会跟过去）：

```bash
# 【开发机】—— 含 glm token，没它 planner 直接 401
scp .env .aerialclaw_llm_config.json nvidia@<NX的IP>:~/AerialClaw/
```

```bash
# 【NX】确认到位
ls -l ~/AerialClaw/.env ~/AerialClaw/.aerialclaw_llm_config.json
```

真机 photo_function 已作为 ROS1 Noetic 软件包安装在目标机，无需同步或构建旧的
ROS2 `ifc_pro` 工作区。

---

## S4. 建虚拟环境 + 装依赖（NX 上）

真机使用 Python 3.10 + `--system-site-packages`，以便导入 ROS1 Noetic 的系统绑定。

```bash
# 【NX】
cd ~/AerialClaw
# 确认系统 3.10
python3.10 --version

# 用绝对路径指定解释器，uv 不会再去镜像下载
uv venv --python /usr/bin/python3.10 --system-site-packages .venv
# 若 uv 仍卡镜像，改用系统 venv 完全绕开 uv：
#   sudo apt install -y python3.10-venv
#   python3.10 -m venv .venv --system-site-packages

# 装依赖
uv pip install -r requirements.txt
# uv pip 也走镜像失败的话：
#   .venv/bin/pip install -r requirements.txt
```

验证：

```bash
# 【NX】
source .venv/bin/activate
python -c "import flask, flask_socketio, flask_cors, mavsdk, cv2; print('后端依赖 OK')"
python -c "import rospy, mavros_msgs; print('ROS1 Noetic Python bindings OK')"
```

> 若 NX 外网整体受限（连 pypi.org 都不通），在开发机离线打包再传：
> ```bash
> # 【开发机】pip download -r requirements.txt -d /tmp/pkgs && rsync /tmp/pkgs nvidia@<IP>:/tmp/pkgs
> # 【NX】.venv/bin/pip install --no-index --find-links=/tmp/pkgs -r requirements.txt
> ```

---

## S5. 连接飞控 PX4（ROS1/MAVROS，核心，先跑通这条）

> 本机真机控制统一走 ROS1 Noetic + MAVROS。旧版 `PX4_MAVSDK_URL`、
> `SIM_ADAPTER=px4` 串口示例不适用于 `10.106.167.219`；请使用
> `/mavros/state` 和 `SIM_ADAPTER=mavros`。

真机上 MAVROS 节点已经持有飞控串口，AerialClaw 的 `MavrosAdapter` 只订阅/发布
ROS1 话题和服务，不会再次打开 UART。

```bash
# 【NX】拆桨状态下启动
cd ~/AerialClaw
source .venv/bin/activate
export SIM_ADAPTER=mavros
export MAVROS_NAMESPACE=/mavros
# 关掉仿真专属的 gz 传感器桥（实机没 Gazebo）
export AERIALCLAW_FORCE_GZ_SENSOR_BRIDGE=0
.venv/bin/python server.py
```

验证飞控连上：

```bash
# 【NX】另开终端
curl -s http://localhost:5001/api/adapter/status
# 期望: {"adapter":"mavros","connected":true, "state":{"armed":false,"in_air":false,...}}
```

- `connected:true` 但 `armed` 一直 false → 看飞控是否有 GPS fix、preflight 检查是否通过（PX4 `COM_DISARM_PRFLT` 等参数）。
- `connected:false` → 检查 MAVROS 的 `fcu_url`、波特率和 `/mavros/state`；或 `dmesg | grep tty` 确认串口枚举。
- 权限拒绝（`Permission denied: /dev/ttyTHS0`）→ S2 的 dialout 组没生效，重新登录。

> ⚠️ **GPS 精度提示**：`fly_to_ned` 用 GPS 转 NED，真实 GPS（无 RTK）误差 ±2-3m，仿真是 cm 级。所以"向东飞 30 米"实机可能落在 27-33 米。要更准需 RTK 或光流。LLM agent 的"到位"判断也要容忍这个误差。

> ⚠️ **第一次只做地面测试**：拆桨。在网页 manual 模式点 arm/disarm，听电机响应音；再点 takeoff（拆桨时电机空转），立刻 stop_execution 看能否停住。**确认 stop 能停再上桨**。

---

## S6. 云台 SIYI A8 Mini + 真机 photo_function 节点

仿真用 `ros2/gimbal_sim_bridge.py` 当假桥；真机换**真实 `photo_function` 节点**（a8_mini 后端直连 SIYI 实物）。真机 `gimbal_control` 技能默认走 ROS1 `/camera/*` 服务。

### 1) 启动已安装的 ROS1 photo_function 节点

```bash
# 【NX】
source /opt/ros/noetic/setup.bash
rosrun photo_function a8_mini_service_node
```

### 2) 连通 SIYI A8 Mini

SIYI A8 Mini 当前实测 IP 为 `192.168.144.25`。NX 的以太网口要配同网段：

```bash
# 【NX】把连 SIYI 的那个网口配静态 IP（接口名按实际，如 eth0/usb0）
sudo ip addr add 192.168.144.10/24 dev <接口名>
ping 192.168.144.25              # 要通
```

> 视频流地址为 `rtsp://192.168.144.25:8554/live`，S7 相机桥使用该地址。

### 3) 启动真机 photo_function 节点（替代 sim_bridge）

```bash
# 【NX】
source /opt/ros/noetic/setup.bash
rosrun photo_function a8_mini_service_node
# 验证服务在
rosservice list | grep '^/camera/'
# 期望看到 set_angle / manual_zoom / get_current_zoom / get_attitude ...
```

### 4) 真机 zoom 语义差异（重要）

仿真桥 `manual_zoom` 每步 0.5x；**真机是连续变焦**，`direction:1` 开始拉近、`direction:0` 停。当前 `gimbal_skill.py` 的 `zoom_in/out` 是"调 N 次 ManualZoom(direction:1) 再调一次 direction:0"——在真机上这相当于"拉近持续 N 次调用时长再停"，步数和倍率不是线性关系。**上真机前要实测校准** `ZOOM_STEP_X`（`gimbal_skill.py:26`）和 `zoom_in` 循环逻辑，或改用按目标倍率控制的方式。先在地面手动测：调一次 `manual_zoom direction:1` 持续 1 秒能放大多少倍，据此调参。

---

## S7. 相机画面可视化（已实现）

`sim/gz_sensor_bridge.py` 是 Gazebo 专用（订阅 gz transport topic），真机上没有 Gazebo，前端 `sensor_cameras`（前/后/左/右/下/云台）会没源。已新增 **`sim/real_sensor_bridge.py`**，实现和 `GzSensorBridge` 相同的接口（`start/is_running/get_camera_image/get_camera_info/get_lidar_scan/get_lidar_info/get_status`），从 SIYI 真实视频流（RTSP）抓帧，每路一个独立线程保留最新帧 + 断流自动重连。`server.py` 已接入：`AERIALCLAW_REAL_CAMERA_BRIDGE=1` 时 `_init_bridge` 改用 `RealSensorBridge`，`_try_connect_adapter` 据此触发 `_start_sensor_bridge()`。

### 要实现的接口（`server.py` 调用的那几个）

```python
class RealSensorBridge:
    is_running: bool
    def get_camera_image(self, direction="front") -> np.ndarray | None  # 返回 BGR 帧
    def get_camera_info(self, direction="front") -> dict                 # {width,height,fps}
    def get_lidar_scan(self) -> dict | None                              # 真机若无 2D 雷达可返回 None
    def get_lidar_info(self) -> dict
    def get_status(self) -> dict
```

### 最小骨架（SIYI RTSP → JPEG）

```python
# sim/real_camera_bridge.py （新建）
import cv2, threading, time, numpy as np

class RealSensorBridge:
    # 实机一般只有一个云台相机；其余方位可用同一流或留空
    STREAMS = {
        "gimbal": "rtsp://192.168.144.25:8554/live",
        # "front": "rtsp://...",  # 若有其它相机再填
    }
    def __init__(self):
        self._caps, self._frames, self._info, self._stop = {}, {}, {}, False
        for d, url in self.STREAMS.items():
            c = cv2.VideoCapture(url)
            self._caps[d] = c
            self._frames[d] = None
            self._info[d] = {"width": 0, "height": 0, "fps": 0.0}
        self.is_running = True
        threading.Thread(target=self._loop, daemon=True).start()
    def _loop(self):
        while not self._stop:
            for d, c in self._caps.items():
                ok, f = c.read()
                if ok:
                    self._frames[d] = f
                    self._info[d] = {"width": f.shape[1], "height": f.shape[0], "fps": 15.0}
            time.sleep(0.05)   # ~20fps
    def get_camera_image(self, direction="gimbal"):
        return self._frames.get(direction)
    def get_camera_info(self, direction="gimbal"):
        return self._info.get(direction, {"width":0,"height":0,"fps":0.0})
    def get_lidar_scan(self): return None
    def get_lidar_info(self): return {"fps": 0.0}
    def get_status(self):
        return {"running": self.is_running,
                "cameras": {d: {"direction": d, **self._info[d]} for d in self._caps}}
```

### 接进 `server.py`

`server.py` 的 `_start_sensor_bridge` 已改：`AERIALCLAW_REAL_CAMERA_BRIDGE=1` 时起 `RealSensorBridge`，`_try_connect_adapter` 也据此触发（无需 `SIM_ADAPTER=px4`，配 `SIM_ADAPTER=mock` 即可，适合不飞只测云台）。`_start_sensor_stream` 不用改 —— 它只调桥的 `get_camera_image/get_camera_info`，真机桥和 gz 桥接口一致；未配置的方向（front/rear/...）返回 None，前端显示 NO SIGNAL，只有 gimbal 出画面。

### 启用（云台测试，不飞）

```bash
# 【NX】起 server.py 的终端（不要 source ifc_pro，避免 protobuf 冲突）
cd ~/AerialClaw && source .venv/bin/activate
export IFC_PRO_DIR=/home/nvidia/ifc_pro                  # gimbal_skill 子进程要用
export SIM_ADAPTER=mock                                   # 不连飞控
export AERIALCLAW_REAL_CAMERA_BRIDGE=1                    # 用真机相机桥
# SIYI RTSP 地址若非默认再覆盖：
# export REAL_CAMERA_GIMBAL_URL=rtsp://192.168.144.25:8554/live
.venv/bin/python server.py
```

云台控制节点另开终端起（source ROS1 Noetic）：`rosrun photo_function a8_mini_service_node`。

### 前置检查

```bash
# 【NX】opencv 带 FFMPEG 才能抓 RTSP
python -c "import cv2; print(cv2.getBuildInformation())" | grep -i FFMPEG
# 期望: FFMPEG: YES。若 NO，opencv-python-headless 不带 ffmpeg，需换带 ffmpeg 的构建或用 gst 管道。
```

### 验证

- `curl -s http://<NX>:5001/api/sensor/status` → `running:true`、`cameras.gimbal.frame_count` 在涨。
- 网页云台画面格（◎ GIMBAL / ◎ 云台）出真实视频，不是 NO SIGNAL。
- `gimbal_control` 转云台时，画面应同步转动（SIYI 视频流跟随云台）。

### 暂时跳过可视化

如果先不补相机桥，飞控 + 云台控制 + LLM agent 照常工作，只是 UI 看不到画面。建议先把飞控跑通，相机可视化随后再补。

---

## S8. LLM/VLM 配置

**LLM（规划）**：配置文件已在 S3 拷到 NX（`.aerialclaw_llm_config.json` 含 glm token）。确认：

```bash
# 【NX】
curl -s http://localhost:5001/api/llm/config | python3 -m json.tool | head
# 期望 active_provider=glm，deepseek/glm 都在
```

- glm token 与 Claude Code 会话共享额度、**可能过期**。401 了就回开发机重取 token 更新 `.aerialclaw_llm_config.json`，或切 `deepseek`（`curl -X PUT /api/llm/active -d '{"provider":"deepseek"}'`）。
- NX 若联网不稳/受限，可跑本地 Ollama（arm64 有构建）：`ollama pull qwen2.5:7b`，`.env` 设 `ACTIVE_PROVIDER=ollama_local`。Xavier NX 8GB 跑 7b 紧（Orin NX 16GB 更稳），建议用 `qwen2.5:3b`。

**VLM（视觉，"观察/拍照分析"用）**：当前 VLM 走 `deepseek-v4-flash`（**纯文本、无视觉**）。实机若要让 agent 真的"看"画面（observe/scan_area 技能），必须配视觉模型：
- 云端 vision API（gpt-4o / 智谱 glmv / 通义 qwen-vl），或
- 本地 `ollama pull qwen2.5-vl:7b`，`.env` 把 `VLM_*` 指到 Ollama。
- 否则视觉类技能会报错或得到空描述 —— 不影响飞行控制，只影响"看"。

---

## S9. 安全护栏（实机必做，不能跳）

真桨 + 软件能自主发飞指令 = 有伤人风险。**首飞前逐条确认**：

1. **RC 手动接管全程**：RC 开关绑一个通道切 PX4 Position/Manual 模式，软件失控时能瞬间手动接管。这是最后一道防线，独立于软件。
2. **飞控 failsafe**：PX4 里设好 —— 信号丢失 → RTH/Land、低电量 → Land、地理围栏（`GF_*` 参数）按场地框定。
3. **`_MAX_ALT` 按场地调小**：`adapters/px4_adapter.py:15` 的 `_MAX_ALT=200`，实机按场地限高调小（如 30-50m）。
4. **离地高度限制**：agent 提示词已强制 `down ≤ -8`（≥8m 离地），但真机要再核对。
5. **测试阶梯**：拆桨 arm/disarm → 拆桨 takeoff/stop → 系绳悬停 → 空旷地低空短悬 → 再放自主。
6. **LLM 决策护栏（待加代码）**：仿真没有，实机建议在 skill 层加：执行移动技能前检查 `GPS fix` 是否 3D+、是否已 armed、单次位移距离上限（防 agent 下发飞 200 米）、是否在地理围栏内。这块是新增代码，需要再写。
7. **`stop_execution` 实测**：网页点停止，确认 `adapter.request_stop()` + `hover/land` 真能让真机停住。

---

## S10. 启动 + 验证（实机完整流程）

```bash
# 【NX】
cd ~/AerialClaw
source .venv/bin/activate
export SIM_ADAPTER=mavros
export MAVROS_NAMESPACE=/mavros
export AERIALCLAW_FORCE_GZ_SENSOR_BRIDGE=0      # 不起 gz 桥；若已接 RealSensorBridge 则去掉这行
.venv/bin/python server.py
```

从地面浏览器访问（NX 的 IP）：

```
http://<NX的IP>:5001
```

**验证顺序**（拆桨）：

1. `curl -s http://<NX>:5001/api/adapter/status` → `connected:true`
2. 网页 manual 模式：arm → 电机响应 → disarm。✅
3. takeoff（拆桨空转）→ stop_execution → 停住。✅
4. 上桨 → 室外空旷 → 系绳 → 低空悬停 30 秒。✅
5. 切 AI 模式，发"起飞至 1.5 米并悬停"，手放在 RC 接管开关上。✅
6. （SIYI 接好后）`rosservice list | grep '^/camera/'` → 云台服务在；网页发"云台转向左前方并放大一倍"。✅
7. （相机桥接好后）`curl -s http://<NX>:5001/api/sensor/status` → `running:true`、gimbal `frame_count` 在涨；网页云台画面有图。✅

---

## S11. 排障速查（实机版）

| 现象 | 原因 / 处理 |
|---|---|
| `Permission denied: /dev/ttyTHS0` | dialout 组没生效 → `id` 看不到 dialout 就重新登录 |
| `adapter connected:false` | MAVROS 未连接 → 检查 `/mavros/state`、`fcu_url` 和波特率 |
| `rosservice list` 没有 `/camera/*` | 真机 photo_function 节点没起，或未 source `/opt/ros/noetic/setup.bash` |
| `ping 192.168.144.25` 不通 | SIYI 没上电/网线没插；NX 网口没配 192.168.144.x 同网段 |
| 云台 zoom 不生效 / 超调 | 真机连续变焦语义和仿真不同，需校准 `ZOOM_STEP_X` 和 zoom_in 循环（S6.4） |
| 相机画面 NO SIGNAL | 还没接 `RealSensorBridge`（S7），或 RTSP 地址不对 |
| GPS 不解锁 / `armed` 一直 false | 没搜到星 → 室外等 3D fix；或 pref-light 检查未过（看 PX4 `commander check`） |
| LLM 401 / `无法连接模型服务` | glm token 过期或 NX 断网；切 deepseek 或本地 ollama |
| `fly_to` 落点偏几米 | 真实 GPS ±2-3m，正常；要更准上 RTK/光流 |

---

## S12. 与仿真指南（第一部分）的对照：哪些跳过

| 仿真指南步骤 | 实机是否需要 |
|---|---|
| ① 软链接 PX4-Autopilot | ❌ 跳过（实机不跑 SITL，不需要 PX4 源码） |
| ② uv venv 3.10 + system-site-packages | ✅ 同样要做（S4），但用系统 python、不带 `--seed` |
| ③ pip install requirements | ✅ 同（S4） |
| ④ setup_px4.sh 装模型/世界 | ❌ 跳过（实机没 Gazebo，不需要模型/世界） |
| ⑤ npm build 前端 | ❌ 跳过（用 rsync 传过去的 `ui/dist`） |
| ⑥ 配 LLM | ✅ 同（S8），但配置文件要手动拷 |
| ⑦ sim_quickstart.sh | ❌ 跳过（那是起 Gazebo+PX4 SITL 的）；实机直接 `python server.py`（S10） |
| ⑧ 验证 | ✅ 同思路，但用 `/api/adapter/status` 看飞控，不用 doctor_gazebo |
| 排障 E（protobuf 共存） | ⚠️ 部分相关：若 NX 上 gz 绑定和 mavsdk 共存仍需 `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`；纯实机不导入 gz 绑定则不需要 |
| 排障 F（PRIME offload / GPU 渲染） | ❌ 跳过（实机不渲染） |

---

## S13. 实机部署待确认/待补清单（来自 WORKLOG 交接）

1. **PX4 固件版本**：建议统一 v1.15.4（项目针对版本），避免 main 的参数/API 差异。
2. **飞控串口端口/波特率**：当前 MAVROS 使用 `ttyTHS0:921600`，变更时同步 MAVROS 参数。
3. **SIYI 实物 IP/端口 + RTSP 地址**：当前为 `192.168.144.25:8554/live`。
4. **真机 zoom 校准**：`manual_zoom` 连续变焦，需实测每秒放大倍率，调 `gimbal_skill.py` 的 `ZOOM_STEP_X` 与循环逻辑。
5. **RealSensorBridge 实现**：S7 骨架 + server.py 分支接入（我可在 SIYI 接好后帮你写完整）。
6. **VLM 视觉模型**：若要"观察/拍照分析"指令，配云端 vision 或本地 `qwen2.5-vl`。
7. **LLM 决策护栏代码**：skill 层 GPS fix / armed / 单次位移上限 / geofence 检查（S9.6，待加）。
8. **RTL 降落行为**：PX4 main 仿真中 RTL 回 home 后转 HOLD 不自动着陆；实机确认 `RTL_LAND_FINAL` 参数或保留强制 land 逻辑。
9. **mavsdk_server 重连**：数传断连更频繁，重点验证自愈窗口内的技能失败重试。
10. **起飞重量**：SIYI A8 Mini 重量计入总重，确认推力余量。
11. **代码提交策略**：仿真侧诸多修改未提交（`git status` 可见），迁移前决定提交/打包，避免遗漏 `config.py`/`agent_loop.py`/`server.py`/`px4_adapter.py`/`gimbal_skill.py` 等关键改动。
