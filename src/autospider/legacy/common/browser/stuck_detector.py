"""操作指纹滑动窗口卡死检测器。

在 LLM 驱动浏览器自动化中，模型可能陷入重复操作循环
（如反复点击同一元素、在两个页面间无限跳转）。

StuckDetector 通过维护最近 N 步操作的指纹（action + url + mark_id），
当滑动窗口内同一指纹出现次数超过阈值时，判定为卡死并触发熔断。
"""

from __future__ import annotations

import os
from collections import Counter, deque

from autospider.platform.observability.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_WINDOW_SIZE = int(os.getenv("STUCK_WINDOW_SIZE", "8"))
_DEFAULT_REPEAT_THRESHOLD = int(os.getenv("STUCK_REPEAT_THRESHOLD", "3"))


class StuckDetector:
    """操作指纹滑动窗口卡死检测器。

    Args:
        window_size: 滑动窗口大小（保留最近多少步）。
        repeat_threshold: 同一指纹在窗口内出现多少次判定为卡死。
    """

    def __init__(
        self,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        repeat_threshold: int = _DEFAULT_REPEAT_THRESHOLD,
    ) -> None:
        self._window: deque[str] = deque(maxlen=max(1, window_size))
        self._threshold = max(2, repeat_threshold)
        self._total_records = 0

    def record(
        self,
        action: str,
        url: str = "",
        mark_id: int | str | None = None,
        target_text: str = "",
    ) -> None:
        """记录一次操作指纹。

        指纹格式: "{action}:{url_path}:{mark_id}:{text_prefix}"
        url 只取 path 部分，避免 query 参数变化导致误判。
        """
        from urllib.parse import urlparse

        url_path = urlparse(url).path if url else ""
        text_key = (target_text or "")[:30].strip()
        fingerprint = f"{action}:{url_path}:{mark_id}:{text_key}"
        self._window.append(fingerprint)
        self._total_records += 1

    def is_stuck(self) -> bool:
        """判断当前是否卡死。

        Returns:
            True 表示窗口内最高频指纹超过阈值。
        """
        if len(self._window) < self._threshold:
            return False

        counter = Counter(self._window)
        top_fingerprint, max_count = counter.most_common(1)[0]

        if max_count >= self._threshold:
            logger.warning(
                "[StuckDetector] 检测到重复操作循环: '%s' 在最近 %d 步中出现 %d 次 (阈值=%d)",
                top_fingerprint,
                len(self._window),
                max_count,
                self._threshold,
            )
            return True

        return False

    def reset(self) -> None:
        """重置检测器状态（如切换到新任务时调用）。"""
        self._window.clear()
        self._total_records = 0

    @property
    def total_records(self) -> int:
        """已记录的操作总数。"""
        return self._total_records

    @property
    def window_snapshot(self) -> list[str]:
        """当前窗口内的指纹快照（调试用）。"""
        return list(self._window)
