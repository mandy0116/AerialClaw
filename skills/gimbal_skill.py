"""
gimbal_skill.py — 云台控制硬技能

通过 photo_function ROS2 服务控制云台（仿真走 rclpy 桥接节点，真机走 SIYI A8 Mini，
服务 API 相同）。用 subprocess 调 `ros2 service call`，避免把 rclpy 引入 server.py 主进程。

服务（前缀 /common/camera/）:
  set_angle(yaw_angle, pitch_angle, roll_angle)   绝对转向，单位度
  rotate_gimbal(yaw_speed, pitch_speed)            速度式转向 -100..100
  manual_zoom(direction 1/-1/0)                    变焦：1=拉近/in, -1=拉远/out, 0=停
  center_gimbal()                                  回中
  get_current_zoom() / get_max_zoom() / get_attitude()  读状态
"""
import os
import subprocess
import time
import logging

from skills.base_skill import Skill, SkillResult

logger = logging.getLogger(__name__)

# The real test vehicle currently runs ROS1 Noetic and exposes the A8 Mini
# services below ``/camera``.  Keep ROS2 available for the Gazebo bridge by
# selecting the CLI at runtime instead of importing either client library.
#
# ``GIMBAL_ROS_VERSION=1`` (default) uses ``rosservice`` and
# ``photo_function/SetAngle``.  Set ``GIMBAL_ROS_VERSION=2`` for the existing
# ROS2 simulation bridge; its service type is ``photo_function/srv/SetAngle``.
GIMBAL_ROS_VERSION = os.getenv("GIMBAL_ROS_VERSION", "1").strip()
if GIMBAL_ROS_VERSION not in ("1", "2"):
    logger.warning("Unsupported GIMBAL_ROS_VERSION=%r; falling back to ROS1", GIMBAL_ROS_VERSION)
    GIMBAL_ROS_VERSION = "1"

ROS_SETUP = os.getenv(
    "ROS_SETUP",
    "/opt/ros/noetic/setup.bash" if GIMBAL_ROS_VERSION == "1" else "/opt/ros/humble/setup.bash",
)
# Optional overlay (for a locally-built photo_function package).  The real
# machine installs photo_function into /opt/ros/noetic, so this is empty by
# default; ROS2 deployments can still use IFC_PRO_DIR as before.
ROS_WS_SETUP = os.getenv("ROS_WS_SETUP", "")
IFC_PRO_DIR = os.getenv("IFC_PRO_DIR", "/home/ubuntu/ifc_pro")
if not ROS_WS_SETUP and GIMBAL_ROS_VERSION == "2":
    ROS_WS_SETUP = os.path.join(IFC_PRO_DIR, "install", "setup.bash")

PREFIX = os.getenv(
    "GIMBAL_SERVICE_PREFIX",
    "camera" if GIMBAL_ROS_VERSION == "1" else "common/camera",
).strip("/")
SERVICE_PACKAGE = os.getenv("GIMBAL_SERVICE_PACKAGE", "photo_function")
ZOOM_STEP_X = 0.5  # 仿真桥接每步 0.5x（与桥接 ZOOM_STEP 一致）


def _snake(name: str) -> str:
    """CamelCase → snake_case，用于服务 topic 名（SetAngle → set_angle）。"""
    import re
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _ros_call(srv_camel: str, payload: str, timeout: int = 20) -> tuple:
    """Call one photo_function service through the selected ROS CLI.

    Keeping this as a subprocess is intentional: importing ``rospy`` or
    ``rclpy`` into the Flask server would couple its Python runtime to the ROS
    installation.  The ROS1 and ROS2 command syntaxes differ, so the command
    and success parsing live in one small compatibility layer.
    """
    short = _snake(srv_camel)
    setup_parts = [f'source "{ROS_SETUP}" 2>/dev/null']
    if ROS_WS_SETUP:
        setup_parts.append(f'source "{ROS_WS_SETUP}" 2>/dev/null')
    if GIMBAL_ROS_VERSION == "2":
        setup_parts.append(
            f'ros2 service call /{PREFIX}/{short} '
            f'{SERVICE_PACKAGE}/srv/{srv_camel} "{payload}"'
        )
    else:
        # ROS1 rosservice infers the service type from the advertised service;
        # unlike ros2 it must not receive a type argument.
        setup_parts.append(f'rosservice call /{PREFIX}/{short} "{payload}"')
    cmd = "; ".join(setup_parts)
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"ROS{GIMBAL_ROS_VERSION} service call timeout"
    out = (p.stdout or "") + (p.stderr or "")
    # ROS1 prints ``success: True`` while ROS2 commonly prints
    # ``success=True``.  Accept either case and avoid treating a successful
    # command with a false response as success.
    import re
    success_match = re.search(r"\bsuccess\s*[:=]\s*(True|False|true|false)\b", out)
    response_ok = success_match is not None and success_match.group(1).lower() == "true"
    ok = p.returncode == 0 and response_ok
    return ok, out.strip()


class GimbalControl(Skill):
    name = "gimbal_control"
    description = (
        "控制云台：转向(point yaw/pitch 度, 可同时带 zoom_steps 放大)、"
        "变焦(zoom_in/zoom_out)、停变焦(zoom_stop)、回中(center)、速度转向(rotate)。"
        "yaw正=右、pitch正=上。'转向并放大'这类复合指令直接用 point + zoom_steps 一步完成。"
    )
    skill_type = "hard"
    robot_type = ["UAV"]
    preconditions = ["gimbal_bridge_or_photo_function_running"]
    input_schema = {
        "action": "point|zoom_in|zoom_out|zoom_stop|center|rotate",
        "yaw": "float, 偏航角(度, 正=右, 仅 action=point)",
        "pitch": "float, 俯仰角(度, 正=上, 仅 action=point)",
        "zoom_steps": "int, 变焦步数(每步0.5x放大; point 可选实现转向+放大; zoom_in/out 必填, 默认3)",
        "yaw_speed": "int, 速度转向yaw(-100..100, 仅 rotate)",
        "pitch_speed": "int, 速度转向pitch(-100..100, 仅 rotate)",
    }
    output_schema = {
        "action": "str", "ok": "bool", "current_zoom": "float", "yaw": "float", "pitch": "float",
    }
    cost = 1.0

    def check_precondition(self, robot_state: dict) -> bool:
        # 云台控制不依赖飞行状态，地面/空中都可转云台
        return True

    def execute(self, input_data: dict) -> SkillResult:
        t0 = time.time()
        action = (input_data.get("action") or "").strip().lower()
        try:
            if action == "point":
                yaw = float(input_data.get("yaw", 0.0))
                pitch = float(input_data.get("pitch", 0.0))
                # The deployed ROS1 photo_function/SetAngle.srv has only
                # yaw_angle and pitch_angle request fields.  The ROS2 bridge
                # kept a roll_angle field for its generated interface, so
                # include it only when using ROS2.
                angle_payload = f"{{yaw_angle: {yaw:.2f}, pitch_angle: {pitch:.2f}"
                if GIMBAL_ROS_VERSION == "2":
                    angle_payload += ", roll_angle: 0.0"
                angle_payload += "}"
                ok, out = _ros_call("SetAngle", angle_payload)
                msg = f"set_angle(yaw={yaw}, pitch={pitch})"
                # point 也支持 zoom_steps: 转向同时放大, 满足"转向左前方并放大一倍"这类
                # 复合指令。否则 agent 会用 point+zoom_steps 期望边转边变焦, 而 zoom_steps
                # 曾被静默忽略 → zoom 永不变, agent 陷入无效重试循环。
                zsteps = input_data.get("zoom_steps")
                if zsteps is not None:
                    try:
                        zsteps = max(0, int(zsteps))
                    except (TypeError, ValueError):
                        zsteps = 0
                    if zsteps > 0:
                        ok_z = True
                        for _ in range(zsteps):
                            ok_s, _ = _ros_call("ManualZoom", "{direction: 1}")
                            ok_z = ok_z and ok_s
                        _ros_call("ManualZoom", "{direction: 0}")  # 停
                        ok = ok and ok_z
                        msg += f" + zoom_in x{zsteps} 步"
            elif action == "zoom_in":
                steps = max(1, int(input_data.get("zoom_steps", 3)))
                ok_all = True
                for _ in range(steps):
                    ok_s, _ = _ros_call("ManualZoom", "{direction: 1}")
                    ok_all = ok_all and ok_s
                _ros_call("ManualZoom", "{direction: 0}")  # 停(真机需要; 仿真无副作用)
                ok, msg = ok_all, f"zoom_in x{steps} 步"
            elif action == "zoom_out":
                steps = max(1, int(input_data.get("zoom_steps", 3)))
                ok_all = True
                for _ in range(steps):
                    ok_s, _ = _ros_call("ManualZoom", "{direction: -1}")
                    ok_all = ok_all and ok_s
                _ros_call("ManualZoom", "{direction: 0}")
                ok, msg = ok_all, f"zoom_out x{steps} 步"
            elif action == "zoom_stop":
                ok, out = _ros_call("ManualZoom", "{direction: 0}")
                msg = "zoom_stop"
            elif action == "center":
                ok, out = _ros_call("CenterGimbal", "{}")
                msg = "center_gimbal"
            elif action == "rotate":
                ys = int(input_data.get("yaw_speed", 0))
                ps = int(input_data.get("pitch_speed", 0))
                ok, out = _ros_call("RotateGimbal", f"{{yaw_speed: {ys}, pitch_speed: {ps}}}")
                msg = f"rotate(yaw_speed={ys}, pitch_speed={ps})"
            else:
                return SkillResult(success=False, error_msg=f"未知 action: {action}", cost_time=0.0)

            # 读反馈：当前变焦 + 姿态
            cur_zoom = None
            att = None
            ok_z, out_z = _ros_call("GetCurrentZoom", "{}")
            if ok_z:
                cur_zoom = _parse_float(out_z, "current_zoom")
            ok_a, out_a = _ros_call("GetAttitude", "{}")
            if ok_a:
                att = _parse_attitude(out_a)

            output = {"action": action, "ok": ok, "current_zoom": cur_zoom}
            if att:
                output.update({"yaw": att.get("yaw"), "pitch": att.get("pitch")})
            return SkillResult(
                success=ok,
                output=output,
                error_msg="" if ok else (f"{msg} 失败: " + out[:200]),
                cost_time=round(time.time() - t0, 2),
                logs=[f"gimbal_control {msg} -> ok={ok}"],
            )
        except Exception as e:
            return SkillResult(success=False, error_msg=f"gimbal_control 异常: {e}", cost_time=round(time.time() - t0, 2))


def _parse_float(out: str, key: str):
    import re
    m = re.search(rf"{key}[:=]\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


def _parse_attitude(out: str):
    import re
    res = {}
    for k in ("yaw", "pitch", "roll"):
        m = re.search(rf"{k}[:=]\s*([-+0-9.eE]+)", out)
        if m:
            res[k] = float(m.group(1))
    return res
