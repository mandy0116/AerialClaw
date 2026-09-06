# AerialClaw 真机迁移与室内试飞指南

本文档说明如何把 AerialClaw 从 PX4+Gazebo 仿真迁移到真实 PX4 多旋翼，覆盖伴随计算机环境、飞控连接、相机、LLM/VLM、网页控制台和分级试飞。

这不是飞行器适航或安全认证文件。第一次上桨前，必须由熟悉 PX4、遥控器和机体的飞手现场复核所有步骤，并让 RC 接管、飞控 failsafe 和独立电机急停始终可用。

## 1. 真机架构

仿真时：

~~~text
Gazebo/PX4 SITL → MAVSDK → PX4Adapter → server.py → 浏览器
~~~

真机时：

~~~text
真实 PX4 飞控 ─串口─> MAVROS（ROS1 Noetic）→ MavrosAdapter → server.py ← 浏览器
                                      │
                                      ├─ WorldModel/遥测 → WebSocket → 浏览器
                                      └─ RealSensorBridge ← RTSP 相机
~~~

真机不运行 Gazebo、PX4 SITL 或 sim/gz_sensor_bridge.py。真机飞行控制统一使用
`MavrosAdapter` 通过 ROS1 `/mavros` 控制 PX4；MAVROS 独占飞控串口，AerialClaw
不再让 MAVSDK 直接打开同一串口。PX4/MAVSDK 适配器仅保留给仿真。

网页“手动模式”和“AI 模式”都不能绕过技能层安全检查；但网页不是飞控级安全系统。飞手必须能通过 RC 退出 Offboard 并接管。

## 2. 支持范围与当前边界

当前真机可以使用：

- PX4 遥测：本地 NED、GPS、航向、电池、解锁和 in_air 状态；
- 起飞、悬停、定点移动、相对移动、调高/调低和降落；
- 驾驶舱连续速度控制；
- AI 规划后调用同一套硬技能；
- RTSP 相机抓帧并推送到网页；
- 室内软件安全包线：1.5 m/s、0.5–4 m、高度/围栏/单步/电量/心跳限制。

当前不能宣称已经闭合的能力：

- 真机 LiDAR 尚未接入 RealSensorBridge，所以没有 fail-closed 的自动避障；
- deepseek-v4-flash 用于文本规划，不是视觉模型；observe 需要另配支持图像输入的 VLM；
- 应用层限制不能替代 PX4 的 RC 接管、failsafe、飞控围栏和硬件 kill switch；
- fly_to 依赖 PX4 有效的本地 NED 位置，普通 GPS 在室内通常不够准确。

## 3. 硬件与飞控准备

### 3.1 必需硬件

- PX4 飞控和已验证的多旋翼机架；
- 电池、动力系统和足够推力余量；
- 可用 RC 发射机/接收机；
- 伴随计算机（笔记本、工控机、Jetson 等）；
- 飞控到伴随计算机的 USB/UART/数传链路；
- 可独立触发的 RC 模式切换和电机急停开关；
- 室内测试用防护笼、系绳或其他经过飞手确认的约束措施。

如果使用 SIYI A8 Mini 或其他 RTSP 相机，还需要相机网络链路和相机供电。相机不是飞控位置源，不能代替 VIO、光流或 UWB。

### 3.2 上电前的硬件检查

1. 第一次连接和所有软件测试均拆桨。
2. 检查电机、电调、螺旋桨方向和机臂固定。
3. 确认电池、电源和 USB/UART 地线连接可靠。
4. 确认 RC 能看到 PX4，且模式开关和急停开关对应正确通道。
5. 确认飞手知道 PX4 的手动、稳定、定高/定点和降落模式如何切换。

### 3.3 PX4 必须配置和验证的项目

在 QGroundControl 中按实际机体和场地配置并记录：

- RC 校准、模式开关和 RC 接管；
- Offboard 丢失动作（例如 COM_OF_LOSS_T 及对应 failsafe）；
- RC 丢失、低电量、位置丢失时的动作；
- 最大高度、速度、倾角和地理围栏；
- COM_DISARM_PRFLT 等自动解锁/预飞 disarm 参数；
- EKF 本地位置有效条件和位置质量阈值；
- 独立 kill switch/flight termination 的动作。

室内没有 GPS 时，必须确认 PX4 的 EKF 能持续输出有效 local position。推荐使用 VIO、光流、UWB 或外部定位。仅凭普通 GPS 的米级误差，接近本项目 3 m 单步移动上限，不适合作为室内精确定位。

## 4. 在伴随计算机上安装环境

以下命令以 Ubuntu/Debian 为例。设备厂商的 Jetson/ROS 镜像可能已经提供 Python 或 OpenCV；不要为了 AerialClaw 随意替换系统 ROS/PX4 依赖。

### 4.1 获取代码

~~~bash
git clone https://github.com/mandy0116/AerialClaw.git
cd AerialClaw
~~~

确保工作区包含当前 server.py、adapters/px4_adapter.py、skills/motor_skills.py 和 sim/real_sensor_bridge.py。

### 4.2 Python 环境

项目要求 Python 3.10 或更高版本。真机使用系统 ROS1 Noetic 的 rospy/消息绑定，
建议使用能看到系统包的虚拟环境：

~~~bash
python3.10 --version
python3.10 -m venv .venv --system-site-packages
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r requirements.txt
~~~

如果设备没有 python3.10-venv，先安装发行版对应的 venv 包。requirements.txt 会安装
Flask、OpenCV、LLM 客户端等依赖；rospy、mavros_msgs、geometry_msgs 等由 ROS1
Noetic 系统提供，不要通过 pip 替换它们。

验证基础依赖：

~~~bash
.venv/bin/python - <<'PY'
import cv2, flask, mavsdk, yaml
print("AerialClaw Python dependencies: OK")
print("OpenCV imported:", cv2.__version__)
PY
~~~

如果要使用前端源码构建：

~~~bash
cd ui
npm install
npm run build
cd ..
~~~

### 4.3 串口权限

先找出实际串口：

~~~bash
ls -l /dev/ttyAMA* /dev/ttyTHS* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
dmesg | grep -Ei 'tty(AMA|THS|USB|ACM)' | tail -30
~~~

把运行用户加入串口组后重新登录：

~~~bash
sudo usermod -aG dialout "$USER"
~~~

不要直接对串口设备使用过宽的 chmod 777。如果设备厂商使用专用串口服务，按其文档停用冲突服务或配置 udev 规则。

## 5. 配置 .env

复制模板并编辑：

~~~bash
cp .env.example .env
chmod 600 .env
~~~

### 5.1 ROS1/MAVROS 飞控和真机相机

示例（端口和波特率必须按设备修改）：

~~~dotenv
SIM_ADAPTER=mavros
MAVROS_NAMESPACE=/mavros

# 真机不用 Gazebo 传感器桥
AERIALCLAW_REAL_CAMERA_BRIDGE=1
REAL_CAMERA_GIMBAL_URL=rtsp://192.168.144.25:8554/live
GIMBAL_ROS_VERSION=1
GIMBAL_SERVICE_PREFIX=camera
ROS_SETUP=/opt/ros/noetic/setup.bash
~~~

启动前确认已有 MAVROS 节点连接飞控；不要让 AerialClaw 再启动 MAVSDK 直连，
也不要把仿真的 udp://:14540 当成真实飞控配置。

在 `bitcq@10.106.167.219` 实测：系统为 Ubuntu 20.04 + ROS1 Noetic，A8 Mini
服务节点为 `/camera_service`，服务位于 `/camera/*`，设备地址为
`192.168.144.25`，控制 TCP 端口为 `37260`，RTSP 为 `8554`。飞行控制默认
通过本仓库的 `MavrosAdapter` 使用现有 `/mavros` 节点，避免与
`/dev/ttyTHS0` 的 MAVROS 串口连接冲突。

### 5.2 DeepSeek 规划模型

当前项目可以使用 DeepSeek 文本规划：

~~~dotenv
ACTIVE_PROVIDER=deepseek
DEEPSEEK_API_KEY=填入你的Key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash
~~~

API Key 只放在本机 .env，不要提交到 Git、截图或日志。启动后可以用 /api/llm/config 查看 provider 和模型名，但不要公开响应中的密钥字段。

### 5.3 视觉模型

DeepSeek 文本规划不能自动理解 RTSP 图像。需要二选一：

- 配置 A40 vLLM/视觉服务：VLM_BACKEND=a40，并确保 A40 隧道或服务地址可达；
- 使用支持图像输入的 OpenAI-compatible VLM，填写 VLM_BACKEND=openai_compat、VLM_BASE_URL、VLM_API_KEY 和 VLM_MODEL。

如果暂时没有 VLM，可以先测试遥测和飞控控制，不要把 observe 成功当成视觉功能已验证。

### 5.4 检查配置是否被 shell 覆盖

python-dotenv 默认不会覆盖已经存在的 shell 环境变量。启动前检查：

~~~bash
env | grep -E '^(ACTIVE_PROVIDER|DEEPSEEK_|SIM_ADAPTER|MAVROS_NAMESPACE|AERIALCLAW_REAL_CAMERA_BRIDGE|REAL_CAMERA_|GIMBAL_ROS_VERSION|ROS_SETUP)'
~~~

## 6. 先做不启动电机的连接测试

建议拆桨执行以下步骤。

### 6.1 启动 AerialClaw

~~~bash
cd ~/AerialClaw
source .venv/bin/activate

export SIM_ADAPTER=mavros
export MAVROS_NAMESPACE=/mavros
export AERIALCLAW_REAL_CAMERA_BRIDGE=1
export GIMBAL_ROS_VERSION=1
export GIMBAL_SERVICE_PREFIX=camera
export ROS_SETUP=/opt/ros/noetic/setup.bash

.venv/bin/python server.py
~~~

如果变量已经写入 .env，可以直接执行 .venv/bin/python server.py。默认网页端口为 5001，可用 AERIALCLAW_PORT 修改。

### 6.2 检查服务和适配器

在另一终端执行：

~~~bash
curl -fsS http://127.0.0.1:5001/api/status
curl -fsS http://127.0.0.1:5001/api/adapter/status
curl -fsS http://127.0.0.1:5001/api/world
~~~

适配器必须明确显示 adapter=mavros 且 connected=true。不能因为网页加载成功就认为已经连接真实飞控；相机桥和控制适配器是两条独立链路。

检查日志：

~~~bash
curl -s http://127.0.0.1:5001/api/logs | python3 -m json.tool | tail -80
~~~

### 6.3 检查遥测

网页初始化系统后，确认以下值会持续更新：

- armed=false、in_air=false；
- 电池电压和百分比不是空值；
- 本地 NED 位置和航向有数值；
- 断开/重连时日志有明确提示。

如果 connected=false，优先检查串口权限、端口、波特率、PX4 MAVLink 实例和是否有其他程序占用串口。

### 6.4 检查相机

~~~bash
curl -fsS http://127.0.0.1:5001/api/sensor/status | python3 -m json.tool
curl -fsS http://127.0.0.1:5001/api/sensor/camera -o /tmp/aerialclaw-camera.jpg
file /tmp/aerialclaw-camera.jpg
~~~

相机状态中 frame_count 应持续增加。RTSP 打不开时检查相机 IP、网络、防火墙、OpenCV 的 FFmpeg 支持和相机是否已经上电。

## 7. 分级实机测试流程

不要直接从 AI 任务开始。每一级通过后再进入下一级。

### Level 0：设备和飞控（拆桨）

1. QGroundControl 能连接 PX4。
2. AerialClaw /api/adapter/status 为 mavros + connected=true。
3. 网页能看到电量、位置、航向和 in_air=false。
4. RC 模式开关、降落开关和 kill switch 已单独验证。

### Level 1：解锁和解除解锁（拆桨）

只验证 PX4 的 arm/disarm 和 preflight 检查，不执行旋翼飞行。确认网页操作和 RC 操作的状态一致。

### Level 2：低风险起飞/悬停/降落

先使用手动模式和防护措施：

~~~text
takeoff(altitude=1.0)
→ hover(5s)
→ land()
~~~

当前网页起飞默认值是 1.5m，但首飞建议明确填写 1.0m。观察 PX4 实际高度、姿态和落点，不要只看网页“成功”。

### Level 3：小范围移动

确认稳定悬停后，只测试单次 0.5–1 m 位移：

~~~text
takeoff(1.0m)
→ fly_relative(forward=0.5, speed=0.5)
→ hover
→ land
~~~

先用 get_position 观察 NED，再执行 fly_to。当前单次三维移动上限为 3 m，水平电子围栏半径为 8 m，不能把这两个上限当成首飞目标。

### Level 4：驾驶舱接管

在低高度、可控场地验证：

1. AerialClaw 驾驶舱发送速度，确认飞机响应；
2. 停止发送浏览器心跳，2 秒内应自动发送零速度；
3. 飞手拨 RC 模式开关退出 Offboard；
4. 确认 PX4 进入预先配置的手动/定高/定点模式；
5. 再由飞手人工降落。

软件 manual 模式不等于 PX4 飞行模式。真正接管以 RC/QGroundControl 的飞行模式为准。

### Level 5：AI 规划

只在前面各级都通过后启用 AI：

~~~text
起飞到1米，向前移动0.5米，悬停5秒，然后原地降落
~~~

确认每一步都经过人工观察。AI 任务结束后不能只看文本报告判断安全；应确认 in_air=false、电机已停止、实际位置和电量正常。

## 8. Offboard 接管和异常处理

fly_to、fly_relative、hover、change_altitude 和驾驶舱速度控制会使用 PX4 Offboard setpoint。飞手应把 RC 模式开关放在随时可拨到的位置。

异常时推荐顺序：

~~~text
发现异常
→ RC 切换退出 Offboard
→ 稳住飞机/人工降落
→ 必要时触发独立急停
→ 关闭 AerialClaw 任务并保存日志
~~~

kill switch 不是普通停止按钮；它可能立即切断电机并导致坠落，只能作为最后手段。网页停止按钮、2 秒速度心跳和 LLM 任务停止都不能替代 RC 接管。

## 9. 常见问题

### connected=false

- 串口路径或波特率错误；
- 用户不在 dialout 组；
- 串口被 QGroundControl、mavlink-router 或其他程序占用；
- PX4 没有在该链路输出 MAVLink；
- MAVROS 节点未启动，或 `/mavros/state.connected` 为 false。

### 网页能打开，但飞机不响应

确认 /api/adapter/status 的 adapter 是 mavros，而不是 mock。再看 PX4 是否允许解锁、是否处于正确模式、是否有有效 local position 和 failsafe 阻止。

### 起飞被拒绝

检查：

- 电量是否低于 30%；
- 当前是否已经在空中；
- 目标高度是否在 0.5–4 m；
- PX4 preflight check 是否通过；
- in_air 遥测是否正常。

### 起飞成功但 fly_to 被拒绝

检查目标是否超过：

- 单次三维位移 3 m；
- 起飞点水平围栏 8 m；
- 高度 0.5–4 m；
- 本地位置是否有效；
- 电量 30% 阈值。

### 相机 NO SIGNAL

~~~bash
ping <相机IP>
python -c "import cv2; print(cv2.getBuildInformation())" | grep -i FFMPEG
curl -s http://127.0.0.1:5001/api/sensor/status
~~~

检查 RTSP URL、相机网络和 OpenCV FFmpeg。相机画面恢复不代表飞控链路正常，两个状态要分别确认。

### observe 失败或没有描述

相机桥只负责图像，仍需要真正的视觉模型。确认 VLM_BACKEND、VLM endpoint、模型输入格式和 API Key；DeepSeek 文本规划模型本身不能替代 VLM。

### 连接断开后自动重连

服务端会尝试重连，但空中重连存在风险：PX4Adapter 可能重新记录相对坐标原点，应用层围栏参考点可能发生漂移。不要把自动重连当成空中自愈保证；优先由飞手 RC 接管并降落。

## 10. 停机、回滚和日志

正常结束任务时：

1. 确认 in_air=false；
2. 网页停止任务并退出 AI 模式；
3. 关闭 server.py；
4. 关闭相机和伴随计算机；
5. 断开电池；
6. 保存 PX4 ULog、AerialClaw 日志和测试记录。

停止服务可以使用终端 Ctrl+C。如果串口仍被占用，查找占用者：

~~~bash
lsof /dev/ttyAMA0
pgrep -af 'server.py|mavsdk|mavlink-router'
~~~

不要在飞行中直接拔串口或断伴随计算机电源；先由 RC 接管，再处理软件链路。

## 11. 最终首飞清单

- [ ] 螺旋桨、机架、电池和方向检查完成；
- [ ] RC 接管和独立急停已验证；
- [ ] PX4 failsafe、限高、限速和围栏已配置；
- [ ] EKF local position 稳定有效；
- [ ] /api/adapter/status 明确为 mavros / connected=true；
- [ ] 遥测位置、电量、航向和 in_air 正常；
- [ ] .env 中没有提交或打印 API Key；
- [ ] 起飞、悬停、降落已拆桨/系绳分级验证；
- [ ] 2 秒速度心跳停止行为已验证；
- [ ] RC 退出 Offboard 已验证；
- [ ] 真机相机和 VLM 已单独验证，或明确暂不使用视觉；
- [ ] 首次 AI 任务明确写出低高度、短距离和最终降落；
- [ ] 飞手、观察员和急停位置已明确。

