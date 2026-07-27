"""
perception/a40_tunnel.py
A40 SSH 隧道自动管理 — 让 VLM_BACKEND=a40 时无需手动起隧道。

仅当环境变量 VLM_BACKEND=a40 时生效。启动时探测本地 5009 端口是否已通,
未通则后台拉起 A40_tunnle.py -p 5009 子进程, 等待端口就绪。
失败只记录日志, 不抛异常 —— VLM 不可用不应阻断 server 启动。

隧道子进程的生命周期跟随主进程 (daemon 子进程, 主进程退出时由 OS 回收)。
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 仓库根目录 (本文件在 perception/ 下)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUNNEL_SCRIPT = _REPO_ROOT / "A40_tunnle.py"

# 默认转发的本地端口 (VLM /describe)
DEFAULT_PORT = 5009

# 模块级句柄, 避免被 GC 回收掉子进程
_proc = None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """本地端口是否可连 (隧道是否已建立)。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_tunnel_running(port: int = DEFAULT_PORT, timeout: float = 20.0) -> bool:
    """
    确保 A40 VLM 的 SSH 隧道在本地 port 上可用。

    - VLM_BACKEND != "a40" 时: 直接 return True (不关心隧道)。
    - 端口已通: return True。
    - 端口未通: 后台拉起 A40_tunnle.py -p <port>, 轮询等待直到通或超时。

    Returns:
        True 表示隧道可用 (或不需要); False 表示需要但拉起失败。
    """
    global _proc

    if os.environ.get("VLM_BACKEND", "openai_compat").strip().lower() != "a40":
        return True  # 非 A40 后端, 无需隧道

    if _port_open("127.0.0.1", port):
        logger.info("A40 VLM 隧道已在运行 (127.0.0.1:%d 可连)", port)
        return True

    if not _TUNNEL_SCRIPT.exists():
        logger.warning("A40 隧道脚本不存在: %s", _TUNNEL_SCRIPT)
        return False

    logger.info("A40 VLM 隧道未运行, 启动子进程: %s -p %d", _TUNNEL_SCRIPT, port)
    try:
        _proc = subprocess.Popen(
            [sys.executable, str(_TUNNEL_SCRIPT), "-p", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # 子进程随主进程退出 (新进程组, 主进程退出时由 OS 回收)
            start_new_session=True,
        )
    except Exception as e:
        logger.warning("启动 A40 隧道子进程失败: %s", e)
        return False

    # 轮询等待端口就绪
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open("127.0.0.1", port):
            logger.info("A40 VLM 隧道已就绪 (127.0.0.1:%d, PID %d)", port, _proc.pid)
            return True
        # 子进程提前挂掉就没必要继续等
        if _proc.poll() is not None:
            logger.warning("A40 隧道子进程已退出 (code=%d), 可能是 SSH 凭据/网络问题", _proc.returncode)
            return False
        time.sleep(0.5)

    logger.warning("A40 隧道等待超时 (%.0fs), 127.0.0.1:%d 仍未就绪", timeout, port)
    return False