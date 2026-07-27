# 工作日志 (WORKLOG)

本文件记录 AerialClaw 开发过程中的重要修改。按日期倒序排列。

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