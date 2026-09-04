# 飞行安全经验 (Flight Safety Experience)

## 核心经验（从多次任务失败中总结）

### 经验1：永远先了解自己的状态
- 执行任何飞行动作前，先调用 `get_position` 获取当前位置
- 查看返回的 position=[x,y,z] 和 ground_z 字段
- 第一个动作永远是 get_position

### 经验2：高度决定安全
- 室内离地高度必须保持在 0.5-4m
- 一般巡航建议 1.0-2.0m，并以实际屋顶净空为准
- 单次移动不得超过 3m，水平电子围栏半径为 8m
- 不要用升高作为默认避障策略；接近上限时横向绕行或降落

### 经验3：fly_to 使用世界坐标
- fly_to 给 [x, y, z]，z 必须比地面 z 更负
- 保持高度时沿用 get_position 返回的 down
- 调整高度时使用 change_altitude 的 altitude 目标值

### 经验4：遇到障碍物的处理
- fly_to 返回"障碍物"错误 → 先 observe 看什么方向有障碍
- 然后用 fly_relative 绕行或 change_altitude 升高
- 不要重复同一个失败的 fly_to

### 经验5：任务节奏
- 飞到新位置 → observe → report → 再飞
- 不要连续飞多个点不观察
- 每个观察点都 report，操作员需要实时了解情况
