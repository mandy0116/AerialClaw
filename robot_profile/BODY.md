# BODY.md -- 身体认知文档
# 自动生成于 2026-07-27 15:15:53
# 本文件由系统启动时自动生成，请勿手动编辑。

## 基本信息

- 适配器: px4
- 描述: PX4 SITL via MAVSDK (Gazebo, no AirSim)
- 支持载具类型: multirotor
- 连接状态: 已连接

## 运动能力

- 类型: 多旋翼无人机 (Multirotor)
- 坐标系: NED 本地坐标 (North-East-Down, 相对起飞点)
- 飞行速度: 室内最大 1.5 m/s (由安全包线强制限制)
- 旋转速度: 最大 45 deg/s (由安全包线强制限制)
- 高度范围: 室内离地 0.5-4m (由安全包线强制限制)
- 水平范围: 起飞点半径最大 8m，单次移动最大 3m
- 定位方式: 由当前适配器提供本地位置/GPS；室内需确认 local position 有效
- 安全策略: 室内严格模式，低电量、超高、超速和越界指令会被拒绝

## 传感器

### 摄像头 (x6)
- front: 0x0 @ 0.0 fps, FOV 80 度
- rear: 0x0 @ 0.0 fps, FOV 80 度
- left: 0x0 @ 0.0 fps, FOV 80 度
- right: 0x0 @ 0.0 fps, FOV 80 度
- down: 0x0 @ 0.0 fps, FOV 80 度
- gimbal: 0x0 @ 0.0 fps, FOV 80 度
- 安装方位: 前(0度)/后(180度)/左(270度)/右(90度), 均向下倾斜约15度
- 用途: 场景识别、目标检测、视觉导航

### 2D 激光雷达 (x1)
- 扫描点数: 1080
- 角度范围: -2.36 ~ 2.36 rad
- 测距范围: 0.1 ~ 30.0 m
- 安装位置: 机体顶部
- 用途: 障碍物检测、环境建图、避障

## 可用硬技能

- takeoff: 室内安全起飞到指定离地高度；默认 1.5m，最高 4m。 [参数: altitude]
- land: 安全降落：逐步下降并用下方深度探测地面，接近地面自动停止，不会穿模。 [参数: 无]
- fly_to: 室内点到点移动；使用 NED 坐标，单次不超过 3m，速度不超过 1.5m/s。 [参数: target_position, speed]
- fly_relative: 相对当前位置和朝向移动。使用前/后/左/右/上/下, 单位: 米。例如: forward=2 表示往前飞2米, right=1 表示往右飞1米。多个方向可以同时指定。 [参数: forward, right, up, speed]
- hover: 无人机在当前位置悬停指定时间。前提：无人机必须在空中。 [参数: duration]
- change_altitude: 在当前水平位置上调整飞行高度。前提：无人机必须在空中。打断后想往上飞用这个。 [参数: altitude]
- get_position: 获取无人机当前的 AirSim 世界坐标和 GPS 坐标。 [参数: 无]
- get_battery: 获取无人机电池电压和剩余电量。 [参数: 无]
- return_to_launch: 室内安全模式下原地降落；不执行可能爬升且依赖 GPS 的室外 RTL。 [参数: 无]
- look_around: 在当前位置原地旋转一圈, 观察四周环境。用于搜索目标、侦察地形。旋转期间 LiDAR 持续扫描。 [参数: duration]
- mark_location: 在当前位置设置标记点, 记录发现的目标或兴趣点。标记会保存到世界模型, 后续可以查看所有标记。 [参数: label, priority]
- get_marks: 查看已设置的所有标记点列表。 [参数: 无]
- orbit_inspect: 围绕指定建筑物进行逐层爬升巡检。给定建筑中心坐标和尺寸，在四周生成安全航点，逐层升高飞行。每个航点自动拍照并用VLM分析建筑外观（窗户破损/裂纹/异常）。完成后返回所有层的巡检报告。 [参数: center, radius, start_height, end_height, height_step, points_per_layer, speed, focus]
- gimbal_control: 控制云台：转向(point yaw/pitch 度, 可同时带 zoom_steps 放大)、变焦(zoom_in/zoom_out)、停变焦(zoom_stop)、回中(center)、速度转向(rotate)。yaw正=右、pitch正=上。'转向并放大'这类复合指令直接用 point + zoom_steps 一步完成。 [参数: action, yaw, pitch, zoom_steps, yaw_speed, pitch_speed]

## 硬件限制

- 电池: 有限续航, 低于 20% 应返航
- 通信: ROS1 Noetic + MAVROS（真机）
- 载荷: 无额外载荷能力 (仅传感器)
- 天气: 仿真环境无风雨影响, 真实环境需考虑
