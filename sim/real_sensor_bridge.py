"""
sim/real_sensor_bridge.py — 真机相机传感器桥接

实机部署时替代 sim/gz_sensor_bridge.py，实现同一套接口
(start / is_running / get_camera_image / get_camera_info / get_lidar_scan /
get_lidar_info / get_status)，从真实相机视频流（如 SIYI A8 Mini RTSP）抓帧，
供 server.py 的 _start_sensor_stream 推送到前端 sensor_cameras 事件。

启用方式（server.py 据此改用本桥）：
    export AERIALCLAW_REAL_CAMERA_BRIDGE=1

流地址配置（环境变量）：
    REAL_CAMERA_URLS       JSON 映射 {方向: url}，例如
                           {"gimbal":"rtsp://192.168.144.25:8554/live",
                            "front":"rtsp://..."}
    REAL_CAMERA_GIMBAL_URL 单方向覆盖（也支持 FRONT/REAR/LEFT/RIGHT/DOWN）
默认只配 gimbal 方向指向 SIYI A8 Mini RTSP；其余方向留空 → 前端显示 NO SIGNAL。

注意：RTSP 抓帧依赖 OpenCV 的 FFMPEG 后端（opencv-python-headless 自带）。
若 VideoCapture 打不开流，检查：SIYI 是否上电/可达、RTSP 地址是否正确、
opencv 是否带 FFMPEG 支持（`python -c "import cv2; print(cv2.getBuildInformation())" | grep FFMPEG`）。
"""
import os
import json
import time
import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# 默认流地址：SIYI A8 Mini 的 RTSP（以 SIYI 实测/文档为准，可用 env 覆盖）
# The deployed Jetson test vehicle uses eth0=192.168.144.50 and the SIYI
# A8 Mini at 192.168.144.25.  Keep the URL overridable through
# REAL_CAMERA_GIMBAL_URL/REAL_CAMERA_URLS for other airframes.
_DEFAULT_URLS = {
    "gimbal": "rtsp://192.168.144.25:8554/live",
}

_DIRECTIONS = ("gimbal", "front", "rear", "left", "right", "down")


def _load_urls() -> dict:
    """从环境变量解析方向→流地址映射。"""
    urls = dict(_DEFAULT_URLS)
    raw = os.getenv("REAL_CAMERA_URLS")
    if raw:
        try:
            urls.update(json.loads(raw))
        except Exception as e:
            logger.warning("[RealCamera] REAL_CAMERA_URLS 解析失败，用默认: %s", e)
    # 单方向覆盖：REAL_CAMERA_GIMBAL_URL / REAL_CAMERA_FRONT_URL ...
    for d in _DIRECTIONS:
        v = os.getenv(f"REAL_CAMERA_{d.upper()}_URL")
        if v:
            urls[d] = v
    # 去掉空值
    return {k: v for k, v in urls.items() if v}


class _StreamGrabber(threading.Thread):
    """单个视频流的抓帧线程：持续抓帧、保留最新帧、断流自动重连。

    用独立线程跑 cv2.VideoCapture.read()（对 RTSP 会阻塞到下一帧），
    这样 get_frame() 永远立即返回最近一帧，不阻塞 server 推送循环。
    """

    def __init__(self, direction: str, url: str):
        super().__init__(daemon=True, name=f"realcam-{direction}")
        self.direction = direction
        self.url = url
        self._frame: Optional[np.ndarray] = None
        self._info = {"direction": direction, "width": 0, "height": 0, "fps": 0.0}
        self._cap = None
        self._stop = False
        self._frame_count = 0
        self._last_ts = 0.0

    def run(self):
        try:
            import cv2
        except ImportError:
            logger.error("[RealCamera] 缺少 opencv，无法抓帧 (%s)", self.direction)
            return
        backoff = 1.0
        while not self._stop:
            if self._cap is None or not self._cap.isOpened():
                try:
                    self._cap = cv2.VideoCapture(self.url)
                    # 尽量降低缓冲延迟，拿最新帧
                    try:
                        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("[RealCamera] %s 打开失败: %s", self.direction, e)
                    self._cap = None
                if not self._cap or not self._cap.isOpened():
                    time.sleep(backoff)
                    backoff = min(backoff * 1.5, 10.0)
                    continue
                backoff = 1.0
                logger.info("[RealCamera] %s 已连接 %s", self.direction, self.url)
            ok, frame = self._cap.read()
            if not ok or frame is None:
                logger.warning("[RealCamera] %s 取帧失败，重连", self.direction)
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue
            self._frame = frame
            self._frame_count += 1
            self._last_ts = time.time()
            h, w = frame.shape[:2]
            self._info = {
                "direction": self.direction,
                "width": int(w),
                "height": int(h),
                "fps": 0.0,
            }
            # read() 已按帧率阻塞，这里只稍微让出 CPU
            time.sleep(0.005)

    def stop(self):
        self._stop = True
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass

    def get_frame(self) -> Optional[np.ndarray]:
        return self._frame

    @property
    def info(self) -> dict:
        return self._info

    @property
    def frame_count(self) -> int:
        return self._frame_count


class RealSensorBridge:
    """真机传感器桥接：从真实相机流抓帧，接口与 GzSensorBridge 一致。

    server.py 的 _start_sensor_stream 会调用：
        is_running / get_camera_image(dir) / get_camera_info(dir)
        / get_lidar_scan() / get_lidar_info() / get_status()
    本桥只实现相机；雷达返回 None（真机若有 2D 雷达可在此扩展）。
    """

    name = "real_camera"

    def __init__(self, urls: Optional[dict] = None):
        self._urls = _load_urls() if urls is None else urls
        self._grabbers: dict[str, _StreamGrabber] = {}
        self.is_running = False

    def start(self) -> bool:
        if not self._urls:
            logger.warning("[RealCamera] 未配置任何相机流 URL（REAL_CAMERA_URLS）")
            return False
        try:
            import cv2  # noqa: F401
        except ImportError:
            logger.error("[RealCamera] 缺少 opencv-python，无法抓帧")
            return False
        for d, url in self._urls.items():
            g = _StreamGrabber(d, url)
            g.start()
            self._grabbers[d] = g
        self.is_running = True
        logger.info("[RealCamera] 桥接启动，方向: %s", list(self._urls.keys()))
        return True

    def stop(self):
        for g in self._grabbers.values():
            g.stop()
        self.is_running = False

    def get_camera_image(self, direction: str = "gimbal") -> Optional[np.ndarray]:
        g = self._grabbers.get(direction)
        return g.get_frame() if g else None

    def get_camera_info(self, direction: str = "gimbal") -> dict:
        g = self._grabbers.get(direction)
        if g:
            return g.info
        return {"direction": direction, "width": 0, "height": 0, "fps": 0.0}

    def get_lidar_scan(self):
        """真机若接了 2D 雷达可在此接入；当前返回 None。"""
        return None

    def get_lidar_info(self) -> dict:
        return {"fps": 0.0}

    def get_status(self) -> dict:
        cams = {}
        for d, g in self._grabbers.items():
            cams[d] = {
                **g.info,
                "frame_count": g.frame_count,
                "last_ts": g._last_ts,
                "topic": self._urls.get(d, ""),
            }
        return {
            "running": self.is_running,
            "source": "real_camera",
            "cameras": cams,
        }
