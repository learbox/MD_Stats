"""段位图标检测线程 — 独立于主识别管线运行。

================================================================================
设计思路
================================================================================

段位图标仅在 coin toss 阶段短暂显示（~2 秒），主管线的 0.3s 截图间隔
无法保证正好截到。因此使用独立线程，以可配置的间隔持续截图检测，
检测到双方段位后立即暂存结果并暂停，等下一局再重新开始。

================================================================================
生命周期
================================================================================

    启动  ──→ 截图循环 ──→ 检测到段位 → 暂存结果 → 暂停
      ↑                                                  │
      └──── 主窗口通知"下一局" ←── 对局结束写入 CSV ←──────┘

    停止  ──→ 重置状态 → 线程退出

================================================================================
线程安全

    工作线程只做：截图 + 检测 + emit 信号
    主线程只做：读取结果 + 控制启动/停止
    结果通过 Signal 传递（Qt 线程安全）
"""


import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from src import capture as _cap
from src import detector as _det
from src.config import load_config


class RankDetector(QThread):
    """独立线程：循环截图检测双方段位图标。"""

    rank_icon_detected = Signal(dict)  # {player_rank, player_tier, ...}

    def __init__(self, parent=None):
        super().__init__(parent)
        cfg = load_config()
        rc = cfg.get("rank_detection", {})
        self._interval: float = rc.get("interval", 0.5)
        self._threshold: float = rc.get("confidence_threshold", 0.7)
        self._running = False
        self._paused = False
        self._result: dict | None = None

    # =========================================================================
    # 主线程接口
    # =========================================================================

    def get_result(self) -> dict | None:
        """取暂存结果，取后清空。返回 None 表示未检测到。"""
        r = self._result
        self._result = None
        return r

    def resume_for_next_game(self) -> None:
        """下一局开始，恢复截图循环。"""
        self._paused = False

    def stop(self) -> None:
        """停止线程（优雅退出）。"""
        self._running = False

    # =========================================================================
    # 线程主循环
    # =========================================================================

    def run(self) -> None:
        self._running = True

        while self._running:
            if self._paused:
                self.msleep(200)
                continue

            # 等待 Master Duel 窗口可用
            if not _cap.is_window_open("masterduel"):
                self.msleep(500)
                continue

            try:
                screenshot = _cap.capture_window("masterduel")
            except Exception:
                self.msleep(int(self._interval * 1000))
                continue

            if screenshot is None:
                self.msleep(int(self._interval * 1000))
                continue

            try:
                result = _det.detect_rank_icon(screenshot, self._threshold)
            except Exception:
                result = {}

            # 双方都检测到 → 暂存结果，暂停
            if result.get("player_rank") and result.get("opponent_rank"):
                self._result = result
                self.rank_icon_detected.emit(result)
                self._paused = True

            self.msleep(int(self._interval * 1000))
