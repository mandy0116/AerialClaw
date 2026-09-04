# get_position -- 获取当前位置

## 使用时机
需要知道无人机当前位置时使用。常用于规划前的状态确认。
⚠️ 在调用 fly_to 之前必须先调用此技能!

## 参数
无参数。

## 前提条件
- 无人机已连接

## 输出说明
返回的 position 是当前适配器的 NED 坐标 [north, east, down]:
- x: 北方向（正=北，负=南）
- y: 东方向（正=东，负=西）
- down: 向下为正；其参考原点由适配器决定
- altitude: 离地高度（正数，米）
- ground_z: 地面参考值（适配器支持时返回）

## 如何使用返回值
假设返回 position=[1.2, -0.5, -1.5]，altitude=1.5:
- 当前位置: 北1.2米，西0.5米，离地1.5米
- 如果要保持高度飞到别处，fly_to 的 down 继续使用 -1.5
- 如果要升高到离地2米，使用 change_altitude(altitude=2.0)

## 注意事项
- 不要跨适配器假定 down 的地面参考值
- altitude 字段才是离地高度（正数，米）
- 规划高度时以 altitude 字段为准

## 输出
- position: [x, y, z] 世界坐标
- ned: [x, y, z]（同 position，兼容旧字段名）
- altitude: float 离地高度（正数）
- ground_z: float 地面的z坐标（约-13）
- gps: {lat, lon, alt} GPS坐标（如可用）
