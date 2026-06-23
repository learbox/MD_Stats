"""后台识别工作线程 — 定时截图并用模板匹配识别 Master Duel 对局信息。

================================================================================
为什么需要独立线程？
================================================================================

程序的"启动"按钮被点击后，会进入一个无限循环：
    每隔 N 秒截图 → 和模板图片比 → 判断是否匹配 → 重复

如果在主线程（GUI 线程）里跑这个循环，后果是：
    - 截图和图像匹配是 CPU 密集型操作，会占用主线程的全部时间
    - Qt 的事件循环（event loop）被阻塞，按钮点击无响应
    - 窗口拖不动、关不掉、界面"假死"

解决方案：用 PySide6 的 QThread 把循环放到后台线程。
    主线程 → 负责画界面、处理鼠标点击
    工作线程 → 负责截图、模板匹配、发信号通知主线程

================================================================================
线程间通信：Signal（信号）/ Slot（槽）
================================================================================

Qt 的 Signal/Slot 机制是线程安全的：

    工作线程（子线程）               主线程（GUI 线程）
    ─────────────────                ─────────────────
    self.result_detected.emit("win") → MainWindow._on_result_detected()
                                           ↓
                                      写入 CSV、刷新表格、更新状态栏

    子线程只需要 emit 信号，Qt 会自动把信号投递到主线程的事件队列中，
    由主线程在处理事件时执行对应的槽函数。子线程不用关心 GUI 更新细节。

================================================================================
状态机（三阶段顺序识别）
================================================================================

Master Duel 的一局对局有三个阶段，出现顺序是固定的：

    ┌──────────────┐  赢/输硬币识别   ┌──────────────┐  先/后攻识别    ┌───────────────┐
    │ WAITING_COIN │───────────────→│ WAITING_TURN │──────────────→│ WAITING_RESULT│
    │ (等待硬币)    │                │ (等待先后攻)    │               │ (等待胜负)    │
    └──────────────┘                └──────────────┘               └───────┬───────┘
           ↑                                                               │
           │                      胜负识别成功，回起点                         │
           └───────────────────────────────────────────────────────────────┘

为什么用状态机而不是每帧所有模板都跑一遍？
    - 速度更快：每次只跑当前阶段相关的 2 张模板，而不是 6 张全跑
    - 防止误匹配：胜负界面里可能有类似"先攻"的文字，但不是对局中的先后攻提示

状态说明:
    WAITING_COIN  → 等待硬币画面出现。检测到赢/输硬币后 → WAITING_TURN
    WAITING_TURN  → 硬币已识别，等待先后攻 UI 出现。检测到后 → WAITING_RESULT
    WAITING_RESULT → 先后攻已知，等待对局结束。检测到胜负后写 CSV → WAITING_COIN

================================================================================
线程安全说明
================================================================================

线程安全是指：多个线程同时访问同一块数据时不会出错。

本程序中：
    - _running 标志：主线程在 stop() 中设为 False，工作线程在 while 循环中读取。
      在 CPython（标准 Python 解释器）中，有 GIL（全局解释器锁）的保护，
      布尔值的简单读写是原子的（不会被拆成多次操作），不会有数据竞争。

    - _state 状态：只在工作线程的 run() 循环中写入，主线程的 jump_to() 也写入。
      虽然理论上存在竞争条件，但实际影响微乎其微——最坏情况是多等一帧（interval 秒）。

    - Signal emit：PySide6 保证跨线程 emit 信号的安全性。

    - 停止方式：stop() 设 _running = False，不使用 QThread.terminate()。
      terminate() 是暴力终止，可能导致锁未释放、文件未关闭等问题。
"""


from datetime import datetime

import cv2
from PySide6.QtCore import QThread, Signal

from src import capture as _cap    # 截图模块：定位窗口、截取客户区
from src import detector as _det   # 识别模块：模板匹配
from src.config import load_config, get_project_root
from src import logger as _log
from src.failure_sample_manager import FailureSampleManager


# =============================================================================
# StatsWorker — 后台识别工作线程
# =============================================================================

class StatsWorker(QThread):
    """后台工作线程：循环执行"截图 → 识别硬币 → 识别先后攻 → 识别胜负"。

    =========================================================================
    生命周期
    =========================================================================

    1. MainWindow._on_start() 创建 StatsWorker 并调用 worker.start()
       → QThread.start() 自动在后台线程中执行 run() 方法

    2. run() 进入主循环，持续截图识别，emit 信号通知主线程

    3. MainWindow._on_stop() 调用 worker.stop() 设 _running = False
       → 工作线程在下一次循环检查时退出

    4. 工作线程退出后发射 finished 信号，MainWindow 安全清理 worker 对象

    =========================================================================
    Signals（信号——工作线程发射，主线程接收）
    =========================================================================

    status_update(str)     — 状态栏消息更新
    coin_win_detected(str) — 硬币识别结果: 'win'（赢）或 'lose'（输）
    rank_detected(str)     — 段位升降结果: 'up'/'down'/''。
                             与 coin_win_detected 同时触发（同一张截图），
                             独立信号不阻塞状态机；'' = 普通局。
    turn_detected(str)     — 先后攻结果: 'first'（先攻）或 'second'（后攻）
    result_detected(str)   — 对局结果: 'win'（胜）或 'lose'（负）

    信号触发顺序 (每局):
        status_update (持续) → coin_win_detected + rank_detected (同时)
        → turn_detected → result_detected → 循环

    =========================================================================
    与 MainWindow 手动按钮的联动
    =========================================================================

    当用户使用手动按钮（赢硬币/先攻/后攻/胜/负）时，主线程调用
    jump_to(stage) 强制跳转状态。这样手动录入和自动识别共享同一状态机，
    互不冲突——手动录入后自动识别直接从新状态继续。
    """

    # ---- Qt 信号定义 ----
    status_update = Signal(str)       # 状态栏消息
    coin_win_detected = Signal(str)   # 硬币识别结果
    rank_detected = Signal(str)       # 段位升降结果（'up'/'down'/''）
    turn_detected = Signal(str)       # 先后攻识别结果
    result_detected = Signal(str)     # 对局胜负结果

    # ---- 常量映射（类属性，所有实例共享一份，节省内存） ----

    # 手动按钮的阶段编号 → 内部状态名
    # stage 0 = 等硬币, stage 1 = 等先后攻, stage 2 = 等胜负
    _STAGE_MAP: dict[int, str] = {
        0: "WAITING_COIN", 1: "WAITING_TURN", 2: "WAITING_RESULT"
    }

    # 每个状态下在状态栏显示的文字
    _STATE_MSGS: dict[str, str] = {
        "WAITING_COIN": "正在运行 — 等待识别硬币…",
        "WAITING_TURN": "正在运行 — 等待识别先后攻…",
        "WAITING_RESULT": "正在运行 — 等待识别胜负…",
    }

    # =========================================================================
    # __init__ — 初始化
    # =========================================================================

    def __init__(self, failure_mgr: FailureSampleManager | None = None,
                 parent=None):
        """初始化工作线程。

        从 config.toml 读取以下参数：
            detection.interval              — 截图间隔（秒），默认 0.5
            detection.confidence_threshold   — 匹配置信度阈值 (0.0~1.0)，默认 0.8
            debug.save_screenshots           — 是否保存检测截图，默认 false
            debug.log_mode                  — 是否开启日志模式，默认 false
            debug.log_scope                 — 日志记录范围列表，默认全开

        如果日志模式开启，同时初始化日志系统（init_log + set_scopes）。
        日志文件路径为项目根目录下的 logs/ 文件夹，文件名为 mdstats_YYYYMMDD.log。

        关于 failure_mgr（最佳失败样本）：
            由 MainWindow 创建并传入，同一实例同时传给 StatsWorker 和
            RankDetector。当用户在设置中勾选「保存最佳失败样本」时生效。
            工作线程在每个检测步骤中调用 failure_mgr.consider()，
            一轮对局结束时调用 failure_mgr.clear_cache()。

        Args:
            failure_mgr: 最佳失败样本管理器实例。为 None 时功能不生效。
            parent: Qt 父对象。

        初始状态为 WAITING_COIN，线程尚未启动（等待 start() 调用）。
        """
        super().__init__(parent)
        self._failure_mgr = failure_mgr
        cfg = load_config()
        # ---- 识别参数 ----
        self._interval: float = cfg.get("detection", {}).get("interval", 0.5)
        self._threshold: float = cfg.get("detection", {}).get("confidence_threshold", 0.8)

        # ---- 调试/实验功能 ----
        # 注意：save_screenshots 控制是否把截图写到磁盘（PNG 文件），
        #       log_mode 控制是否写日志文件（logs/*.log），两者是独立开关。
        #       截图事件的日志记录由 log_scope 中的 "screenshots" 控制，
        #       即使用户没勾选"截图事件"作用域，只要 save_screenshots=true，
        #       截图文件仍然会保存，只是不会在日志中写"已保存"消息。
        dbg = cfg.get("debug", {})
        self._save_screenshots: bool = dbg.get("save_screenshots", False)
        self._auto_clear: bool = dbg.get("auto_clear_screenshots", True)
        self._show_confidence: bool = dbg.get("show_confidence", False)
        if dbg.get("log_mode", False):
            _log.init_log(get_project_root() / "logs")       # 初始化日志文件
            _log.set_scopes(set(dbg.get("log_scope",         # 设置记录范围
                ["status", "screenshots", "errors"])))

        self._running = False        # True = 线程正在运行（由 start() 后的 run() 设置）
        self._state = "WAITING_COIN" # 初始状态：等待检测硬币

        # ---- 截图清除标记 ----
        self._new_game = True

        # ---- 当前游戏窗口分辨率 ----
        # 每次 _ensure_templates 成功时更新，用于截图文件名中的分辨率标注。
        self._current_size: tuple[int, int] | None = None

    # =========================================================================
    # 内部辅助方法
    # =========================================================================

    def _skip(self) -> None:
        """休眠 interval 秒。

        QThread.msleep() 是线程安全的休眠函数，只休眠当前线程，
        不会阻塞主线程的 Qt 事件循环。如果直接用 time.sleep() 也一样，
        但 msleep() 是 Qt 的惯例写法。

        休眠时间 = interval（秒）× 1000（转毫秒）。
        """
        self.msleep(int(self._interval * 1000))

    def _consider_best(
        self, pairs: list[tuple[str, str]], all_scores: dict[str, float],
        screenshot, meta: dict,
    ) -> None:
        """对一组互斥的模板，只对分数最高的那个 target 调用 consider()。

        同一帧中 coin_win 和 coin_lose 不可能同时出现，只保留最佳匹配的
        失败样本才有诊断价值。另一个模板的分数在 TOML 的 [all_scores] 中可见。

        Args:
            pairs: [(target名, 模板名), ...] 如 [("coin_win","coin_win"), ("coin_lose","coin_lose")]
            all_scores: {模板名: 分数} 从 get_last_all_scores() 获取
            screenshot: 截图
            meta: extra_meta 字典
        """
        if self._failure_mgr is None:
            return
        # 找分数最高的
        best_target, best_score = "", 0.0
        for target, key in pairs:
            sc = all_scores.get(key, 0.0)
            if sc > best_score:
                best_score, best_target = sc, target
        if best_target:
            self._failure_mgr.consider(
                best_target, best_score, screenshot, self._threshold, meta)

    def _build_extra_meta(self) -> dict:
        """构建 consider() 所需的 extra_meta 字典。

        从最后一次检测结果中收集诊断信息，写入 TOML 元数据文件。
        收集内容包括：
            - all_scores: 所有候选模板各自的匹配分数（诊断用）
            - matched_template: 实际匹配到的模板名
            - ROI 信息: 搜索区域名称、坐标、来源（预设 or 全图兜底）
            - 窗口信息: 客户区分辨率 + 窗口在屏幕上的位置（排查多显示器问题）

        Returns:
            符合 FailureSampleManager.consider() extra_meta 格式的字典。
        """
        roi_info = _det.get_last_roi_info()
        # 短名称 → 完整路径（如 "coin_win" → "resource/templates/1600x900/coin_win.png"）
        tmpl_name = _det.get_last_matched_template()
        tmpl_path = ""
        if tmpl_name and self._current_size:
            res = f"{self._current_size[0]}x{self._current_size[1]}"
            tmpl_path = f"resource/templates/{res}/{tmpl_name}.png"
        meta: dict = {
            "all_scores": _det.get_last_all_scores(),
            "matched_template": tmpl_path,
        }
        if roi_info:
            meta["roi_name"] = roi_info.get("roi_name", "")
            meta["roi"] = roi_info.get("roi", [])
            meta["roi_source"] = roi_info.get("roi_source", "")
        # 窗口信息
        size = _cap.get_client_size("masterduel")
        if size:
            meta["client_size"] = f"{size[0]}x{size[1]}"
        rect = _cap.get_window_rect("masterduel")
        if rect:
            meta["window_rect"] = rect
        return meta

    def _handle_pause(self, paused: bool) -> bool:
        """处理"窗口不可用"的暂停状态。窗口已关闭时设置 _running = False。

        在主循环中，有两种情况会导致暂停：
            1. 窗口最小化 → 不需要截图，因为看不到内容
            2. 分辨率变化导致模板重载 → 暂时无法识别
            3. 窗口已关闭 → 停止工作线程
        """
        # 窗口已关闭（不是最小化）→ 停止线程
        if not _cap.is_window_open("masterduel"):
            self._running = False
            self.status_update.emit("程序已关闭 — Master Duel 窗口未找到")
            return paused

        if not paused:
            paused = True
            if _cap.is_window_minimized("masterduel"):
                self.status_update.emit("窗口已最小化 — 等待恢复…")
        self._skip()
        return paused

    def _ensure_templates(self, last_size: tuple[int, int] | None) -> tuple[int, int] | None:
        """检测 Master Duel 窗口分辨率是否变化，变化时刷新模板缓存。

        为什么要动态检测分辨率？
            用户可能：
            1. 切换游戏的全屏/窗口模式，分辨率改变
            2. 更换显示器，分辨率改变
            3. 调节游戏内的渲染分辨率

        如果分辨率变了但模板还是旧的，匹配率会极低甚至全失败。
        所以每次循环都检查：当前分辨率 ≠ 上次分辨率 → 重新加载模板。

        返回:
            当前客户区 (宽, 高)，如果窗口不可用则返回 None。

        特殊情况处理：
            - GetClientRect 返回 (0, 0)：窗口最小化或未就绪 → 返回 None
            - 模板加载失败（如文件夹缺失）：emit 错误消息 → 返回 None
        """
        match _cap.get_client_size("masterduel"):
            case (w, h) if w > 0 and h > 0:            # 窗口可用，尺寸有效
                self._current_size = (w, h)
                if (w, h) != last_size:                 # 分辨率变了
                    _det.set_resolution(w, h)            # 设置新分辨率
                    msg = _det.init_templates()          # 重新加载模板
                    if msg is not None:
                        self.status_update.emit(msg)
                        # 仅可选模板缺失（如 rank_up/rank_down）→ 只提示，不阻止启动
                        if "已跳过" not in msg:
                            return None
                return w, h
            case _:                                     # 窗口不可用
                return None

    # =========================================================================
    # 调试截图辅助方法
    # =========================================================================
    #
    # 这两个方法实现了"调试截图"功能的底层逻辑：
    #
    #   对局流程:  硬币检测 → 先后攻检测 → 胜负检测 → 回到等硬币
    #   截图行为:  清除旧图  → 保存 coin → 保存 turn → 保存 result
    #             ↑ 仅在每局第一次检测到硬币时执行清除
    #
    # 清除时机为什么放在"检测到硬币"而不是"检测到胜负"？
    #   因为在胜负检测后，状态机立刻回到 WAITING_COIN，用户可能来不及
    #   查看截图就被清空了。把清除时机延后到下一局的硬币出现，用户有
    #   整个等待下一局的时间来慢慢查看截图。
    # =========================================================================

    @staticmethod
    def _clear_screenshots() -> None:
        """清空 screenshots/ 根目录下的所有 PNG 截图文件。

        注意：仅匹配 screenshots/*.png，不会影响 screenshots/debug/ 子目录。
        因此「最佳失败样本」功能保存的文件不会被自动清除。

        采用逐文件删除的方式（而非 shutil.rmtree 整目录删除），原因：
            - Windows 上刚写入的文件可能被杀毒软件暂时锁定
            - 逐文件删除可以跳过被锁定的文件，继续删除其余文件
            - 不会因为一个文件删除失败而放弃整批清理
        """
        ss_dir = get_project_root() / "screenshots"
        if ss_dir.is_dir():
            deleted = 0
            for f in ss_dir.glob("*.png"):
                try:
                    f.unlink()         # 删除单个文件
                    deleted += 1
                except OSError:
                    pass               # 文件被占用时跳过，不中断整个清理
            _log.write("SCRN", f"已清除 {deleted} 个文件")
        else:
            ss_dir.mkdir(parents=True, exist_ok=True)

    def _save_detection_screenshot(self, screenshot, tag: str) -> None:
        """保存检测截图到 screenshots/ 目录。

        文件名格式: {检测类型}_{分辨率}_{时间戳}.png
        例如: coin_win_1920x1080_20260528_143025_123.png

        为什么用 cv2.imencode 而不是 cv2.imwrite？
            cv2.imwrite 在 Windows 上对含中文字符的路径（如 E:\\文档\\...）
            调用 ANSI API 可能写入失败。cv2.imencode 在内存中完成 PNG 编码，
            不涉及任何文件路径，再用 Python 原生的 write_bytes 写入磁盘 —
            Python 的文件 I/O 使用 Unicode API，能正确处理中文路径。

        为什么检查 C_CONTIGUOUS 标志？
            OpenCV 的 imencode 要求传入的 numpy 数组在内存中是连续存储的。
            mss 截图返回的数组通过 [:, :, :3] 切片后通常仍是连续的，但
            在极少数情况下（如经过某种变换），可能变成非连续视图。
            对非连续数组调用 .copy() 会分配一块连续内存，确保 imencode 正常。

        Args:
            screenshot: BGR 格式的 numpy 数组 (H, W, 3)，来自 capture_window。
            tag: 检测类型标签，如 "coin_win"、"turn_first"、"result_lose"。
        """
        ss_dir = get_project_root() / "screenshots"
        ss_dir.mkdir(parents=True, exist_ok=True)

        # 构造文件名：tag_分辨率_时间戳.png
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 去掉最后3位微秒
        if self._current_size:
            res = f"{self._current_size[0]}x{self._current_size[1]}"
        else:
            res = "unknown"  # 分辨率未知时标记为 unknown
        filepath = ss_dir / f"{tag}_{res}_{timestamp}.png"

        # 确保 numpy 数组在内存中是连续存储的（OpenCV 要求）
        src = screenshot.copy() if not screenshot.flags['C_CONTIGUOUS'] else screenshot

        # 第一步：在内存中把像素数据编码为 PNG 格式（不涉及文件路径）
        success, buf = cv2.imencode('.png', src)
        if not success:
            _log.write("SCRN", f"{tag} 编码失败")
            self.status_update.emit(f"截图保存失败({tag}): 编码错误")
            return

        # 第二步：用 Python 原生文件 I/O 将编码后的字节写入磁盘
        try:
            filepath.write_bytes(buf.tobytes())
            _log.write("SCRN", f"已保存: {filepath.name}")
        except OSError as e:
            _log.write("SCRN", f"{tag} 写入失败: {e}")
            self.status_update.emit(f"截图保存失败({tag}): {e}")

    # =========================================================================
    # run() — 工作线程的主循环（由 QThread.start() 自动调用）
    # =========================================================================

    def run(self) -> None:
        """线程入口函数，包含"启动等待"和"主循环"两个阶段。

        =====================================================================
        启动阶段
        =====================================================================

        目标：等待 Master Duel 窗口出现、加载模板图片。

        过程：
            1. 循环检测窗口是否可用（GetClientRect 返回有效尺寸）
            2. 窗口可用 → 加载模板 → 成功则进入主循环
            3. 窗口不可用 → 休眠 interval 秒 → 重试
            4. 如果窗口最小化 → 发状态消息提示用户

        这个阶段不会导致 CPU 飙升，因为每次循环都休眠 interval 秒。

        =====================================================================
        主循环（每轮执行以下步骤）
        =====================================================================

        每轮循环的步骤：

            [0] 检查分辨率是否变化（变化时重载模板）
            [1] 检查窗口是否最小化（最小化时跳过）
            [2] 截取 Master Duel 窗口客户区
            [3] 根据当前状态执行对应识别
            [4] 休眠 interval 秒
            [5] 检查 Master Duel 是否仍然运行

        状态机识别逻辑（第3步的细节）：

            WAITING_COIN:
                detect_coin_win() 用 win/lose 两张模板匹配屏幕
                  → 匹配到 win → emit coin_win_detected('win') → WAITING_TURN
                  → 匹配到 lose → emit coin_win_detected('lose') → WAITING_TURN
                  → 都没匹配上 → 跳过，下轮继续

            WAITING_TURN:
                detect_turn() 用 first/second 两张模板匹配屏幕
                  → 匹配到 first → emit turn_detected('first') → WAITING_RESULT
                  → 匹配到 second → emit turn_detected('second') → WAITING_RESULT
                  → 都没匹配上 → 跳过，下轮继续

            WAITING_RESULT:
                detect_result() 用 victory/defeat 两张模板匹配屏幕
                  → 匹配到 win → emit result_detected('win') → WAITING_COIN（回起点）
                  → 匹配到 lose → emit result_detected('lose') → WAITING_COIN
                  → 都没匹配上 → 跳过，下轮继续

        =====================================================================
        退出条件
        =====================================================================

        线程在以下情况退出 while 循环：
            1. _running 被设为 False（stop() 被调用）
            2. Master Duel 窗口关闭（is_window_open 返回 False）
        """
        # ---- 统一异常捕获 ----
        # QThread 的 run() 方法运行在子线程中，如果抛出未捕获的异常，
        # Qt 只会把 traceback 打印到 stderr，不会触发 sys.excepthook。
        # 所以这里需要手动包一层 try/except，确保工作线程中的任何
        # 异常（模板匹配崩溃、截图编码失败等）都能被记录到日志中。
        try:
            self._run_impl()
        except Exception as e:
            _log.write("ERROR", f"工作线程异常: {e}")
            self.status_update.emit(f"工作线程异常: {e}")

    def _run_impl(self) -> None:
        """run() 的实际实现。

        从 run() 中拆分出来，让 run() 只负责 try/except 异常捕获。
        这个方法的全部代码就是原来 run() 的主体逻辑，一行未改。
        """
        self._running = True

        # ================================================================
        # 启动阶段：等待 Master Duel 窗口可用 + 加载模板
        # ================================================================
        self.status_update.emit("正在运行 — 等待 Master Duel 窗口…")
        _last_resolution = None   # 上一次的分辨率（用于检测变化）
        _warned = False           # 是否已经发过"窗口最小化"的提示（避免刷屏）
        while self._running:
            # 先检查最小化：GetClientRect 对最小化窗口也返回有效尺寸，
            # 如果不提前拦截，_ensure_templates 会成功 → 直接 break → 跳过最小化提示
            if _cap.is_window_minimized("masterduel"):
                if not _warned:
                    self.status_update.emit("Master Duel 窗口已最小化 — 请恢复窗口")
                    _warned = True
                self._skip()
                continue
            size = self._ensure_templates(_last_resolution)  # 尝试获取分辨率+加载模板
            if size is not None:
                _last_resolution = size
                break  # 成功加载模板，跳出启动等待循环
            self._skip()
        if not self._running:    # stop() 在等待期间被调用
            return

        # 启动完成，进入初始状态
        self._state = "WAITING_COIN"
        self.status_update.emit("正在运行 — 等待识别硬币…")

        # ================================================================
        # 主循环
        # ================================================================
        _paused = False  # 暂停标志（窗口不可用时设为 True）

        while self._running:

            # [0] 每轮都检查分辨率（用户可能中途切换分辨率）
            size = self._ensure_templates(_last_resolution)
            if size is None:
                _paused = self._handle_pause(_paused)
                continue  # 跳过本轮，下轮重试

            # [1] 检查窗口是否最小化（全屏游戏切桌面时视为最小化）
            if _cap.is_window_minimized("masterduel"):
                _paused = self._handle_pause(_paused)
                continue

            # 窗口恢复可用时，发出"恢复识别"的状态消息
            if _paused:
                _paused = False
                self.status_update.emit(
                    self._STATE_MSGS.get(self._state, "正在运行")
                )
            _last_resolution = size  # 更新分辨率记录

            # [2] 截取 Master Duel 窗口客户区
            #     capture_window 内部用 mss 库做高性能截图（Windows 上走 DirectX）
            try:
                screenshot = _cap.capture_window("masterduel")
            except Exception as e:
                # 截图失败的原因很多（窗口关闭/失去焦点/BitBlt拒绝访问等），
                # 统一处理为跳过本帧，外层 run() 的 try/except 负责捕获真正的逻辑 bug
                self.status_update.emit(f"截图失败: {e}")
                self._skip()
                continue

            # [3] 状态机：根据当前阶段执行对应识别
            #
            #     每个 detect_xxx 函数内部会：
            #        a) 根据当前分辨率选择模板子目录
            #        b) 用 OpenCV matchTemplate 逐模板匹配
            #        c) 取最高匹配度，和 threshold 比较
            #        d) 返回匹配到的结果字符串 或 None
            #
            if self._state == "WAITING_COIN":
                # 检测硬币输赢（模板：coin_win.png / coin_lose.png）
                coin_win = _det.detect_coin_win(screenshot, self._threshold)

                # ---- 失败样本记录：硬币（互斥，只保留最佳匹配） ----
                self._consider_best(
                    [("coin_win", "coin_win"), ("coin_lose", "coin_lose")],
                    _det.get_last_all_scores(), screenshot,
                    self._build_extra_meta())

                if coin_win:
                    # 同一张截图检测段位升降（升段/降段/普通局）
                    # 不增加新状态，不影响后续流程，结果随 coin 一起发射
                    coin_score = _det.get_last_score()       # rank 检测前先存 coin 分数
                    rank_result = _det.detect_rank(screenshot, self._threshold)
                    self.rank_detected.emit(rank_result or "")

                    # ---- 失败样本记录：段位升降（互斥，只保留最佳匹配） ----
                    if _det.has_template("rank_up") and _det.has_template("rank_down"):
                        self._consider_best(
                            [("rank_up", "rank_up"), ("rank_down", "rank_down")],
                            _det.get_last_all_scores(), screenshot,
                            self._build_extra_meta())

                    # 调试截图：如果开启了截图保存，在新一局开始前先清除旧截图
                    if self._save_screenshots:
                        if self._new_game and self._auto_clear:
                            self._clear_screenshots()        # 清除上一局的所有截图
                        if self._new_game:
                            self._new_game = False
                        self._save_detection_screenshot(screenshot, f"coin_{coin_win}")
                        if rank_result:                      # 如果是升段/降段局也保存一张
                            self._save_detection_screenshot(screenshot, f"rank_{rank_result}")
                    self.coin_win_detected.emit(coin_win)    # 通知主线程
                    coin_text = "赢硬币" if coin_win == "win" else "输硬币"
                    # 状态栏消息中附加段位升降信息（如有）
                    rank_text = ""
                    if rank_result == "up":
                        rank_text = "（升段局）"
                    elif rank_result == "down":
                        rank_text = "（降段局）"
                    if self._show_confidence:
                        self.status_update.emit(
                            f"已识别: {coin_text}{rank_text} ({coin_score:.2f}) — 等待识别先后攻…")
                    else:
                        self.status_update.emit(
                            f"已识别: {coin_text}{rank_text} — 等待识别先后攻…")
                    self._state = "WAITING_TURN"              # 状态前进一步

            elif self._state == "WAITING_TURN":
                # 检测先后攻（模板：go_first.png / go_second.png）
                turn = _det.detect_turn(screenshot, self._threshold)

                # ---- 失败样本记录：先后攻（互斥，只保留最佳匹配） ----
                self._consider_best(
                    [("turn_first", "go_first"), ("turn_second", "go_second")],
                    _det.get_last_all_scores(), screenshot,
                    self._build_extra_meta())

                if turn:
                    # 调试截图
                    if self._save_screenshots:
                        self._save_detection_screenshot(screenshot, f"turn_{turn}")
                    self.turn_detected.emit(turn)
                    turn_text = "先攻" if turn == "first" else "后攻"
                    turn_score = _det.get_last_score()
                    if self._show_confidence:
                        self.status_update.emit(
                            f"已识别: {turn_text} ({turn_score:.2f}) — 等待识别对局胜负…")
                    else:
                        self.status_update.emit(
                            f"已识别: {turn_text} — 等待识别对局胜负…")
                    self._state = "WAITING_RESULT"

            elif self._state == "WAITING_RESULT":
                # 检测胜负（模板：victory.png / defeat.png）
                result = _det.detect_result(screenshot, self._threshold)

                # ---- 失败样本记录：胜负（互斥，只保留最佳匹配） ----
                self._consider_best(
                    [("result_win", "victory"), ("result_lose", "defeat")],
                    _det.get_last_all_scores(), screenshot,
                    self._build_extra_meta())

                if result:
                    # 调试截图
                    if self._save_screenshots:
                        self._save_detection_screenshot(screenshot, f"result_{result}")
                    self.result_detected.emit(result)          # 通知主线程写入 CSV
                    result_text = "胜" if result == "win" else "负"
                    result_score = _det.get_last_score()
                    if self._show_confidence:
                        self.status_update.emit(
                            f"已识别结果: {result_text} ({result_score:.2f}) — 等待下一局…")
                    else:
                        self.status_update.emit(
                            f"已识别结果: {result_text} — 等待下一局…")
                    self._state = "WAITING_COIN"               # 回到起点，等下一局
                    self._new_game = True                      # 标记新一局开始，下次检测硬币时清除旧截图

                    # ---- 一轮结束 → 清空失败样本缓存 ----
                    if self._failure_mgr is not None:
                        self._failure_mgr.clear_cache()

            # [4] 休眠 interval 秒
            self._skip()

            # [5] 检查 Master Duel 窗口是否仍然在运行
            #     is_window_open 用 pywin32 的 EnumWindows 遍历顶层窗口
            if not _cap.is_window_open("masterduel"):
                self._running = False
                self.status_update.emit("程序已关闭 — Master Duel 窗口未找到")
                break

    # =========================================================================
    # jump_to — 手动按钮跳转状态（主线程调用）
    # =========================================================================

    def jump_to(self, stage: int) -> None:
        """外部通知阶段跳转 — 手动按钮触发时同步状态。

        当用户点击手动按钮（如"赢硬币"→"先攻"→"胜"）时，
        MainWindow 调用此方法强制跳转状态机。

        例如用户手动点了"赢硬币"：
            jump_to(1) → _state = "WAITING_TURN"（跳过自动识别硬币的步骤）

        映射关系（定义在 _STAGE_MAP 中）：
            stage 0 → WAITING_COIN（等硬币）
            stage 1 → WAITING_TURN（等先后攻）
            stage 2 → WAITING_RESULT（等胜负）
        """
        self._state = self._STAGE_MAP[stage]
        if stage == 0:
            self._new_game = True   # 手动回到硬币阶段视为新一局

    # =========================================================================
    # stop — 停止线程
    # =========================================================================

    def stop(self) -> None:
        """停止工作线程。

        实现方式：设置 _running = False，线程在下一次 while 循环检查时退出。

        为什么不直接用 QThread.terminate()？
            terminate() 是暴力杀死线程，相当于任务管理器结束进程：
                - 可能带着未释放的锁退出（死锁风险）
                - 打开的文件可能来不及关闭
                - 已分配的内存可能泄漏
            Qt 官方建议用标志位 + 循环检查的方式优雅退出。

        最坏情况：线程刚进入 self._skip() 休眠，需要等待 interval 秒才能退出。
        如果要立即退出，可以在 stop() 之前先调用 self.quit() + self.wait(timeout)。
        """
        self._running = False
        self.status_update.emit("已停止")
