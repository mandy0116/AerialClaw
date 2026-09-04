"""Runtime-enforced flight envelope for indoor operation.

The YAML file is operator-facing configuration.  The limits below are also
capped in code so a missing, malformed, or accidentally loosened file cannot
turn an indoor test into an unrestricted flight.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import yaml


_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "safety_config.yaml"

# Absolute indoor ceilings. Configuration may tighten these, never loosen them.
_HARD_MAX_SPEED = 1.5
_HARD_MAX_ALTITUDE = 4.0
_HARD_MAX_DISTANCE = 8.0
_HARD_MAX_COMMAND_DISTANCE = 3.0
_HARD_MAX_YAW_RATE = 45.0


@dataclass(frozen=True)
class FlightEnvelope:
    max_speed: float = _HARD_MAX_SPEED
    max_altitude: float = _HARD_MAX_ALTITUDE
    min_altitude: float = 0.5
    max_distance: float = _HARD_MAX_DISTANCE
    max_command_distance: float = _HARD_MAX_COMMAND_DISTANCE
    min_battery: float = 30.0
    critical_battery: float = 15.0
    heartbeat_timeout: float = 2.0
    max_tilt_angle: float = 15.0
    max_yaw_rate: float = _HARD_MAX_YAW_RATE
    min_obstacle_distance: float = 2.0
    geofence_enabled: bool = True


@dataclass(frozen=True)
class SafetyCheck:
    ok: bool
    message: str = ""


def _positive_number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and number > 0 else default


def get_flight_envelope(config_path: Path | str | None = None) -> FlightEnvelope:
    """Load the configured envelope and apply non-bypassable indoor caps."""
    path = Path(config_path) if config_path is not None else _CONFIG_PATH
    raw: dict[str, Any] = {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = loaded.get("flight_envelope", {}) or {}
    except (OSError, yaml.YAMLError, AttributeError):
        # Fail closed to the hard-coded indoor defaults.
        raw = {}

    min_altitude = max(_positive_number(raw.get("min_altitude"), 0.5), 0.5)
    max_altitude = min(
        _positive_number(raw.get("max_altitude"), _HARD_MAX_ALTITUDE),
        _HARD_MAX_ALTITUDE,
    )
    if min_altitude >= max_altitude:
        min_altitude = min(0.5, max_altitude / 2)

    min_battery = min(max(_positive_number(raw.get("min_battery"), 30.0), 30.0), 100.0)
    critical_battery = min(
        max(_positive_number(raw.get("critical_battery"), 15.0), 15.0),
        min_battery,
    )

    return FlightEnvelope(
        max_speed=min(_positive_number(raw.get("max_speed"), _HARD_MAX_SPEED), _HARD_MAX_SPEED),
        max_altitude=max_altitude,
        min_altitude=min_altitude,
        max_distance=min(
            _positive_number(raw.get("max_distance"), _HARD_MAX_DISTANCE),
            _HARD_MAX_DISTANCE,
        ),
        max_command_distance=min(
            _positive_number(
                raw.get("max_command_distance"), _HARD_MAX_COMMAND_DISTANCE
            ),
            _HARD_MAX_COMMAND_DISTANCE,
        ),
        min_battery=min_battery,
        critical_battery=critical_battery,
        heartbeat_timeout=min(_positive_number(raw.get("heartbeat_timeout"), 2.0), 2.0),
        max_tilt_angle=min(_positive_number(raw.get("max_tilt_angle"), 15.0), 15.0),
        max_yaw_rate=min(
            _positive_number(raw.get("max_yaw_rate"), _HARD_MAX_YAW_RATE),
            _HARD_MAX_YAW_RATE,
        ),
        min_obstacle_distance=max(
            _positive_number(raw.get("min_obstacle_distance"), 2.0), 2.0
        ),
        geofence_enabled=True,
    )


def normalize_battery_percent(value: Any) -> float | None:
    """Normalize adapters that report either 0..1 or 0..100 battery values."""
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(percent) or percent < 0:
        return None
    if percent <= 1.0:
        percent *= 100.0
    return min(percent, 100.0)


def check_battery(value: Any, envelope: FlightEnvelope | None = None) -> SafetyCheck:
    envelope = envelope or get_flight_envelope()
    percent = normalize_battery_percent(value)
    if percent is None:
        return SafetyCheck(False, "无法读取有效电量，室内安全模式禁止非紧急飞行")
    if percent < envelope.critical_battery:
        return SafetyCheck(False, f"电量 {percent:.0f}% 已达到紧急降落阈值")
    if percent < envelope.min_battery:
        return SafetyCheck(False, f"电量 {percent:.0f}% 低于飞行阈值 {envelope.min_battery:.0f}%")
    return SafetyCheck(True)


def check_altitude(altitude: Any, envelope: FlightEnvelope | None = None) -> SafetyCheck:
    envelope = envelope or get_flight_envelope()
    try:
        altitude = float(altitude)
    except (TypeError, ValueError):
        return SafetyCheck(False, "高度必须是有限数值")
    if not math.isfinite(altitude):
        return SafetyCheck(False, "高度必须是有限数值")
    if altitude < envelope.min_altitude:
        return SafetyCheck(False, f"目标高度 {altitude:.2f}m 低于室内下限 {envelope.min_altitude:.2f}m")
    if altitude > envelope.max_altitude:
        return SafetyCheck(False, f"目标高度 {altitude:.2f}m 超过室内上限 {envelope.max_altitude:.2f}m")
    return SafetyCheck(True)


def check_target(
    current_position: Any,
    target_north: Any,
    target_east: Any,
    target_down: Any,
    current_altitude: Any,
    envelope: FlightEnvelope | None = None,
    home_north: Any = 0.0,
    home_east: Any = 0.0,
) -> SafetyCheck:
    """Validate one NED target without assuming a particular world Z origin."""
    envelope = envelope or get_flight_envelope()
    try:
        cn, ce, cd = (
            float(current_position.north),
            float(current_position.east),
            float(current_position.down),
        )
        tn, te, td = float(target_north), float(target_east), float(target_down)
        current_altitude = float(current_altitude)
        home_north, home_east = float(home_north), float(home_east)
    except (TypeError, ValueError, AttributeError):
        return SafetyCheck(False, "目标位置必须包含有效的 NED 数值")
    if not all(
        math.isfinite(v)
        for v in (cn, ce, cd, tn, te, td, current_altitude, home_north, home_east)
    ):
        return SafetyCheck(False, "目标位置必须包含有限数值")

    target_altitude = current_altitude + cd - td
    altitude_check = check_altitude(target_altitude, envelope)
    if not altitude_check.ok:
        return altitude_check

    command_distance = math.dist((cn, ce, cd), (tn, te, td))
    if command_distance > envelope.max_command_distance:
        return SafetyCheck(
            False,
            f"单次移动 {command_distance:.2f}m 超过室内上限 {envelope.max_command_distance:.2f}m",
        )
    home_distance = math.hypot(tn - home_north, te - home_east)
    if envelope.geofence_enabled and home_distance > envelope.max_distance:
        return SafetyCheck(
            False,
            f"目标距起飞点 {home_distance:.2f}m 超过电子围栏 {envelope.max_distance:.2f}m",
        )
    return SafetyCheck(True)


def limit_speed(value: Any, envelope: FlightEnvelope | None = None) -> tuple[float, bool]:
    """Return a safe positive speed and whether the request was limited."""
    envelope = envelope or get_flight_envelope()
    try:
        requested = float(value)
    except (TypeError, ValueError):
        requested = envelope.max_speed
    if not math.isfinite(requested) or requested <= 0:
        requested = envelope.max_speed
    safe = min(requested, envelope.max_speed)
    return safe, not math.isclose(safe, requested)


def limit_body_velocity(
    forward: Any,
    right: Any,
    down: Any,
    yaw_rate: Any,
    envelope: FlightEnvelope | None = None,
) -> tuple[float, float, float, float, bool]:
    """Scale the translation vector and yaw rate into the indoor envelope."""
    envelope = envelope or get_flight_envelope()
    values = []
    for value in (forward, right, down, yaw_rate):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        values.append(number if math.isfinite(number) else 0.0)
    fwd, right, down, yaw = values
    magnitude = math.sqrt(fwd * fwd + right * right + down * down)
    limited = False
    if magnitude > envelope.max_speed:
        scale = envelope.max_speed / magnitude
        fwd, right, down = fwd * scale, right * scale, down * scale
        limited = True
    safe_yaw = max(-envelope.max_yaw_rate, min(yaw, envelope.max_yaw_rate))
    limited = limited or not math.isclose(safe_yaw, yaw)
    return fwd, right, down, safe_yaw, limited
