import math

from adapters import adapter_manager
from adapters.mock_adapter import MockAdapter
from adapters.sim_adapter import Position
from core.flight_safety import (
    check_target,
    get_flight_envelope,
    limit_body_velocity,
)
from skills.motor_skills import FlyRelative, ReturnToLaunch, Takeoff


def test_configuration_can_tighten_but_not_loosen_indoor_hard_caps(tmp_path):
    config = tmp_path / "safety.yaml"
    config.write_text(
        """
flight_envelope:
  max_speed: 99
  max_altitude: 99
  max_distance: 99
  max_command_distance: 99
  max_yaw_rate: 999
  min_battery: 1
  critical_battery: 1
  min_obstacle_distance: 0.1
  geofence_enabled: false
""",
        encoding="utf-8",
    )

    envelope = get_flight_envelope(config)
    assert envelope.max_speed == 1.5
    assert envelope.max_altitude == 4.0
    assert envelope.max_distance == 8.0
    assert envelope.max_command_distance == 3.0
    assert envelope.max_yaw_rate == 45.0
    assert envelope.min_battery == 30.0
    assert envelope.critical_battery == 15.0
    assert envelope.min_obstacle_distance == 2.0
    assert envelope.geofence_enabled is True


def test_target_check_rejects_long_steps_altitude_and_geofence():
    current = Position(0, 0, -1.5)
    assert check_target(current, 2, 0, -1.5, 1.5).ok
    assert "单次移动" in check_target(current, 4, 0, -1.5, 1.5).message
    assert "目标高度" in check_target(current, 0, 0, -5, 1.5).message

    edge = Position(7, 0, -1.5)
    assert "电子围栏" in check_target(edge, 9, 0, -1.5, 1.5).message


def test_manual_velocity_is_scaled_as_a_vector_and_yaw_is_limited():
    fwd, right, down, yaw, limited = limit_body_velocity(3, 4, 0, 90)
    assert limited
    assert math.isclose(math.sqrt(fwd * fwd + right * right + down * down), 1.5)
    assert yaw == 45.0


def test_takeoff_rejects_unsafe_altitude_and_low_battery():
    adapter = MockAdapter()
    adapter.connect()
    adapter_manager._adapter = adapter

    too_high = Takeoff().execute({"altitude": 5})
    assert not too_high.success
    assert not adapter.is_in_air()

    adapter._battery = (10.5, 0.2)
    low_battery = Takeoff().execute({"altitude": 1.5})
    assert not low_battery.success
    assert "电量" in low_battery.error_msg
    assert not adapter.is_in_air()


def test_fly_relative_rejects_a_step_over_three_metres():
    adapter = MockAdapter()
    adapter.connect()
    adapter.takeoff(1.5)
    adapter_manager._adapter = adapter

    result = FlyRelative().execute({"forward": 3.1, "speed": 15})
    assert not result.success
    assert "单次移动" in result.error_msg
    assert adapter.get_position().north == 0


def test_indoor_return_to_launch_lands_in_place_even_on_low_battery():
    class TrackingAdapter(MockAdapter):
        rtl_called = False

        def return_to_launch(self):
            self.rtl_called = True
            return super().return_to_launch()

    adapter = TrackingAdapter()
    adapter.connect()
    adapter.takeoff(1.5)
    adapter._position = Position(2, 1, -1.5)
    adapter._battery = (10.0, 0.1)
    adapter_manager._adapter = adapter

    result = ReturnToLaunch().execute({})
    assert result.success
    assert result.output["safety_mode"] == "indoor_land_in_place"
    assert not adapter.rtl_called
    assert not adapter.is_in_air()
    assert (adapter.get_position().north, adapter.get_position().east) == (2, 1)


def test_cockpit_velocity_entry_point_enforces_vector_limit():
    import server

    previous_adapter = adapter_manager._adapter
    previous_initialized = server.state.initialized
    previous_mode = server.state.mode
    adapter = MockAdapter()
    adapter.connect()
    adapter.takeoff(1.5)
    adapter_manager._adapter = adapter
    server.state.initialized = True
    server.state.mode = "manual"
    client = server.socketio.test_client(server.app)
    try:
        client.emit(
            "velocity_control",
            {"forward": 3, "right": 4, "down": 0, "yaw_rate": 90},
        )
        events = [e for e in client.get_received() if e["name"] == "velocity_result"]
        payload = events[-1]["args"][0]
        applied = payload["applied"]
        magnitude = math.sqrt(
            applied["forward"] ** 2
            + applied["right"] ** 2
            + applied["down"] ** 2
        )
        assert payload["ok"]
        assert payload["limited"]
        assert math.isclose(magnitude, 1.5)
        assert applied["yaw_rate"] == 45.0
    finally:
        client.disconnect()
        with server.state._velocity_lock:
            server.state._velocity_deadline = 0.0
        server.state.initialized = previous_initialized
        server.state.mode = previous_mode
        adapter_manager._adapter = previous_adapter
