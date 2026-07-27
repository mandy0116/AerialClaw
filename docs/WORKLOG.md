# 工作日志 (WORKLOG)

本文件记录 AerialClaw 开发过程中的重要修改。按日期倒序排列。

---

## 2026-07-25 — 实机迁移交接总结（vs 原 git 仓库 / 环境要求 / 待确认点）

> 面向队友对接实机迁移。下文为本会话及前序会话累计改动的高度概括，细节见同日其它条目与 `DEPLOY_GUIDE_UV_CN.md`。

### 一、改动总览（相对原 git 仓库）

#### A. 部署/启动脚本修复（让项目能在本机 PX4-main + gz-Harmonic 跑起来）
- `scripts/start_sim.sh` + `scripts/sim_quickstart.sh`：加 `GZ_SIM_SYSTEM_PLUGIN_PATH` 指向 PX4 build 的 `gz_plugins` 目录。**否则 gz 找不到 `MotorFailurePlugin` → ruby CLI 段错误 → gz 崩 → PX4 rcS 返回 2、仿真起不来。** 这是本机最关键的潜在 bug。
- `scripts/start_sim.sh` + `scripts/sim_quickstart.sh`：加 NVIDIA PRIME offload（`__NV_PRIME_RENDER_OFFLOAD=1` 等）。混合显卡笔记本（AMD 核显 + NVIDIA 独显）上 gz 传感器渲染必须走独显，否则 Mesa EGL `dri2 screen` 失败、摄像头/gpu_lidar 0 帧。`GZ_FORCE_NVIDIA_OFFLOAD=0` 可关。
- `scripts/start_sim.sh` + `scripts/doctor_gazebo.sh`：加 `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`。gz apt 绑定（protobuf 3.12）与 pip mavsdk（protobuf 7.x）同进程共存必需，否则 mavsdk 导入崩。
- 新增 `scripts/start_custom_sim.sh`：用自定义飞机/世界模型的启动器（自动把 `sim/models/<model>`、`sim/worlds/<world>.sdf` 安装到 gz/PX4 运行时路径）。
- 新增 `scripts/start_gimbal_bridge.sh`：启动 rclpy 云台桥接（source ROS2 + ifc_pro install + protobuf 纯 Python）。

#### B. 云台功能（photo_function 仿真桥接 + 语言控制）
- `sim/models/x500_lidar_2d_cam/model.sdf`：加 pan/tilt 云台（`gimbal_yaw_link`/`gimbal_pitch_link`/`gimbal_cam_link` + 两个 revolute 关节 + `JointPositionController`，topic `gimbal/yaw_cmd`、`gimbal/pitch_cmd`）+ `gimbal_cam` 相机。云台 link 轻量(0.05/0.04/0.02kg) + 关节阻尼(1.5)+摩擦(0.02) + 惯量(1e-4) + PID(p=3,i=0.2,d=0.5) —— 解决三件事：ODE collide 崩溃（轻 link 无阻尼重力下垂狂摆）、到位精度（i_gain 消除稳态误差，0.5rad 命令→0.499rad）、不影响起飞（总重 0.11kg）。
- 新增 `ros2/gimbal_sim_bridge.py`：rclpy 节点，实现 photo_function ROS 服务（`set_angle`/`rotate_gimbal`/`manual_zoom`/`get_current_zoom`/`get_max_zoom`/`get_attitude`/`center_gimbal`，前缀 `common/camera/`）→ 翻译成 gz transport `Double` 命令。**仿真/真机同一套 ROS 服务 API，AerialClaw 技能代码不变。**
- `sim/gz_sensor_bridge.py`：加 `gimbal` 相机方向（订阅 `gimbal_cam/image`）+ 订阅 `/gimbal/zoom_level` 做数字变焦（中心裁剪放大回原尺寸）。
- 新增 `skills/gimbal_skill.py` + `skills/docs/gimbal_control.md`：`gimbal_control` 技能（point/zoom_in/zoom_out/zoom_stop/center/rotate），用 `subprocess` 调 `ros2 service call`（内部 source ROS2+ifc_pro，不污染 server.py 主进程）。`server.py:148` `ALL_SKILL_FACTORIES` 注册。
- `server.py`：`_start_sensor_stream` 的 `DIRECTIONS` 加 `gimbal`，云台帧推前端。
- UI（`SensorPanel.jsx`/`AiMonitorPanel.jsx`/`CockpitView.jsx`）：加云台相机格/快捷键`6`/PiP。

#### C. 仿真稳定性 / 模型修复
- `sim/worlds/urban_rescue.sdf`：加 `<magnetic_field>` + `gz-sim-magnetometer-system` 插件。**否则磁罗盘 0 数据、EKF2 缺数据、PX4 拒绝解锁。** 同步到 PX4 worlds 目录。
- `~/.simulation-gazebo/models/x500`：原空占位目录换成指向真 x500 的软链接；自定义模型也拷进 `PX4-Autopilot/Tools/simulation/gz/models/`。修 `model://x500` include 解析失败（base_link 缺失）。
- `adapters/px4_adapter.py`：`_ARRIVE_DIST` 2.5→0.5（fly_to 到位精度，之前"向东5米"只飞到 2.6m）。近目标最低速 0.4→0.3。
- `brain/agent_loop.py`：坐标系提示词重写（NED 一致 + `fly_relative` 是机体坐标随航向变 + `down≤-8` 安全高度）；修 `{GROUND_Z}` 字面占位符 bug（system_prompt 未 .format）。
- `brain/agent_loop.py` + `server.py`：`action = output.get("action") or {}`（DeepSeek 返回 `action:null` 时 NoneType 崩溃防护）。

#### D. LLM / AI 行为（细节见同日"修复 AI 模式无响应链路"条目）
- `config.py`：deepseek 模型 `deepseek-chat` → `deepseek-v4-pro`/`v4-flash`（本服务只接受 v4 系列模型名）；新增 `glm` provider（`ollama.com/v1`，`glm-5.2`）。
- `llm_client.py`：网络重试 3 次 + temperature 400 重试。
- `brain/agent_loop.py`：`on_error` 回调（LLM 失败推前端，不再假死）、`max_tokens` 500→4000、纯移动指令终止识别、思考占位卡片。
- `skills/gimbal_skill.py`：`point` action 支持 `zoom_steps`（转向+变焦复合指令一步完成）。

#### E. 文档
- 新增 `DEPLOY_GUIDE_UV_CN.md`：本机保姆级部署指南（含全部踩坑+修复+排障速查）。

### 二、系统环境要求（实机迁移前确认）

| 项 | 要求 | 说明 |
|---|---|---|
| OS | Ubuntu 22.04 (jammy)，内核 6.8 | 官方支持 |
| Python | **3.10** | gz apt 绑定是 `cpython-310` 编译的 .so，只能 3.10 导入；uv 环境 `--python 3.10 --system-site-packages --seed` |
| Gazebo | gz Harmonic (gz sim 8.x) | 项目要求 8.x；本机同时装了 Garden(7)+Harmonic(8)，默认解析到 Harmonic，勿动 |
| PX4 | 项目设计 **v1.15.4**；本机用 main(v1.17-alpha1) | main 多处不兼容（SDF frame 严格、rcS、gz 插件路径）已逐个绕过；**实机建议飞控固件统一 v1.15.4** |
| ROS2 | humble | 仅云台桥接/真机 photo_function 需要；纯仿真飞行不用 ROS |
| GPU | 混合显卡需 PRIME offload 到 NVIDIA 独显 | 仿真传感器渲染必需；实机伴飞电脑若无 Gazebo 渲染则不需要 |
| photo_function | 需 `colcon build` 生成 srv/msg | `/home/ubuntu/ifc_pro/install`；rclpy 桥接 + 技能都依赖 |
| protobuf | `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` | gz+mavsdk 同进程共存必需 |
| MAVSDK | pip mavsdk（已装 v3.17） | 仿真连 `udp://:14540`；实机连飞控串口/数传 |

### 三、实机迁移待确认/完善点

1. **PX4 版本对齐**：项目针对 v1.15.4，本机用 main 绕过多处。实机飞控固件建议统一 v1.15.4，避免 main 的 SDF/rcS/插件差异；若用 main，必须带上本会话的 start_sim/世界/模型修复（尤其 `GZ_SIM_SYSTEM_PLUGIN_PATH`）。
2. **飞控连接**：实机改 `PX4_MAVSDK_URL`（`server.py:296` 读，默认 `udp://:14540`）→ 串口 `serial:///dev/ttyAMA0:921600` 或数传/WiFi。先手动验证 arm/takeoff/land 经 API 跑通。
3. **云台真机**：仿真用 `ros2/gimbal_sim_bridge.py`；真机换真实 `photo_function`（a8_mini 后端连 SIYI A8 Mini 实物）。`gimbal_control` 技能代码不变（同 ROS 服务 API）。需确认：SIYI 实物 IP/端口、`manual_zoom` 真机是**连续变焦**（仿真每步 0.5x，语义有差异，真机需 `zoom_stop` 停）、`set_angle` 限位与仿真一致。
4. **VLM 视觉**：现 VLM 走 deepseek-v4-flash（纯文本，无视觉）。实机若要"观察/扫描/拍照分析"语言指令，需加真视觉模型（Ollama `qwen2.5-vl` 或云端 vision API），否则这类指令会报错。
5. **LLM 渠道稳定性**：deepseek 本机网络抖动严重（30s 超时/断连交替）；glm-5.2 token 与 Claude Code 会话共享、可能过期。实机伴飞电脑需稳定联网或本地 ollama；建议配多渠道 + `ACTIVE_PROVIDER` 可切。
6. **传感器替换**：仿真靠 gz 传感器桥接（`gz_sensor_bridge.py`）；实机靠飞控真实 IMU/GPS/mag + 真实相机（用 OpenCV 抓图替换 gz 桥接）。`fly_to_ned` 用 GPS NED，真实 GPS 误差 ±2-3m（仿真 cm 级），"固定距离飞行"会有米级偏差，要更准需 RTK 或光流。
7. **安全护栏（实机必做）**：RC 手动接管全程、飞控侧地理围栏 + failsafe、`_MAX_ALT` 按场地调小、离地高度限制、先系绳/空旷试飞。LLM 决策护栏（skill 层检查 GPS fix / 解锁状态 / 单次位移上限）**待加**。
8. **RTL/降落**：PX4 main 仿真中 RTL 回 home 后不自动着陆（转 HOLD 悬停）；仿真侧曾加 `return_to_launch` 强制 land 但**本会话末已应用户要求回退**，当前为原样。实机需确认 `RTL_LAND_FINAL` 参数或保留强制 land 逻辑。
9. **mavsdk_server 自愈**：已加 `_run_telem` 捕获断连重连（~8s 自愈），但重连窗口内技能可能失败需重试；实机数传断连更频繁，需重点验证。
10. **起飞重量**：仿真云台 0.11kg 不影响起飞；实机 SIYI A8 Mini 重量需计入无人机总重，确认推力余量。
11. **未提交**：以上改动多为工作区未提交状态（`git status` 可见），迁移前需决定提交/打包策略，避免遗漏 `start_sim.sh`/`sim_quickstart.sh`/`config.py`/`agent_loop.py`/`server.py`/`px4_adapter.py`/`gz_sensor_bridge.py`/模型 SDF/世界 SDF 等关键修改。

---

## 2026-07-25 — 修复 AI 模式"无响应"链路 + 切换 LLM 渠道 + mavsdk_server 自愈

### 起因
用户在网页 AI 模式下发指令（如"向前飞20米"），仅显示"🤖 AI 任务"和"🧠 启动 Agent 自主循环..."后无响应。逐层排查发现是多个独立问题叠加。

### 问题诊断与修复链

#### 问题 1：LLM 渠道（deepseek）网络极不稳 + 模型选择不当
- **现象**：日志满屏 `HTTP 400`、`无法连接模型服务`、`The read operation timed out`。
- **根因 A（模型）**：`deepseek-v4-pro` 是重型推理模型，推理链极长，AgentLoop 的 `max_tokens=500` 全被 `reasoning_content` 吃光，`content` 字段为空、`finish=length` → `llm_client` 只读 `content` → 返回空串 → 解析失败。
- **根因 B（网络）**：本机到 `api.deepseek.com` 抖动严重（实测 30s 超时 / 17s 断连 / 6s 成功 交替）。仅 deepseek 配了 key，openai/zhipu/moonshot 无 key，ollama 未运行，无备用渠道。
- **修复**：
  - `deepseek` 默认模型 `v4-pro` → `v4-flash`（推理短，能正常输出 content）。
  - 新增 `glm` provider（`https://ollama.com/v1`，模型 `glm-5.2`），实测 ~1-2s 稳定可达、OpenAI 兼容、`max_tokens` 给够时返回合法 JSON。`active_provider` 切到 `glm`。
  - VLM 模块仍留 deepseek-v4-flash（glm-5.2 视觉支持未验证）。

#### 问题 2：AgentLoop 静默吞 LLM 失败，前端假死
- **现象**：LLM 失败只写服务端日志，不通知前端，页面停在"启动 Agent 自主循环..."。
- **根因**：`agent_loop.py` 的 LLM 异常和解析失败只 `logger.error/warning` + `time.sleep(2)` + `continue`，无 WebSocket 事件。
- **修复**：AgentLoop 新增 `on_error` 回调；`server.py` 的 `on_ai_task` 和 `_run_agent_loop` 两处注入实现（emit `ai_thinking{phase:"error"}` + `push_log`）。

#### 问题 3：LLM 调用期间前端无反馈
- **现象**：每轮 LLM 调用要等返回（最坏几十秒）才有更新，期间只有 THINKING 标签不推进。
- **修复**：AgentLoop 每轮调用 LLM **前**先发"🤔 思考中..."占位卡片（复用 `on_thinking`），LLM 返回后被真实结果覆盖。前端无需改动。

#### 问题 4：glm-5.2 第2轮起 JSON 被截断
- **现象**：切 glm 后第1步成功，第2/3/4轮连续解析失败。raw 显示 JSON 写到一半被切断。
- **根因**：`max_tokens=500` 对推理模型不够；第2轮 prompt 带执行历史更长，reasoning 消耗 token 后 content 被截断。
- **修复**：AgentLoop 三处 `max_tokens` 调大：主循环 500→4000，战术方案 300→800，安全返航 300→2000。实测模拟第2轮（带历史）返回完整可解析 JSON。

#### 问题 5：mavsdk_server 崩溃后无法恢复
- **现象**：takeoff 报 `Stream removed (Socket closed)` → `50051 Connection refused`。mavsdk_server 进程变 `<defunct>`，但 PX4 SITL + Gazebo 仍存活。
- **根因**：遥测协程 `_t_*` 在 mavsdk_server 死时抛 `AioRpcError`，但无 try/except，异常被 asyncio 吞掉，`self._connected` 保持 True → server 的重连循环（靠 `not is_connected()` 触发）永不触发。
- **修复**：`px4_adapter.py` 加 `_run_telem` 包装器捕获遥测流异常，断开时置 `self._connected = False`，使 server 已有的重连循环能在 ~8s 内自动 `connect()` 拉起新 mavsdk_server。
- **遗留**：动作方法传给 `_ra` 的是已绑定旧 `self._system` 的协程，重连后失效，重连窗口（~8s）内点的技能仍会失败需手动重试；彻底自愈需把 `_ra` 改成接受 callable（未做）。mavsdk_server 崩溃根因未定位（疑似与 PX4 SITL 偶发不稳）。

#### 问题 6：gimbal_control 的 zoom 不生效，agent 陷入 9 轮空转
- **现象**：任务"将云台向左前方旋转并放大一倍"，agent 连续 9 轮调用 gimbal_control，yaw 成功但 `current_zoom` 始终 1.0；试过 `zoom_steps=1/2/10`、`action='zoom'`（无效）、`run_python`，直到耗尽。
- **根因**：`gimbal_skill.py` 的 `point` action 只调 `SetAngle`（转向），**完全忽略 `zoom_steps`** —— `zoom_steps` 仅在 `zoom_in`/`zoom_out` action 中生效。agent 自然期望 `point(yaw, zoom_steps)` 一次完成"转向+放大"，但 zoom_steps 被静默丢弃；而 agent 又始终没调用正确的 `zoom_in` action。实测桥接本身正常：直接 `ros2 service call manual_zoom direction:1` 四次，zoom 1.0→3.0（每步 0.5x）。
- **修复**：`point` action 在传入 `zoom_steps>0` 时，转向后追加 `ManualZoom(direction:1)` 循环放大，实现"转向+变焦"复合指令一步完成。同步更新 `description` / `input_schema`，明确 point 支持 zoom_steps。实测 `point(yaw=-45, zoom_steps=2)` → `current_zoom=2.0, yaw=-45.0`，任务一步达成。

### 文件变更明细

#### `config.py`
- `deepseek` provider：`default_model` `deepseek-v4-pro` → `deepseek-v4-flash`；新增 `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` 环境变量覆盖；加注释说明 v4-pro 不适合 planner。
- 新增 `glm` provider：`base_url=https://ollama.com/v1`、`default_model=glm-5.2`、`timeout=90`、`api_key` 读 `GLM_API_KEY`/`ANTHROPIC_AUTH_TOKEN`。注释标明 token 与 Claude Code 同账户额度、可能过期。

#### `.aerialclaw_llm_config.json`（已 gitignore，启动时覆盖 config.py）
- `deepseek` + `vlm` 两个 provider 的 `default_model` → `deepseek-v4-flash`。
- `active_provider`：`deepseek` → `glm`。
- 新增 `glm` provider 块（含实际 token）。
- ⚠️ 该文件由 `llm_config_store.load_runtime_config` 在启动时覆盖 `config.py`，改配置必须同步此文件，只改 config.py 无效。

#### `llm_client.py`
- 新增 `logging` + `logger`；新增网络重试常量 `_NETWORK_EXC`、`_MAX_NET_RETRIES=3`、`_NET_RETRY_DELAY=1.5`。
- 重构 `_chat_openai_compat`：抽出 `_build_payload` + `_stream_once` 内嵌 helper；
  - **网络层重试**：对 `URLError`/`socket.timeout`/`HTTPException`/`ConnectionError`/`TimeoutError` 自动重试 3 次（间隔 1.5s），应对 deepseek/云端端点抖动。
  - **temperature 400 重试**：HTTP 400 且 body 含 `temperature` 时，去掉 `temperature` 重试一次（推理模型不支持该参数）。
  - 外层 `except` 改为 `_NETWORK_EXC` 兜底。
- `chat_with_tools`（非流式，AgentLoop 不用）未改。

#### `brain/agent_loop.py`
- `AgentLoop.__init__` 新增 `on_error` 回调参数（默认 no-op）。
- LLM 调用失败 `except` 分支：调 `self.on_error(...)` 推前端。
- 解析失败分支：调 `self.on_error(...)` 推前端。
- 每轮 LLM 调用前：`self.on_thinking(iter, {"thinking":"思考中...", "decision":"pending"})` 占位。
- `max_tokens`：主循环 500→4000；战术方案 300→800；`_safe_return` 300→2000。

#### `server.py`
- `on_ai_task`：新增 `_on_error` 回调（`push_log("warn")` + emit `ai_thinking{phase:"error"}`），传入 AgentLoop。
- `_run_agent_loop`：同上新增 `on_error` 并传入 AgentLoop。

#### `adapters/px4_adapter.py`
- 新增 `_run_telem(coro, name)` 包装器：捕获遥测流异常，断开时置 `self._connected = False` 并 warn 日志。
- `_start_telem` 改为用 `_run_telem` 包装每个 `_t_*` 任务，使 mavsdk_server 崩溃后 server 重连循环能感知。

#### `skills/gimbal_skill.py`
- `point` action 新增 `zoom_steps` 支持：传入 `zoom_steps>0` 时，`SetAngle` 后追加 `ManualZoom(direction:1)` 循环放大 + 停止，实现"转向+变焦"复合指令一步完成（之前 `point` 静默忽略 `zoom_steps`，导致 agent 陷入空转）。
- 更新 `description` / `input_schema`：明确 point 可带 zoom_steps 实现转向+放大，复合指令直接用 point + zoom_steps。

### 功能新增：云台画面可视化

#### 背景
仿真模型已含 `gimbal_cam` 相机，`sim/gz_sensor_bridge.py` 早已支持 `gimbal` 方向（订阅 `gimbal_cam/image` topic，按 `/gimbal/zoom_level` 做数字变焦），但：
- `server.py` 的 `_start_sensor_stream` 推送列表 `DIRECTIONS` 只有 front/rear/left/right/down，**缺 gimbal** → 云台帧订阅了却不推前端。
- 前端三处相机列表（SensorPanel / AiMonitorPanel / CockpitView）都没 gimbal 项。

#### 改动
- `server.py`：`_start_sensor_stream` 的 `DIRECTIONS` 加 `"gimbal"`，云台帧纳入 `sensor_cameras` 推送。
- `ui/src/components/SensorPanel.jsx`：`CAM_LABELS` 加 `gimbal: '◎ 云台'`；相机网格 layout 第二行加 `gimbal` 格。
- `ui/src/components/AiMonitorPanel.jsx`：`CAM_DIRECTIONS` 加 `{key:'gimbal', label:'◎ GIMBAL', cockpit:'gimbal'}` → AI 模式主视图可切到云台、缩略图栏可见。
- `ui/src/components/CockpitView.jsx`：`viewImages`/`viewLabels` 加 gimbal；键盘快捷键 `'6'` 切云台；PiP 栏自动含云台（pipViews 由 viewImages 派生）。
- 前端 `npm run build` 重新构建 `ui/dist`。

#### 验证
- `/api/sensor/status` 确认桥接 gimbal slot：640×480、9.56 fps、frame_count>6000，topic 已订阅、帧持续流入。
- 数字变焦：bridge 对 gimbal 方向按 `/gimbal/zoom_level` 应用数字变焦，与 gimbal_control 的 zoom 联动（agent 放大时画面同步放大）。

### 问题 7：纯移动指令缺乏终止识别，agent 超调多飞
- **现象**：任务"向左飞20米"，`fly_relative(right=-20)` 一次即移 20 米，应第1轮 done。但 agent 第2轮又飞一次（"继续按指令移动"），第3轮被反重复警告逼用 fly_to，第4轮再 fly_relative，共飞 ~80 米严重超调，且因 fly_relative 是机体坐标系、朝向会漂，多次 = 乱晃。直到第5轮才 done。
- **根因**：`AGENT_SYSTEM_PROMPT` 没有明确告诉 agent "纯移动指令一次达标即 done"。原"简单指令"规则针对"飞过去+看看+问操作员"，不适用纯移动；"什么时候判 done"规则偏巡检类。agent 缺乏对"只飞N米"这类指令的终止识别。
- **修复**：`brain/agent_loop.py` 的 `AGENT_SYSTEM_PROMPT` 在"简单指令"与"什么时候判 done"之间新增"纯移动指令的终止识别"规则：纯移动指令 = takeoff(若需要) → 一次移动技能 → 立刻 done；明确警告"fly_relative(right=-20) 再调一次 = 总共40米超调"、"'向左飞N米'是相对朝向的一次性位移，不要拆多次"、纯移动 vs 复杂的判断（指令含看/搜/巡/找/拍 = 复杂，否则纯移动）。
- **验证**：模拟第2轮（第1步 fly_relative 成功、位移19.8m）调用，agent 返回 `decision=done`、thinking 明确"纯移动指令一次执行即达标，立即判done"。
- **glm token 生命周期**：`.aerialclaw_llm_config.json` 中 glm 的 key 即 Claude Code 会话 token，共享额度、可能过期。失效时切回 deepseek 或本地 ollama。token 仅存于该 json 文件（gitignore 已覆盖），删文件即失效。
- **max_tokens=4000 成本/延迟**：单次调用最多 8×输出，叠加 `max_iterations=50` 理论上限较高；实际多任务几轮完成。可按需调保守（如 2000）。
- **网络重试最坏延迟**：3×timeout（glm 90s）≈ 270s 单次调用卡住；重试在抖动时重复计 input token。
- **VLM 仍走 deepseek**：视觉感知类功能未跟随切 glm，可能仍受 deepseek 网络抖动影响。
- **mavsdk_server 重连窗口**：~8s 内技能可能失败需重试；每次重连 spawn 新 mavsdk_server，旧进程变僵尸，长期累积（server 重启清空）。

### 验证
- `llm_client.chat()` + glm-5.2 + `temperature=0.5` + `max_tokens=4000` 实测返回合法 JSON。
- 模拟 AgentLoop 第2轮（带执行历史）调用，`_parse_agent_output` 解析成功，决策合理。
- `config` 加载验证：`ACTIVE_PROVIDER=glm`，planner 解析到 `glm-5.2 @ ollama.com/v1`。
- 全部改动文件 `ast.parse` 语法通过。
- mavsdk_server 自愈：依赖 server 重启后实测（待用户重启验证）。


一、立刻要做的（在 NX 上）

  1. 把代码和配置弄到 NX 上

  仓库可以 git clone，但有两个文件 gitignore 了、不会跟过去，必须手动拷：
  - .env（环境变量）
  - .aerialclaw_llm_config.json（含 glm token，没有它 planner 直接 401）

  从开发机拷到 NX（在你 NoMachine 的 NX 终端里，或用 scp）：
  # 在开发机上，把这两个文件传到 NX
  scp .env .aerialclaw_llm_config.json <nx用户>@<nx的ip>:~/AerialClaw/

  2. 确认硬件 + 软件状态（跑这几条，结果贴给我）

  ls -l /dev/ttyACM* /dev/ttyTHS* /dev/ttyUSB* 2>/dev/null     # 飞控/相机串口
  ls /opt/ros/humble/setup.bash 2>/dev/null && echo "ROS2 OK"  # ROS2
  ls ~/ifc_pro/install/setup.bash 2>/dev/null                  # photo_function 真机节点
  ls ~/AerialClaw/server.py 2>/dev/null                        # AerialClaw 代码
  ip addr | grep -E "192.168.144|usb"                          # SIYI 相机网口

二、三个集成点

  ① 飞控 PX4 —— 改连接串即可，代码不动
  ```
  # 在 NX 的 .env 或启动环境里
  export SIM_ADAPTER=px4
  export PX4_MAVSDK_URL=serial:///dev/ttyACM0:57600   # 端口/波特率按你的接线改
  # 串口权限：
  sudo usermod -aG dialout $USER   # 加完重新登录
  MAVSDK 的 mavsdk_server 支持串口连接，px4_adapter 只是把 PX4_MAVSDK_URL 透传给 System.connect()，不用改代码。
  ```

  ② 云台 SIYI A8 Mini —— 跑真 photo_function 节点，技能不变
  ```
  # 在 NX 上启动真实 photo_function（替代仿真用的 gimbal_sim_bridge.py）
  source /opt/ros/humble/setup.bash
  source ~/ifc_pro/install/setup.bash
  ros2 run <photo_function 的可执行名> ...   # 按 ifc_pro 的说明起
  ```
  gimbal_skill.py 走的是 /common/camera/* ROS2 服务，真机节点和仿真桥接用的是同一套 API，技能代码完全不用改。

  ③ 相机画面可视化 —— 这是缺口，要补代码
  gz_sensor_bridge 是 Gazebo 专用，真机上没有。前端 sensor_cameras（含云台画面）会没源。两个选择：
  - (a) 写一个真机相机桥：读 SIYI A8 Mini 的视频流（RTSP 或 photo_function 发布的 ROS2 image topic）→ JPEG → emit
  sensor_cameras。我可以帮你写，但需要先知道 SIYI 相机的输出方式（RTSP 地址？还是 ROS2 image topic？）。
  - (b) 先不要可视化：飞控 + 云台控制 + LLM agent 照常工作，只是 UI 看不到画面。先跑通飞控再说。

  三、安全（真桨，必须先做）

  软件能自主发 takeoff/fly_to，真机一旦失控伤人。起飞前：
  - 硬件 kill switch：RC 上绑一个通道做 PX4 flight termination / kill，独立于软件，软件挂了也能切断。
  - failsafe：PX4 里设好信号丢失/低电量 → RTH 或 Land。      1 new message (ctrl+End) ↓ 
  - 先拆桨：第一次 arm/disarm、电机响应测试都拆桨做。
  - 第一次飞行低空短悬，确认 agent 的 stop_execution → hover/land 真能停住。

  我需要你提供两样东西才能继续

  1. 上面"二"里那几条硬件/软件检查命令的输出。
  2. SIYI A8 Mini 相机的视频输出方式：是 RTSP 流（地址？）、还是 photo_function 真机节点会发布 ROS2 image topic（topic
  名？）、还是别的。这决定相机桥怎么写。 
