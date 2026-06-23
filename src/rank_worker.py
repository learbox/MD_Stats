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


import cv2
from PySide6.QtCore import QThread, Signal

from src import capture as _cap
from src import detector as _det
from src.config import load_config
from src.failure_sample_manager import FailureSampleManager


class RankWorker(QThread):
    """独立线程：循环截图检测双方段位图标。

    QThread 是 PySide6 的线程封装。PySide6 中不能在其他线程直接操作
    UI 控件，但可以通过 Signal（信号）把数据安全地传给主线程。

    这个类继承 QThread，重写 run() 方法实现后台循环：
        1. 定时对 Master Duel 窗口截图
        2. 调用 detector.detect_rank_icon() 识别段位图标
        3. 识别结果通过 Signal 传给主线程
        4. 双方都识别到后暂停，等下一局再继续

    属性说明:
        _interval  — 截图间隔（秒），从 config.toml 读取，默认 0.5
        _threshold — NCC 匹配置信度阈值，低于此值的结果丢弃
        _running   — 线程运行标志，设为 False 后下一次循环退出
        _paused    — 暂停标志，一局完成后暂停截图节省 CPU
        _result    — 暂存检测结果，双方都检测到后发射并暂停
    """

    # Signal 定义：类属性，不是实例属性
    # Qt 会在后台建立线程安全的通信通道
    rank_icon_detected = Signal(dict)  # 双方都检测到时发射（完整结果）
    partial_update = Signal(dict)      # 首次检测到单方时发射（增量进度）

    def __init__(self, failure_mgr: FailureSampleManager | None = None,
                 parent=None):
        """初始化段位检测线程，从 config.toml 读取配置。

        关于 failure_mgr（最佳失败样本）：
            由 MainWindow 创建并传入，与 StatsWorker 共用同一实例。
            每次检测后对 my_rank_icon 和 opponent_rank_icon 调用 consider()，
            新一轮开始时（resume_for_next_game）调用 clear_cache() 清空缓存。

        Args:
            failure_mgr: 最佳失败样本管理器实例。为 None 时功能不生效。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        cfg = load_config()
        rank_cfg = cfg.get("rank_detection", {})  # 读取 [rank_detection] 段
        self._interval: float = rank_cfg.get("interval", 0.5)
        self._threshold: float = rank_cfg.get("confidence_threshold", 0.7)
        self._running = False               # 线程主循环开关
        self._paused = False                # 暂停标志（一局结束到下一局开始之间）
        self._result: dict | None = None    # 暂存当前这局的检测结果
        self._failure_mgr = failure_mgr     # 失败样本管理器

    # =========================================================================
    # 主线程接口 — 以下方法由主线程调用，控制检测线程的行为
    #
    # 注意：这些方法运行在主线程，只是修改了工作线程会读取的标志位。
    # QThread 的 start() 方法会创建一个真正的操作系统线程来执行 run()。
    # =========================================================================

    def get_result(self) -> dict | None:
        """取暂存的段位检测结果，取后清空。返回 None 表示还没检测到。

        主窗口在写入 CSV 时调用此方法获取己方/对方段位字符串，
        取完后 _result 被清空，下一局重新检测。
        """
        r = self._result
        self._result = None
        return r

    def stop_searching(self) -> None:
        """通知线程：当前对局已进入阶段2（先后攻出现），段位图标已消失。

        此时如果已经检测到结果（即使只有单方），立即发射给主线程供 CSV 写入。
        正常情况主循环已检测到双方并暂停，此方法仅在主循环未完成时兜底。
        如果还没检测到，直接暂停。
        """
        if self._result and not self._paused:
            self.rank_icon_detected.emit(dict(self._result))
        self._paused = True

    def resume_for_next_game(self) -> None:
        """下一局开始，恢复截图搜索循环。

        主窗口在写入 CSV 后（一局正式结束）调用此方法，
        让检测线程重新开始截图搜索段位图标。

        必须清空 _result：上一局的检测数据还在里面，
        如果不清理，线程恢复后第一帧就会因为双方都已"检测到"
        而直接发射旧结果，导致状态栏显示错乱的段位信息。

        同时清空失败样本缓存（新一局从空缓存开始）。
        """
        self._result = None  # 清除旧数据，否则会被误发射
        self._paused = False
        if self._failure_mgr is not None:
            self._failure_mgr.clear_cache()

    def stop(self) -> None:
        """优雅停止线程。不强制 kill，只把 _running 设为 False。

        工作线程在下一轮循环的开头检查 _running，发现 False 就退出 run()。
        msleep 保证最多等待一轮间隔时间（默认 0.5 秒）。
        """
        self._running = False

    # =========================================================================
    # 线程主循环 — 在独立线程中运行，不能操作 UI
    # =========================================================================

    def run(self) -> None:
        """QThread 的主入口，运行在独立线程中。

        生命周期:
            1. 循环截图 Master Duel 窗口
            2. 跳过已检测到的侧（player/opponent），只搜未检测到的
            3. 调用 detect_rank_icon() 做模板匹配
            4. 合并多次的结果（可能第一次只检测到 player，第二次检测到 opponent）
            5. 双方都检测到 → 发射信号 → 暂停等待下一局
            6. 对局结束 → 主窗口调用 resume_for_next_game() → 继续循环

        退出条件:
            - _running 被设为 False（stop() 被调用）
            - Master Duel 窗口关闭
        """
        self._running = True

        while self._running:
            # ---- 暂停检查 ----
            if self._paused:
                self.msleep(200)  # 暂停时每 200ms 检查一次是否恢复
                continue

            # ---- 窗口状态检查 ----
            # Master Duel 窗口关闭 → 停止线程
            if not _cap.is_window_open("masterduel"):
                self._running = False
                break
            # 窗口最小化时跳过截图（截图会截到桌面或其他窗口）
            if _cap.is_window_minimized("masterduel"):
                self.msleep(int(self._interval * 1000))
                continue

            # ---- 截图 ----
            try:
                screenshot = _cap.capture_window("masterduel")
            except OSError:
                self.msleep(int(self._interval * 1000))
                continue

            if screenshot is None:  # 截图失败（如窗口被遮挡）
                self.msleep(int(self._interval * 1000))
                continue

            # ---- 跳过已检测到的侧 ----
            # 例如：第一帧检测到 player 是 "铂金 II"，之后跳过 player 只搜 opponent
            skip: set[str] = set()
            if self._result:
                if self._result.get("player_rank"):
                    skip.add("player")
                if self._result.get("opponent_rank"):
                    skip.add("opponent")

            # ---- 检测段位图标 ----
            try:
                result = _det.detect_rank_icon(screenshot, self._threshold,
                                               skip_sides=skip or None)
            except (cv2.error, ValueError):
                result = {}  # 检测异常时返回空结果，下一轮重试

            # ---- 失败样本记录：段位图标两项 ----
            # 和三阶段检测同理：每个 target 独立提交自己的置信度分数。
            # 段位图标比较特殊——除了图标 NCC 匹配分数外，
            # 还有"等级数字识别"（I~V 的列投影），其分数也写入 TOML 供诊断。
            if self._failure_mgr is not None and result:
                # 收集窗口信息（排查多显示器/DPI 缩放问题）
                size = _cap.get_client_size("masterduel")
                rect = _cap.get_window_rect("masterduel")
                for side, target in [("player", "my_rank_icon"),
                                     ("opponent", "opponent_rank_icon")]:
                    # 该侧的段位图标 NCC 匹配分数
                    side_score = float(result.get(f"{side}_score", 0.0))
                    rank_label = result.get(f"{side}_rank")
                    # 原始图标文件名（如 "img_rankicon_04"，用于拼接完整路径）
                    icon_name = result.get(f"{side}_icon")
                    # 等级数字识别结果（I~V，巅峰没有）
                    tier_val = result.get(f"{side}_tier")
                    tier_score = float(result.get(f"{side}_tier_score", 0.0))

                    # 段位图标不用 ROI 系统（用位置缓存），不传 roi 字段
                    extra: dict = {
                        "all_scores": _det.get_rank_icon_all_scores(side),
                    }
                    if icon_name:
                        extra["matched_template"] = f"resource/templates/rankicons/{icon_name}_l.png"
                    if isinstance(tier_val, int) and 1 <= tier_val <= 5:
                        tier_str = ["", "I", "II", "III", "IV", "V"][tier_val]
                        extra["tier_detected"] = tier_str
                        extra["tier_score"] = tier_score
                    if size:
                        extra["client_size"] = f"{size[0]}x{size[1]}"
                    if rect:
                        extra["window_rect"] = rect

                    self._failure_mgr.consider(
                        target, side_score, screenshot,
                        self._threshold, extra)

            # ---- 合并多次检测结果 ----
            # 记录合并前的状态，用于判断是否有新发现
            had_player = bool(self._result.get("player_rank")) if self._result else False
            had_opponent = bool(self._result.get("opponent_rank")) if self._result else False

            if self._result:
                for k in ("player_rank", "player_tier", "player_score",
                          "player_tier_score", "player_icon",
                          "opponent_rank", "opponent_tier", "opponent_score",
                          "opponent_tier_score", "opponent_icon"):
                    if not self._result.get(k) and result.get(k):
                        self._result[k] = result[k]
            else:
                self._result = result

            # ---- 发射信号（仅在新发现时） ----
            has_player = bool(self._result.get("player_rank")) if self._result else False
            has_opponent = bool(self._result.get("opponent_rank")) if self._result else False

            if (has_player and not had_player) or (has_opponent and not had_opponent):
                if has_player and has_opponent:
                    # 双方齐备 → 完整结果
                    self.rank_icon_detected.emit(dict(self._result))
                    self._paused = True
                else:
                    # 首次检测到单方 → 增量进度（状态栏实时反馈）
                    self.partial_update.emit(dict(self._result))

            # 等待指定间隔后进入下一轮截图
            self.msleep(int(self._interval * 1000))
