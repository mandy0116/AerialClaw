# gimbal_control — 云台控制

真机默认使用 ROS1 Noetic 的 `photo_function` 服务（`/camera/*`）。仿真
桥接仍使用 ROS2；运行仿真桥接时设置 `GIMBAL_ROS_VERSION=2`，或直接使用
`scripts/start_gimbal_bridge.sh`。

控制机载云台的转向与变焦。底层通过 `photo_function` 服务：仿真走 ROS2
`rclpy` 桥接节点，真机走 ROS1 Noetic 的 SIYI A8 Mini 节点。

## 参数
- action: point | zoom_in | zoom_out | zoom_stop | center | rotate
- yaw: float 度，偏航角（正=右，负=左）。仅 action=point。
- pitch: float 度，俯仰角（正=上，负=下）。仅 action=point。
- zoom_steps: int，变焦步数（默认 3，每步 0.5x）。仅 zoom_in/zoom_out。
- yaw_speed: int -100..100，仅 rotate。
- pitch_speed: int -100..100，仅 rotate。

## 用法示例
- 转向左前方 30°：`{"action":"point", "yaw":-30, "pitch":10}`
- 放大变焦（3 步≈1.0→2.5x）：`{"action":"zoom_in", "zoom_steps":3}`
- 缩小变焦：`{"action":"zoom_out", "zoom_steps":3}`
- 停止变焦：`{"action":"zoom_stop"}`
- 云台回中：`{"action":"center"}`
- 速度转向（持续）：`{"action":"rotate", "yaw_speed":50, "pitch_speed":0}`

## 返回
- ok: 是否成功
- current_zoom: 当前变焦倍数
- yaw / pitch: 当前云台姿态（度）

## 搭配观察
云台相机方向是 `gimbal`。转向/变焦后用 observe 取景可看到云台画面：
`observe(direction="gimbal")` — 变焦后画面会被数字放大（中心裁剪）。

## 注意
- yaw 正=向右，pitch 正=向上（与 SIYI 一致）。
- 仿真桥接限位：yaw ±120°，pitch -80°~+30°，zoom 1.0~8.0x；真机 A8 Mini
  当前查询到最大变焦为 5.5x，最终限位由设备固件执行。
- 仿真桥接每步 manual_zoom = 0.5x；真机 SIYI 是连续变焦（需 zoom_stop 停）。
