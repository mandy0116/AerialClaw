"""ROS1/MAVROS flight adapter for real PX4 vehicles.

The real test computer already runs MAVROS and owns the FCU serial link.  This
adapter deliberately talks to MAVROS topics/services instead of opening the
PX4 UART itself, so there is a single MAVLink owner on the companion computer.
ROS imports are lazy: simulation users do not need rospy or mavros_msgs.
"""
import math
import threading
import time
from adapters.sim_adapter import SimAdapter, Position, GPSPosition, VehicleState, ActionResult


class MavrosAdapter(SimAdapter):
    name = "mavros"
    description = "ROS1 Noetic MAVROS adapter for real PX4"
    supported_vehicles = ["multirotor"]

    def __init__(self):
        self._ns = "/mavros"
        self._connected = False
        self._armed = False
        self._in_air = False
        self._mode = "UNKNOWN"
        self._pos = Position()
        self._gps = GPSPosition()
        self._vel = [0.0, 0.0, 0.0]
        self._heading = 0.0
        self._battery_v = 0.0
        self._battery_pct = 0.0
        self._home = Position()
        self._have_home = False
        self._have_pose = False
        self._extended_in_air = None
        self._stop_req = False
        self.is_flying = False
        self._last_error = ""
        self._ros = None
        self._pub_vel = None
        self._pub_pos = None
        self._endpoints_ready = False
        self._lock = threading.Lock()

    def connect(self, connection_str="", timeout=15.0) -> bool:
        try:
            import rospy
            from mavros_msgs.msg import State, ExtendedState
            from geometry_msgs.msg import PoseStamped, TwistStamped
            from sensor_msgs.msg import NavSatFix, BatteryState
            from std_msgs.msg import Float64
            from mavros_msgs.srv import CommandBool, CommandTOL, CommandLong, SetMode
        except Exception as exc:
            self._last_error = f"ROS1 MAVROS Python bindings unavailable: {exc}"
            return False

        self._ros = rospy
        if connection_str:
            self._ns = "/" + str(connection_str).strip("/")
        n = self._ns
        if not rospy.core.is_initialized():
            rospy.init_node("aerialclaw_mavros_adapter", anonymous=True, disable_signals=True)
        # Keep one set of ROS endpoints across reconnect attempts.  The server's
        # telemetry loop may call connect() again when MAVROS briefly drops;
        # recreating subscribers there would otherwise duplicate callbacks and
        # reset the local coordinate origin in mid-flight.
        if not self._endpoints_ready:
            self._pub_vel = rospy.Publisher(f"{n}/setpoint_velocity/cmd_vel", TwistStamped, queue_size=10)
            self._pub_pos = rospy.Publisher(f"{n}/setpoint_position/local", PoseStamped, queue_size=10)
            rospy.Subscriber(f"{n}/state", State, self._state_cb, queue_size=1)
            rospy.Subscriber(f"{n}/extended_state", ExtendedState, self._extended_state_cb, queue_size=1)
            rospy.Subscriber(f"{n}/local_position/pose", PoseStamped, self._pose_cb, queue_size=1)
            rospy.Subscriber(f"{n}/local_position/velocity_local", TwistStamped, self._vel_cb, queue_size=1)
            rospy.Subscriber(f"{n}/global_position/global", NavSatFix, self._gps_cb, queue_size=1)
            rospy.Subscriber(f"{n}/global_position/rel_alt", Float64, self._rel_alt_cb, queue_size=1)
            rospy.Subscriber(f"{n}/battery", BatteryState, self._battery_cb, queue_size=1)
            rospy.Subscriber(f"{n}/global_position/compass_hdg", Float64, self._heading_cb, queue_size=1)
            self._arm_srv = rospy.ServiceProxy(f"{n}/cmd/arming", CommandBool)
            self._takeoff_srv = rospy.ServiceProxy(f"{n}/cmd/takeoff", CommandTOL)
            self._land_srv = rospy.ServiceProxy(f"{n}/cmd/land", CommandTOL)
            self._command_srv = rospy.ServiceProxy(f"{n}/cmd/command", CommandLong)
            self._mode_srv = rospy.ServiceProxy(f"{n}/set_mode", SetMode)
            self._endpoints_ready = True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not rospy.is_shutdown():
            if self._connected and self._have_pose:
                return True
            time.sleep(0.1)
        self._last_error = "MAVROS /mavros/state did not report connected"
        return False

    def disconnect(self):
        self._connected = False
        self._publish_velocity(0.0, 0.0, 0.0, 0.0)

    def is_connected(self): return self._connected
    def is_armed(self): return self._armed
    def is_in_air(self): return self._in_air
    def get_position(self):
        with self._lock:
            return Position(self._pos.north - self._home.north, self._pos.east - self._home.east, self._pos.down - self._home.down)
    def get_gps(self):
        with self._lock:
            return GPSPosition(self._gps.lat, self._gps.lon, self._gps.alt)
    def get_battery(self):
        with self._lock:
            return self._battery_v, self._battery_pct
    def get_state(self):
        with self._lock:
            gps = GPSPosition(self._gps.lat, self._gps.lon, self._gps.alt)
            armed, in_air, mode = self._armed, self._in_air, self._mode
            battery_v, battery_pct, heading = self._battery_v, self._battery_pct, self._heading
            velocity = list(self._vel)
        return VehicleState(armed, in_air, mode, self.get_position(), gps,
                            battery_v, battery_pct, heading, velocity)

    def _state_cb(self, msg):
        with self._lock:
            self._connected, self._armed, self._mode = bool(msg.connected), bool(msg.armed), str(msg.mode)
        self._update_in_air()

    def _extended_state_cb(self, msg):
        # ExtendedState is the authoritative landed/in-air signal.  Keep a
        # height-based fallback for FCU/firmware versions that publish an
        # undefined landed_state.
        landed = getattr(msg, "landed_state", 0)
        in_air_value = getattr(msg, "LANDED_STATE_IN_AIR", 2)
        takeoff_value = getattr(msg, "LANDED_STATE_TAKEOFF", 3)
        landing_value = getattr(msg, "LANDED_STATE_LANDING", 4)
        with self._lock:
            self._extended_in_air = (
                True if landed in (in_air_value, takeoff_value, landing_value)
                else False if landed == getattr(msg, "LANDED_STATE_ON_GROUND", 1)
                else None
            )
        self._update_in_air()

    def _update_in_air(self):
        with self._lock:
            if self._extended_in_air is not None:
                self._in_air = self._extended_in_air
            else:
                self._in_air = self._armed and self._have_home and abs(self._pos.down - self._home.down) > 0.25

    def _pose_cb(self, msg):
        # MAVROS local pose is ENU; AerialClaw exposes NED.
        with self._lock:
            pos = Position(msg.pose.position.y, msg.pose.position.x, -msg.pose.position.z)
            if not self._have_home:
                self._home = Position(pos.north, pos.east, pos.down)
                self._have_home = True
            self._pos = pos
            self._have_pose = True
        self._update_in_air()

    def _vel_cb(self, msg):
        with self._lock:
            self._vel = [msg.twist.linear.y, msg.twist.linear.x, -msg.twist.linear.z]

    def _gps_cb(self, msg):
        # Keep altitude relative to home, matching PX4Adapter's contract;
        # /global_position/rel_alt supplies the relative value asynchronously.
        with self._lock:
            self._gps = GPSPosition(msg.latitude, msg.longitude, self._gps.alt)

    def _rel_alt_cb(self, msg):
        with self._lock:
            self._gps.alt = float(msg.data)

    def _battery_cb(self, msg):
        with self._lock:
            self._battery_v = float(msg.voltage or 0.0)
            # sensor_msgs/BatteryState.percentage is specified as 0..1;
            # server.py normalizes either 0..1 or 0..100 for its API.
            self._battery_pct = float(msg.percentage if msg.percentage >= 0 else 0.0)

    def _heading_cb(self, msg):
        with self._lock:
            self._heading = float(msg.data)

    def _wait_service(self, proxy, timeout=5.0):
        try:
            proxy.wait_for_service(timeout=timeout)
            return True
        except Exception:
            return False

    def arm(self):
        try:
            if not self._wait_service(self._arm_srv): return ActionResult(False, "MAVROS arming service unavailable")
            r = self._arm_srv(True)
            return ActionResult(bool(r.success), "Armed" if r.success else str(r.result))
        except Exception as exc: return ActionResult(False, str(exc))

    def disarm(self):
        try:
            if not self._wait_service(self._arm_srv): return ActionResult(False, "MAVROS arming service unavailable")
            r = self._arm_srv(False)
            return ActionResult(bool(r.success), "Disarmed" if r.success else str(r.result))
        except Exception as exc: return ActionResult(False, str(exc))

    def _set_mode(self, mode):
        if not self._wait_service(self._mode_srv): return False
        r = self._mode_srv(custom_mode=mode)
        return bool(r.mode_sent)

    def _publish_velocity(self, forward, right, down, yaw_rate):
        if not self._pub_vel: return
        from geometry_msgs.msg import TwistStamped
        # body FLU -> local ENU using compass heading (degrees).
        yaw = math.radians(self._heading)
        vx = forward * math.cos(yaw) - right * math.sin(yaw)
        vy = forward * math.sin(yaw) + right * math.cos(yaw)
        m = TwistStamped()
        m.header.stamp = self._ros.Time.now()
        m.twist.linear.x, m.twist.linear.y, m.twist.linear.z = vy, vx, -down
        # MAVROS transforms ROS ENU angular-z to MAVLink NED by flipping Z.
        # AerialClaw/MAVSDK define positive yaw_rate as increasing compass
        # heading (clockwise when viewed from above), hence the minus sign.
        m.twist.angular.z = -math.radians(yaw_rate)
        self._pub_vel.publish(m)

    def _publish_position(self, north, east, down):
        from geometry_msgs.msg import PoseStamped
        m = PoseStamped()
        m.header.stamp = self._ros.Time.now()
        m.header.frame_id = "map"
        m.pose.position.x, m.pose.position.y, m.pose.position.z = east + self._home.east, north + self._home.north, -(down + self._home.down)
        # Keep the current compass heading instead of commanding a fixed yaw.
        # ROS ENU yaw is measured CCW from east, while compass heading is
        # measured clockwise from north.
        yaw_enu = math.radians(90.0 - self._heading)
        m.pose.orientation.z = math.sin(yaw_enu / 2.0)
        m.pose.orientation.w = math.cos(yaw_enu / 2.0)
        self._pub_pos.publish(m)

    def _offboard_ready(self, target=None):
        if not self._connected or not self._have_pose:
            return False
        # PX4 requires a short stream of setpoints before accepting OFFBOARD.
        for _ in range(20):
            if target is None: self._publish_velocity(0, 0, 0, 0)
            else: self._publish_position(*target)
            time.sleep(0.05)
        return self._set_mode("OFFBOARD")

    def takeoff(self, altitude=1.5):
        if not self._connected: return ActionResult(False, "Not connected")
        altitude = max(0.5, min(float(altitude), 4.0))
        try:
            if not self._armed:
                r = self.arm()
                if not r.success: return r
            target = (0.0, 0.0, -altitude)
            if not self._offboard_ready(target): return ActionResult(False, "PX4 rejected OFFBOARD mode")
            self.is_flying = True
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                self._publish_position(*target)
                if self._in_air and -self.get_position().down >= altitude * 0.7: return ActionResult(True, "Takeoff OK", {"altitude": -self.get_position().down})
                time.sleep(0.05)
            return ActionResult(False, "Takeoff timeout")
        except Exception as exc: return ActionResult(False, str(exc))

    def land(self):
        try:
            if not self._connected: return ActionResult(False, "Not connected")
            if not self._set_mode("AUTO.LAND"): return ActionResult(False, "MAVROS rejected AUTO.LAND")
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if not self._in_air: self.is_flying = False; return ActionResult(True, "Landed")
                time.sleep(0.2)
            return ActionResult(False, "Land timeout")
        except Exception as exc: return ActionResult(False, str(exc))

    def hover(self, duration=5.0):
        if not self._offboard_ready(): return ActionResult(False, "PX4 rejected OFFBOARD mode")
        end = time.monotonic() + duration
        while time.monotonic() < end: self._publish_velocity(0, 0, 0, 0); time.sleep(0.05)
        return ActionResult(True, f"Hovered {duration}s")

    def return_to_launch(self):
        try:
            if not self._connected: return ActionResult(False, "Not connected")
            ok = self._set_mode("AUTO.RTL")
            return ActionResult(ok, "RTL requested" if ok else "MAVROS rejected AUTO.RTL")
        except Exception as exc: return ActionResult(False, str(exc))

    def fly_to_ned(self, north, east, down, speed=1.5):
        if not self._connected: return ActionResult(False, "Not connected")
        target = (float(north), float(east), max(-4.0, min(-0.5, float(down))))
        speed = max(0.1, min(float(speed), 3.0))
        if not self._offboard_ready(target): return ActionResult(False, "PX4 rejected OFFBOARD mode")
        self.is_flying = True; self._stop_req = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self._stop_req: self.stop_velocity(); self.is_flying = False; return ActionResult(False, "Stopped")
            p = self.get_position(); err = math.sqrt((target[0]-p.north)**2 + (target[1]-p.east)**2 + (target[2]-p.down)**2)
            self._publish_position(*target)
            if err < 0.5: self.is_flying = False; return ActionResult(True, f"Arrived (err={err:.2f}m)")
            time.sleep(0.05)
        self.is_flying = False; return ActionResult(False, "fly_to_ned timeout")

    def change_altitude_relative(self, delta, speed=1.0):
        p = self.get_position()
        target_alt = max(0.5, min(4.0, -p.down + float(delta)))
        return self.fly_to_ned(p.north, p.east, -target_alt, speed)

    def request_stop(self):
        self._stop_req = True

    def set_velocity_body(self, forward, right, down, duration=1.0, yaw_rate=0.0):
        if not self._connected: return ActionResult(False, "Not connected")
        if not self._offboard_ready(): return ActionResult(False, "PX4 rejected OFFBOARD mode")
        self._stop_req = False
        end = time.monotonic() + max(0.0, float(duration))
        while time.monotonic() < end and not self._stop_req:
            self._publish_velocity(forward, right, down, yaw_rate)
            time.sleep(0.05)
        self._publish_velocity(0.0, 0.0, 0.0, 0.0)
        return ActionResult(True, "velocity_body sent")

    def stop_velocity(self):
        self._stop_req = True
        self._publish_velocity(0, 0, 0, 0)
        return ActionResult(True, "Stopped")
