from types import SimpleNamespace

import skills.gimbal_skill as gimbal


def _fake_run_factory(calls, stdout="success: True\n"):
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return fake_run


def test_ros1_call_uses_rosservice_and_ros1_type(monkeypatch):
    calls = []
    monkeypatch.setattr(gimbal, "GIMBAL_ROS_VERSION", "1")
    monkeypatch.setattr(gimbal, "ROS_SETUP", "/opt/ros/noetic/setup.bash")
    monkeypatch.setattr(gimbal, "ROS_WS_SETUP", "")
    monkeypatch.setattr(gimbal, "PREFIX", "camera")
    monkeypatch.setattr(gimbal.subprocess, "run", _fake_run_factory(calls))

    ok, output = gimbal._ros_call("SetAngle", "{yaw_angle: 5.0, pitch_angle: 2.0}")

    assert ok is True
    assert output == "success: True"
    command = calls[0][0][2]
    assert "source \"/opt/ros/noetic/setup.bash\"" in command
    assert "rosservice call /camera/set_angle" in command
    assert "photo_function/SetAngle" not in command


def test_ros2_call_keeps_ros2_service_type(monkeypatch):
    calls = []
    monkeypatch.setattr(gimbal, "GIMBAL_ROS_VERSION", "2")
    monkeypatch.setattr(gimbal, "ROS_SETUP", "/opt/ros/humble/setup.bash")
    monkeypatch.setattr(gimbal, "ROS_WS_SETUP", "/opt/ros/ws/install/setup.bash")
    monkeypatch.setattr(gimbal, "PREFIX", "common/camera")
    monkeypatch.setattr(gimbal, "SERVICE_PACKAGE", "photo_function")
    monkeypatch.setattr(gimbal.subprocess, "run", _fake_run_factory(calls, "success=True\n"))

    ok, _ = gimbal._ros_call("GetCurrentZoom", "{}")

    assert ok is True
    command = calls[0][0][2]
    assert "source \"/opt/ros/humble/setup.bash\"" in command
    assert "source \"/opt/ros/ws/install/setup.bash\"" in command
    assert "ros2 service call /common/camera/get_current_zoom photo_function/srv/GetCurrentZoom" in command


def test_ros1_point_omits_ros2_only_roll_field(monkeypatch):
    payloads = []

    def fake_call(name, payload, timeout=20):
        payloads.append((name, payload))
        if name == "GetCurrentZoom":
            return True, "success: True\ncurrent_zoom: 1.0"
        if name == "GetAttitude":
            return True, "success: True\nyaw: 0.0\npitch: 0.0"
        return True, "success: True"

    monkeypatch.setattr(gimbal, "GIMBAL_ROS_VERSION", "1")
    monkeypatch.setattr(gimbal, "_ros_call", fake_call)

    result = gimbal.GimbalControl().execute({"action": "point", "yaw": 10, "pitch": -5})

    assert result.success is True
    assert payloads[0] == ("SetAngle", "{yaw_angle: 10.00, pitch_angle: -5.00}")
