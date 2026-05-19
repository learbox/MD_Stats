"""后台识别工作线程 — 定时截图并用模板匹配识别对局信息。

================================================================================
设计原理
================================================================================

本模块定义 StatsWorker 类，继承自 PySide6 的 QThread。
将图像识别逻辑放在独立线程中的原因:

    1. 不阻塞 GUI: 截图 + 模板匹配是 CPU 密集型操作，如果在主线程执行，
       会导致 GUI 界面冻结、按钮无响应。

    2. 定时循环: 需要每隔 N 秒（默认 0.5s）执行一次截图和识别，
       使用 QThread.msleep() 不会阻塞 Qt 事件循环。

    3. 线程安全通信: 通过 Qt 的信号/槽机制（Signal/Slot）将识别结果
       发送到主线程更新 GUI，这是 Qt 中跨线程通信的标准做法。

================================================================================
状态机（三阶段）
================================================================================

识别过程使用三状态的状态机，对应 Master Duel 对局的三个阶段:

    ┌──────────────┐  赢/输硬币识别   ┌──────────────┐  先/后攻识别    ┌───────────────┐
    │ WAITING_COIN │───────────────→│ WAITING_TURN │──────────────→│ WAITING_RESULT│
    │ (等待硬币)    │                │ (等待先后攻)    │               │ (等待胜负)    │
    └──────────────┘                └──────────────┘               └───────┬───────┘
           ↑                                                               │
           │                      胜负识别成功                               │
           └───────────────────────────────────────────────────────────────┘

状态说明:
    - WAITING_COIN:  当前不在对局中，等待硬币画面出现。
                     检测到赢/输硬币后切换到 WAITING_TURN。

    - WAITING_TURN:  硬币已识别，等待先后攻 UI 出现。
                     检测到先攻/后攻后切换到 WAITING_RESULT。

    - WAITING_RESULT: 先后攻已知，等待对局结束的结果画面。
                      检测到胜利/失败后写入 CSV 并切回 WAITING_COIN。

启动流程: 获取客户区尺寸 → set_resolution → init_templates（预加载缓存）。
         模板缺失时 worker 直接退出，状态栏显示具体缺失信息。

顺序依赖: 前一个阶段未识别到，不会尝试识别后续阶段。
         这防止了误将结果界面中的元素识别为硬币/先后攻等问题。

================================================================================
线程安全
================================================================================

- _running 标志: 简单的布尔值，由主线程在 stop() 中设为 False，
  工作线程在 while 循环中检查。在 CPython 中，由于 GIL 的存在，
  布尔值的读写是原子操作，不会出现数据竞争。

- Signal 发射: PySide6 的 Signal 是线程安全的，可以在子线程中 emit，
  Qt 会自动将信号投递到主线程的事件队列中处理。

- 停止机制: stop() 设置 _running = False，线程在下一次循环迭代时退出。
  最坏情况下等待时间 = interval（默认 0.5 秒）。
"""


from PySide6.QtCore import QThread, Signal

from src import capture as _cap
from src import detector as _det
from src.config import load_config


class StatsWorker(QThread):
    """后台工作线程：循环执行"截图 → 识别硬币 → 识别先后攻 → 识别胜负"。

    Signals:
        status_update(str):
            状态更新消息，显示在 GUI 状态栏中。

        coin_win_detected(str):
            硬币输赢识别结果。
            取值为 'win'（赢硬币）或 'lose'（输硬币）。

        turn_detected(str):
            先后攻识别结果。
            取值为 'first'（先攻）或 'second'（后攻）。

        result_detected(str):
            对局胜负识别结果。
            取值为 'win'（胜）或 'lose'（负）。

    Attributes:
        _interval:   截图间隔时间（秒），从配置读取。
        _threshold:  模板匹配置信度阈值，从配置读取。
        _running:    bool，控制线程运行/停止。
        _state:      str，当前状态机状态。
    """

    # -----------------------------------------------------------------------
    # Qt 信号定义
    # -----------------------------------------------------------------------
    status_update = Signal(str)
    coin_win_detected = Signal(str)
    turn_detected = Signal(str)
    result_detected = Signal(str)

    def __init__(self, parent=None):
        """初始化工作线程。从 config.toml 读取截图间隔和匹配阈值。"""
        super().__init__(parent)
        cfg = load_config()
        self._interval: float = cfg.get("detection", {}).get("interval", 0.5)
        self._threshold: float = cfg.get("detection", {}).get("confidence_threshold", 0.8)
        self._running = False
        self._state = "WAITING_COIN"

    def _skip(self) -> None:
        """休眠一个间隔后继续循环。"""
        self.msleep(int(self._interval * 1000))

    def _ensure_templates(self, last_size: tuple[int, int] | None) -> tuple[int, int] | None:
        """检测分辨率变化并刷新模板缓存。返回当前客户区尺寸或 None。

        窗口最小化时 GetClientRect 返回 (0, 0)，通过 case guard 过滤掉。
        """
        match _cap.get_client_size("masterduel"):
            case (w, h) if w > 0 and h > 0:
                if (w, h) != last_size:
                    _det.set_resolution(w, h)
                    msg = _det.init_templates()
                    if msg is not None:
                        self.status_update.emit(msg)
                        return None
                return w, h
            case _:
                return None

    def run(self) -> None:
        """线程的入口函数（由 QThread.start() 自动调用）。

        启动阶段:
            等待窗口可用并加载模板。窗口最小化或未启动时自动重试，
            恢复后自动继续，无需手动重启。

        主循环:
            1. 检测分辨率变化，变化时刷新模板缓存
            2. 窗口最小化时跳过本轮
            3. 截取 Master Duel 窗口客户区
            4. 根据当前状态执行对应的识别
            5. 识别成功后发射信号并切换到下一状态
            6. 休眠 interval 秒
            7. 检测窗口是否仍在运行，若已关闭则自动停止
        """
        self._running = True

        # ---- 启动阶段：等待窗口可用并初始化模板 ----
        self.status_update.emit("正在运行 — 等待 Master Duel 窗口…")
        _last_resolution = None
        _warned = False
        while self._running:
            size = self._ensure_templates(_last_resolution)
            if size is not None:
                _last_resolution = size
                break
            if not _warned and _cap.is_window_minimized("masterduel"):
                self.status_update.emit("Master Duel 窗口已最小化 — 请恢复窗口")
                _warned = True
            self._skip()
        if not self._running:
            return

        self._state = "WAITING_COIN"
        self.status_update.emit("正在运行 — 等待识别硬币…")

        # ---- 主循环 ----
        _paused = False
        while self._running:
            # ---- 第 0 步：每轮更新模板分辨率 ----
            size = self._ensure_templates(_last_resolution)
            if size is None:
                if not _paused:
                    _paused = True
                    if _cap.is_window_minimized("masterduel"):
                        self.status_update.emit("窗口已最小化 — 等待恢复…")
                self._skip()
                continue

            # ---- 第 1 步：检测窗口是否最小化 ----
            if _cap.is_window_minimized("masterduel"):
                if not _paused:
                    _paused = True
                    self.status_update.emit("窗口已最小化 — 等待恢复…")
                self._skip()
                continue

            if _paused:
                _paused = False
                state_msgs = {
                    "WAITING_COIN": "正在运行 — 等待识别硬币…",
                    "WAITING_TURN": "正在运行 — 等待识别先后攻…",
                    "WAITING_RESULT": "正在运行 — 等待识别胜负…",
                }
                self.status_update.emit(state_msgs.get(self._state, "正在运行"))
            _last_resolution = size

            # ---- 第 2 步：截取 Master Duel 窗口 ----
            try:
                screenshot = _cap.capture_window("masterduel")
            except (OSError, RuntimeError) as e:
                self.status_update.emit(f"截图失败: {e}")
                self._skip()
                continue

            # ---- 第 3 步：根据当前状态执行对应阶段的识别 ----
            if self._state == "WAITING_COIN":
                coin_win = _det.detect_coin_win(screenshot, self._threshold)
                if coin_win:
                    self.coin_win_detected.emit(coin_win)
                    coin_text = "赢硬币" if coin_win == "win" else "输硬币"
                    self.status_update.emit(
                        f"已识别: {coin_text} — 等待识别先后攻…"
                    )
                    self._state = "WAITING_TURN"

            elif self._state == "WAITING_TURN":
                turn = _det.detect_turn(screenshot, self._threshold)
                if turn:
                    self.turn_detected.emit(turn)
                    turn_text = "先攻" if turn == "first" else "后攻"
                    self.status_update.emit(
                        f"已识别: {turn_text} — 等待识别对局胜负…"
                    )
                    self._state = "WAITING_RESULT"

            elif self._state == "WAITING_RESULT":
                result = _det.detect_result(screenshot, self._threshold)
                if result:
                    self.result_detected.emit(result)
                    result_text = "胜" if result == "win" else "负"
                    self.status_update.emit(
                        f"已识别结果: {result_text} — 等待下一局…"
                    )
                    self._state = "WAITING_COIN"

            # ---- 第 4 步：休眠等待下一轮 ----
            self.msleep(int(self._interval * 1000))

            # ---- 第 5 步：检测 Master Duel 窗口是否仍在运行 ----
            if not _cap.is_window_open("masterduel"):
                self._running = False
                self.status_update.emit("程序已关闭 — Master Duel 窗口未找到")
                break

    def jump_to(self, stage: int) -> None:
        """外部通知阶段跳转 — 手动按钮触发时，主线程调用此方法同步状态。

        主线程不必知道内部 _state 是字符串，由本方法完成映射。

        Args:
            stage: 0=等硬币, 1=等先后攻, 2=等胜负。
        """
        _STATE_MAP = {0: "WAITING_COIN", 1: "WAITING_TURN", 2: "WAITING_RESULT"}
        self._state = _STATE_MAP[stage]

    def stop(self) -> None:
        """停止工作线程。

        设置 _running = False，线程将在下一次循环检查时退出。
        不会立即中断线程（不使用 terminate()），保证资源正确释放。
        """
        self._running = False
        self.status_update.emit("已停止")
