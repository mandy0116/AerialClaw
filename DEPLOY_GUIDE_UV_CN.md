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
4. 试一句：`起飞至15米高度并观察周围环境`

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