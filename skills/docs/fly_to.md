# fly_to -- 飞行到指定位置

## 使用时机
需要无人机移动到特定位置时使用。这是最常用的移动技能。

## 参数
- target_position: [north, east, down]，当前适配器的 NED 坐标（米）
  - 必须先读取当前位置，并保持目标离地高度在 0.5-4m
  - 单次三维移动不超过 3m，目标水平位置不超过起飞点 8m
- speed: float，默认 1.0m/s，最高 1.5m/s

## 前提条件
- 无人机在空中 (必须先 takeoff)
- 电池满足室内安全阈值

## 坐标计算方法
1. 先调用 get_position，查看当前 position=[x,y,z] 和 ground_z 字段
2. 保持高度时直接沿用当前位置的 down
3. 改变高度优先使用 change_altitude(altitude=目标离地高度)
4. 水平目标与当前位置的三维距离不得超过 3m

## 执行流程
1. 获取当前位置
2. 计算到目标点的路径
3. 飞向目标（支持外部打断）
4. 到达后悬停并确认位置

## 安全机制
- 超时 150 秒未到达会返回失败
- 前方障碍物检测（深度摄像头）
- 支持外部 request_stop() 打断

## 注意事项
- ⚠️ 使用前必须先 get_position 知道当前位置！
- 不要假定地面 down 固定为某个值，以 get_position 的结果为准
- 飞行过程中不会自动避障，需要提前规划路径

## 输出
- arrived_position: [x, y, z] 实际到达的世界坐标
- distance_traveled: float 飞行水平距离（米）
- altitude: float 离地高度（正数，米）
- error_to_target: float 到达误差（米）

## 室内速度要求
- 建议使用 speed=1.0；任何更高值都会被限制到 1.5m/s
