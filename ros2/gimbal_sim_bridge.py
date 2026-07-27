#!/usr/bin/env python3
"""
gimbal_sim_bridge.py — 仿真云台桥接节点

把 photo_function 的 ROS2 云台控制服务翻译成 Gazebo Transport 关节/变焦命令，
使仿真云台与真实 SIYI A8 Mini 云台走同一套 ROS 服务 API（仿真/真机互换）。

实现的 photo_function 服务（前缀 common/camera/，与 photo_function 实际代码一致）:
  set_angle         SetAngle(yaw_angle, pitch_angle, roll_angle)        → gz gimbal/yaw_cmd, gimbal/pitch_cmd (Double, 弧度)
  rotate_gimbal     RotateGimbal(yaw_speed, pitch_speed)                 → 相对步进 yaw/pitch (弧度)
  manual_zoom       ManualZoom(direction 1/-1/0)                         → 维护 zoom_level, 发 gimbal/zoom_level (Double)
  get_current_zoom  → zoom_level
  get_max_zoom      → 8.0
  get_attitude      → 返回最近指令的 yaw/pitch (度)
  center_gimbal     → set_angle(0, 0)

环境（由启动脚本设置）:
  source /opt/ros/humble/setup.bash
  source <ifc_pro>/install/setup.bash   # photo_function srv
  export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python   # gz 绑定需要
"""
import math
import threading
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from photo_function.srv import (
    SetAngle, RotateGimbal, ManualZoom, GetCurrentZoom, GetMaxZoom,
    GetAttitude, CenterGimbal,
)

import gz.transport13 as gzt
from gz.msgs10 import double_pb2

# 云台物理限位 (弧度) — 仿 SIYI A8 Mini
YAW_MIN, YAW_MAX = -2.0944, 2.0944         # ±120°
PITCH_MIN, PITCH_MAX = -1.3963, 0.5236    # -80° ~ +30°
ZOOM_MIN, ZOOM_MAX = 1.0, 8.0
ZOOM_STEP = 0.5
ROTATE_SCALE = 0.02                         # rotate_gimbal 速度 -> 弧度步进系数

# 服务名前缀（与 photo_function 代码一致；README 的 /camera/ 过时勿用）
PREFIX = "common/camera"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class GimbalSimBridge(Node):
    def __init__(self):
        super().__init__("gimbal_sim_bridge")
        # gz transport node + publishers
        self._gz = gzt.Node()
        self._pub_yaw = self._gz.advertise("gimbal/yaw_cmd", double_pb2.Double)
        self._pub_pitch = self._gz.advertise("gimbal/pitch_cmd", double_pb2.Double)
        self._pub_zoom = self._gz.advertise("gimbal/zoom_level", double_pb2.Double)
        self._lock = threading.Lock()
        self._yaw = 0.0      # 当前指令 yaw (弧度)
        self._pitch = 0.0    # 当前指令 pitch (弧度)
        self._zoom = 1.0     # 当前变焦倍数
        self._publish_all()

        # ROS2 服务（名字严格用 common/camera/<short>）
        self.create_service(SetAngle, f"{PREFIX}/set_angle", self._set_angle)
        self.create_service(RotateGimbal, f"{PREFIX}/rotate_gimbal", self._rotate)
        self.create_service(ManualZoom, f"{PREFIX}/manual_zoom", self._manual_zoom)
        self.create_service(GetCurrentZoom, f"{PREFIX}/get_current_zoom", self._get_current_zoom)
        self.create_service(GetMaxZoom, f"{PREFIX}/get_max_zoom", self._get_max_zoom)
        self.create_service(GetAttitude, f"{PREFIX}/get_attitude", self._get_attitude)
        self.create_service(CenterGimbal, f"{PREFIX}/center_gimbal", self._center)

        self.get_logger().info(
            f"gimbal_sim_bridge ready. services under /{PREFIX}/  gz topics: "
            f"gimbal/yaw_cmd, gimbal/pitch_cmd, gimbal/zoom_level")

    # ── gz 发布 ──────────────────────────────────────────────
    def _publish_all(self):
        with self._lock:
            self._pub_yaw.publish(double_pb2.Double(data=self._yaw))
            self._pub_pitch.publish(double_pb2.Double(data=self._pitch))
            self._pub_zoom.publish(double_pb2.Double(data=self._zoom))

    # ── 服务回调 ─────────────────────────────────────────────
    def _set_angle(self, req, resp):
        # SIYI A8: yaw=偏航(正=右), pitch=俯仰(正=上)。roll 在 A8 后端忽略。
        with self._lock:
            self._yaw = _clamp(math.radians(req.yaw_angle), YAW_MIN, YAW_MAX)
            self._pitch = _clamp(math.radians(req.pitch_angle), PITCH_MIN, PITCH_MAX)
            y, p = self._yaw, self._pitch
        self._pub_yaw.publish(double_pb2.Double(data=y))
        self._pub_pitch.publish(double_pb2.Double(data=p))
        resp.success = True
        self.get_logger().info(f"set_angle yaw={req.yaw_angle:.1f} pitch={req.pitch_angle:.1f} -> ({y:.3f},{p:.3f}) rad")
        return resp

    def _rotate(self, req, resp):
        # 速度式：每次调用按速度方向相对步进一段；speed=0 不动
        with self._lock:
            self._yaw = _clamp(self._yaw + req.yaw_speed * ROTATE_SCALE, YAW_MIN, YAW_MAX)
            self._pitch = _clamp(self._pitch + req.pitch_speed * ROTATE_SCALE, PITCH_MIN, PITCH_MAX)
            y, p = self._yaw, self._pitch
        self._pub_yaw.publish(double_pb2.Double(data=y))
        self._pub_pitch.publish(double_pb2.Double(data=p))
        resp.success = True
        return resp

    def _manual_zoom(self, req, resp):
        with self._lock:
            if req.direction > 0:
                self._zoom = _clamp(self._zoom + ZOOM_STEP, ZOOM_MIN, ZOOM_MAX)
            elif req.direction < 0:
                self._zoom = _clamp(self._zoom - ZOOM_STEP, ZOOM_MIN, ZOOM_MAX)
            # direction == 0: stop, 保持当前 zoom
            z = self._zoom
        self._pub_zoom.publish(double_pb2.Double(data=z))
        resp.success = True
        self.get_logger().info(f"manual_zoom dir={req.direction} -> zoom={z:.1f}x")
        return resp

    def _get_current_zoom(self, req, resp):
        with self._lock:
            resp.success = True
            resp.current_zoom = float(self._zoom)
        return resp

    def _get_max_zoom(self, req, resp):
        resp.success = True
        resp.max_zoom = ZOOM_MAX
        return resp

    def _get_attitude(self, req, resp):
        with self._lock:
            resp.success = True
            resp.yaw = math.degrees(self._yaw)
            resp.pitch = math.degrees(self._pitch)
            resp.roll = 0.0
            resp.yaw_velocity = 0.0
            resp.pitch_velocity = 0.0
            resp.roll_velocity = 0.0
        return resp

    def _center(self, req, resp):
        with self._lock:
            self._yaw = 0.0
            self._pitch = 0.0
        self._pub_yaw.publish(double_pb2.Double(data=0.0))
        self._pub_pitch.publish(double_pb2.Double(data=0.0))
        resp.success = True
        return resp


def main():
    rclpy.init()
    node = GimbalSimBridge()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()