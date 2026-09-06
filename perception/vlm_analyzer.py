"""
perception/vlm_analyzer.py
VLM (视觉语言模型) 分析器 — 按需深度图像分析。

第二层感知: LLM 决定需要深度分析时调用。
使用 GPT-4o 等云端视觉大模型做 图像 -> 语言 转换。

功能:
  - 将摄像头图像发送给 VLM, 获取结构化环境描述
  - 支持多种分析模式: 环境分析 / 目标搜索 / 导航辅助
  - 与 PerceptionDaemon 联动: 分析结果自动注入环境摘要

设计:
  - 不在每次循环中调用 (VLM 调用有 API 成本)
  - 由 planner 或感知技能按需触发
  - 输出固定格式 JSON, 便于解析和融合
"""

import base64
import json
import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class VLMAnalyzer:
    """
    VLM 分析器。通过 OpenAI 兼容接口调用视觉大模型分析图像。
    """

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        timeout: int = 30,
    ):
        """
        Args:
            base_url: VLM API 地址 (default: from config/env)
            api_key:  API Key (default: from config/env)
            model:    模型名称 (default: from config/env)
            timeout:  请求超时 (秒)

        后端选择 (VLM_BACKEND 环境变量):
            "openai_compat" (默认): OpenAI 兼容 /chat/completions, 自定义 prompt 生效。
            "a40":            走 A40 vLLM 的 POST /describe 端点 (固定导航 schema,
                              忽略自定义 prompt)。本地需先建立 SSH 隧道把
                              127.0.0.1:5009 转发到 A40:5009 (见 A40_tunnle.py)。
        """
        import os
        self._base_url = (base_url or os.environ.get("VLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self._api_key = api_key or os.environ.get("VLM_API_KEY", "")
        self._model = model or os.environ.get("VLM_MODEL", "gpt-4o")
        self._timeout = timeout
        # VLM 后端: "openai_compat" (走 /chat/completions) 或 "a40" (走 /describe)
        self._backend = os.environ.get("VLM_BACKEND", "openai_compat").strip().lower()
        # A40 /describe 端点完整 URL (基于 base_url 拼接)
        self._a40_url = self._base_url + "/describe"
        # A40 单次调用在降采样后通常 ~5-10s。给 30s 超时留足余量; A40 真正不可达时
        # 重试 2 次 = 最坏阻塞 ~60s, 不会把 agent 循环卡死。env VLM_A40_TIMEOUT 可调。
        if self._backend == "a40":
            self._timeout = int(os.environ.get("VLM_A40_TIMEOUT", "30"))
        # A40 发送前降采样的最大边长 (像素)。导航 schema 不需要高清, 小图传输快、
        # vLLM 推理快, 显著降低超时概率。env 可调, 设 0 表示不降采样。
        self._a40_max_dim = int(os.environ.get("VLM_A40_MAX_DIM", "480"))

        # 调用统计
        self._call_count = 0
        self._total_time = 0.0
        self._last_call_ts = 0.0

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def analyze_image(
        self,
        image,  # np.ndarray (BGR) 或 bytes (JPEG)
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 500,
    ) -> Optional[Dict[str, Any]]:
        """
        发送图像给 VLM 分析。

        Args:
            image:         OpenCV BGR 图像 (np.ndarray) 或 JPEG bytes
            system_prompt: 系统提示词
            user_prompt:   用户提示词
            max_tokens:    最大输出 token 数

        Returns:
            dict: VLM 输出的结构化 JSON, 解析失败返回 None
        """
        import numpy as np

        # 将图像编码为 base64 JPEG
        if isinstance(image, np.ndarray):
            import cv2  # 延迟导入: cv2 依赖 numpy, 环境不兼容时不应阻断整个模块加载
            _, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 70])
            b64_image = base64.b64encode(buf.tobytes()).decode("ascii")
        elif isinstance(image, bytes):
            b64_image = base64.b64encode(image).decode("ascii")
        else:
            logger.error("VLM 输入类型不支持: %s", type(image))
            return None

        # A40 后端: 走 /describe 端点, 返回固定导航 schema, 再翻译成通用超集 dict。
        # A40 忽略 system_prompt/user_prompt (服务端用固定提示词), 但仍把 user_prompt
        # 透传为 prompt 字段, 以备服务端日后支持。max_tokens 对 A40 无意义但保留参数签名。
        if self._backend == "a40":
            start = time.time()
            try:
                # 降采样: 真实 AirSim 帧分辨率高, 直接发大图会让 vLLM 推理 + SSH 隧道
                # 传输都很慢, 实测 30s 超时都不够 (日志: 3 次重试全 timed out)。
                # 导航 schema 不需要高清, 限到 480px 后单次 ~5-10s 稳定。
                b64_image = self._downscale_b64(b64_image, self._a40_max_dim)
                desc = self._call_a40(b64_image, user_prompt)
                elapsed = time.time() - start
                if desc is None:
                    logger.warning("A40 VLM 分析失败 (返回空, %.1fs)", elapsed)
                    return None
                result = self._translate_a40(desc)
                self._call_count += 1
                self._total_time += elapsed
                self._last_call_ts = time.time()
                logger.info(
                    "A40 VLM 分析完成 (%.1fs, 累计 %d 次, 平均 %.1fs)",
                    elapsed, self._call_count, self._total_time / self._call_count,
                )
                return result
            except Exception as e:
                logger.error("A40 VLM 分析异常: %s", e)
                return None

        # 构建 messages
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}",
                            "detail": "low",  # 降低 token 消耗
                        },
                    },
                ],
            },
        ]

        # 调用 API
        start = time.time()
        try:
            raw = self._call_api(messages, max_tokens)
            elapsed = time.time() - start
            self._call_count += 1
            self._total_time += elapsed
            self._last_call_ts = time.time()

            logger.info(
                "VLM 分析完成 (%.1fs, 累计 %d 次, 平均 %.1fs)",
                elapsed, self._call_count, self._total_time / self._call_count,
            )

            # 解析 JSON
            return self._parse_json_response(raw)
        except Exception as e:
            logger.error("VLM 分析失败: %s", e)
            return None

    def analyze_environment(
        self,
        image,
        camera_direction: str = "前方",
        altitude: float = 1.5,
        task_context: str = "环境探索",
    ) -> Optional[Dict[str, Any]]:
        """
        环境分析: 分析相机图像, 返回结构化环境描述。

        Args:
            image:            OpenCV BGR 图像
            camera_direction: 相机方向 (前方/后方/左方/右方)
            altitude:         当前高度 (米)
            task_context:     当前任务描述

        Returns:
            dict: 环境分析结果
        """
        from perception.prompts import ENV_ANALYSIS_SYSTEM, ENV_ANALYSIS_USER
        user_prompt = ENV_ANALYSIS_USER.format(
            camera_direction=camera_direction,
            altitude=altitude,
            task_context=task_context,
        )
        return self.analyze_image(image, ENV_ANALYSIS_SYSTEM, user_prompt)

    def search_target(
        self,
        image,
        target_description: str,
        camera_direction: str = "前方",
        altitude: float = 1.5,
    ) -> Optional[Dict[str, Any]]:
        """
        目标搜索: 分析图像, 判断是否发现搜索目标。
        """
        from perception.prompts import TARGET_SEARCH_SYSTEM, TARGET_SEARCH_USER
        user_prompt = TARGET_SEARCH_USER.format(
            target_description=target_description,
            camera_direction=camera_direction,
            altitude=altitude,
        )
        return self.analyze_image(image, TARGET_SEARCH_SYSTEM, user_prompt)

    def evaluate_navigation(
        self,
        image,
        camera_direction: str = "前方",
        target_direction: str = "正前方",
        altitude: float = 1.5,
    ) -> Optional[Dict[str, Any]]:
        """
        导航辅助: 评估飞行路径安全性。
        """
        from perception.prompts import NAVIGATION_SYSTEM, NAVIGATION_USER
        user_prompt = NAVIGATION_USER.format(
            camera_direction=camera_direction,
            target_direction=target_direction,
            altitude=altitude,
        )
        return self.analyze_image(image, NAVIGATION_SYSTEM, user_prompt)

    # ── 统计信息 ──────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取调用统计。"""
        return {
            "call_count": self._call_count,
            "total_time": round(self._total_time, 2),
            "avg_time": round(self._total_time / max(self._call_count, 1), 2),
            "last_call": self._last_call_ts,
            "model": self._model,
            "backend": self._backend,
        }

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _call_a40(self, b64_image: str, prompt: str) -> Optional[Dict[str, Any]]:
        """
        调用 A40 vLLM 的 POST /describe 端点。

        请求: {"image": "<base64 jpeg>", "prompt": "..."}  (prompt 服务端目前忽略)
        响应外层: {"status":"success","engine":"vllm","elapsed_s":..,
                  "description":{固定导航 schema},"raw_response":"..."}
        返回内层 description dict; 失败返回 None。

        带网络层重试 (2 次)。A40 单次较慢, 重试次数取低以免长时间阻塞 agent 循环。
        """
        import urllib.request
        import urllib.error

        url = self._a40_url
        payload = json.dumps({"image": b64_image, "prompt": prompt or ""}).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                if body.get("status") != "success":
                    logger.warning("A40 /describe 状态异常: %s", str(body)[:200])
                    return None
                desc = body.get("description")
                if not isinstance(desc, dict):
                    logger.warning("A40 /describe 无 description 字段: %s", str(body)[:200])
                    return None
                return desc
            except urllib.error.HTTPError as e:
                # HTTP 错误 (4xx) 是配置/请求问题, 重试无意义, 直接返回 None
                logger.error("A40 /describe HTTP %d: %s", e.code, e.read().decode("utf-8", "replace")[:200])
                return None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_exc = e
                if attempt < 1:
                    logger.warning("A40 /describe 连接失败 (第%d/2次), 1.5s 后重试: %s", attempt + 1, e)
                    time.sleep(1.5)
        logger.error("A40 /describe 连接失败 (已重试2次): %s", last_exc)
        return None

    def _downscale_b64(self, b64_image: str, max_dim: int) -> str:
        """
        把 base64 JPEG 降采样到最大边长 max_dim 像素, 再编码回 base64 JPEG。

        A40 走 SSH 隧道 + vLLM, 高分辨率帧会让推理/传输都很慢 (实测 1080p 帧直接
        30s 超时)。导航场景描述不需要高清, 限到 480px 后单次稳定在 ~5-10s。
        max_dim<=0 表示不降采样 (直接返回原图)。降采样失败时回退原图, 不阻断。
        """
        if not max_dim or max_dim <= 0:
            return b64_image
        try:
            import io as _io
            from PIL import Image
            raw = base64.b64decode(b64_image)
            im = Image.open(_io.BytesIO(raw))
            im = im.convert("RGB")
            w, h = im.size
            scale = max_dim / float(max(w, h))
            if scale < 1.0:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            buf = _io.BytesIO()
            im.save(buf, format="JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            logger.debug("A40 图像降采样失败, 回退原图: %s", e)
            return b64_image

    def _translate_a40(self, desc: Dict[str, Any]) -> Dict[str, Any]:
        """
        把 A40 固定导航 schema 翻译成通用超集 dict。

        A40 忽略调用方传入的 system/user prompt, 永远返回同一套导航字段;
        而现有调用方 (Observe / orbit_inspect / PassivePerception / Perceive)
        各自期望不同的键 (description/objects/hazards/issues/obstacles/
        features/summary/findings/objects_detected)。这里一次性展开成超集,
        让全部调用方零改动即可消费。
        """
        obstacles = desc.get("obstacles", []) or []
        scene_summary = desc.get("scene_summary", "")
        confidence = desc.get("confidence")

        # 阻塞型障碍 → hazards/issues (字符串列表)
        blocking_strs = []
        for o in obstacles:
            if o.get("blocking"):
                blocking_strs.append(
                    f"{o.get('direction','?')} {o.get('distance_m','?')}m {o.get('type','障碍物')}"
                )

        return {
            # Observe / orbit_inspect 读
            "description": scene_summary,
            "objects": [
                {
                    "type": o.get("type", "?"),
                    "position": o.get("direction", "?"),
                    "detail": f"{o.get('type','?')} {o.get('distance_m','?')}m",
                }
                for o in obstacles
            ],
            "hazards": blocking_strs,
            "issues": list(blocking_strs),  # orbit_inspect 读 issues
            # PassivePerception 读 (obstacles 形状需匹配 WorldModel 写入格式)
            "obstacles": [
                {
                    "direction": o.get("direction", "?"),
                    "type": o.get("type", "?"),
                    "distance_m": o.get("distance_m"),
                    "height_m": None,
                    "width_m": None,
                }
                for o in obstacles
            ],
            "features": [],
            "summary": scene_summary,
            # Perceive 读
            "findings": [],
            "objects_detected": [
                {
                    "type": o.get("type", "?"),
                    "description": f"{o.get('direction','?')} {o.get('distance_m','?')}m",
                    "confidence": confidence,
                }
                for o in obstacles
            ],
            # A40 原始字段透传 (导航决策可参考)
            "scene_type": desc.get("scene_type"),
            "clear_directions": desc.get("clear_directions", []),
            "recommended_direction": desc.get("recommended_direction"),
            "free_space": desc.get("free_space"),
            "target_visible": desc.get("target_visible", False),
            "target_found": desc.get("target_visible", False),
            "target_description": desc.get("target_description"),
            "confidence": confidence,
        }

    def _call_api(self, messages: list, max_tokens: int) -> str:
        """调用 OpenAI 兼容的 VLM API。"""
        import urllib.request
        import urllib.error

        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                return content.strip()
            except urllib.error.HTTPError as e:
                status = e.code
                if status in (502, 503) and attempt < max_retries - 1:
                    logger.warning("VLM API %d, 重试 %d/%d", status, attempt + 1, max_retries)
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"VLM API HTTP {status}") from e
            except urllib.error.URLError as e:
                if attempt < max_retries - 1:
                    logger.warning("VLM API 连接失败, 重试 %d/%d: %s", attempt + 1, max_retries, e)
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"VLM API 连接失败: {e}") from e

    def _parse_json_response(self, raw: str) -> Optional[Dict[str, Any]]:
        """解析 VLM 输出的 JSON, 容忍 markdown 代码块包裹。"""
        # 去掉 markdown 代码块标记
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉第一行 ```json 和最后一行 ```
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取第一个 JSON 对象
            import re
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning("VLM 输出 JSON 解析失败: %s", text[:200])
            return None


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_analyzer: Optional[VLMAnalyzer] = None


def get_analyzer() -> Optional[VLMAnalyzer]:
    """获取全局 VLM 分析器实例。"""
    return _analyzer


def init_analyzer(**kwargs) -> VLMAnalyzer:
    """初始化全局 VLM 分析器。"""
    global _analyzer
    _analyzer = VLMAnalyzer(**kwargs)
    logger.info("VLM 分析器已初始化 (model=%s)", _analyzer._model)
    return _analyzer
