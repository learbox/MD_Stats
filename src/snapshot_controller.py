"""截图控制器 — 管理全局热键注册、截图动作和周期截图。

将热键/截图相关的业务逻辑从 MainWindow 中提取出来，
MainWindow 只需持有 SnapshotController 实例并通过信号接收状态消息。

================================================================================
架构
================================================================================

    MainWindow
      └── SnapshotController(QObject)
            ├── HotkeyListener — 独立线程监听 WM_HOTKEY
            └── _periodic_timer — 周期截图定时器

    信号流向:
        HotkeyListener.hotkey_pressed → SnapshotController._on_hotkey_pressed
        HotkeyListener.register_failed → SnapshotController._on_register_failed
        SnapshotController.status_message → MainWindow._show_status
"""

from datetime import datetime

import cv2

from PySide6.QtCore import QObject, QTimer, Signal
from src.config import get_project_root
from src.hotkey_listener import HotkeyListener, parse_hotkey


class SnapshotController(QObject):
    """管理截图热键的注册、回调和周期截图。

    信号:
        status_message(str) — 通知主窗口更新状态栏
    """

    status_message = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._periodic_timer: QTimer | None = None
        self._hotkey_listener = HotkeyListener(self)
        self._hotkey_listener.hotkey_pressed.connect(self._on_hotkey_pressed)
        self._hotkey_listener.register_failed.connect(self._on_register_failed)

    def update_config(self, config: dict) -> None:
        """更新配置引用（重载配置时调用）。"""
        self._config = config

    def sync_hotkeys(self) -> None:
        """根据 hotkey_enabled 开关同步热键注册/注销。独立于检测启停。"""
        if self._config.get("debug", {}).get("hotkey_enabled", False):
            self._register_hotkeys()
        else:
            self.unregister_hotkeys()

    def unregister_hotkeys(self) -> None:
        """注销所有热键。"""
        self._hotkey_listener.stop()

    # =========================================================================
    # 内部方法
    # =========================================================================

    def _register_hotkeys(self) -> None:
        """注册全局热键。被占用时状态栏提示。"""
        cfg = self._config.get("debug", {})
        hotkeys = []
        for hid, name in [(1, "snapshot_hotkey"), (2, "periodic_hotkey")]:
            combo = cfg.get(name, "")
            if not combo:
                continue
            mod, vk = parse_hotkey(combo)
            if vk:
                hotkeys.append((hid, mod, vk, combo))
        if hotkeys:
            self._hotkey_listener.start(hotkeys)
        if cfg.get("hotkey_enabled", False):
            self.status_message.emit("截图热键已启用")

    def _on_hotkey_pressed(self, hotkey_id: int) -> None:
        """热键按下回调（由 HotkeyListener 信号触发，在主线程中执行）。"""
        if hotkey_id == 1:
            self._snapshot_single()
        elif hotkey_id == 2:
            self._toggle_periodic()

    def _on_register_failed(self, combo: str) -> None:
        """热键注册失败回调。"""
        self.status_message.emit(f"热键 {combo} 注册失败（可能被其他程序占用）")

    def _snapshot_single(self) -> None:
        """热键 1 回调：截取 Master Duel 窗口并保存到 screenshots/ 目录。

        与自动检测截图不同——此方法不管是否有对局在进行、是否检测到任何
        事件，直接截取当前窗口。适合用户手动截取特定 UI 画面作为模板。
        文件名格式：screenshot_1920x1080_20260612_143025_123.png（含分辨率和毫秒时间戳）。
        """
        try:
            from src import capture as _cap
            screenshot = _cap.capture_window("masterduel")
            ss_dir = get_project_root() / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)
            h, w = screenshot.shape[:2]
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 去掉最后3位微秒
            fname = f"screenshot_{w}x{h}_{ts}.png"
            success, buf = cv2.imencode('.png', screenshot)
            if success:
                (ss_dir / fname).write_bytes(buf.tobytes())
                self.status_message.emit(f"截图已保存: {fname}")
            else:
                self.status_message.emit("截图保存失败")
        except Exception as e:
            self.status_message.emit(f"截图失败: {e}")

    def _periodic_tick(self) -> None:
        """周期截图定时器回调：直接复用单次截图逻辑。"""
        self._snapshot_single()

    def _toggle_periodic(self) -> None:
        """热键 2 回调：切换周期截图开关。

        第一次按 → 启动 QTimer（间隔取 debug.periodic_interval，默认 0.5s）
        第二次按 → 停止定时器，不再截图
        """
        if self._periodic_timer is not None:
            self._periodic_timer.stop()
            self._periodic_timer = None
            self.status_message.emit("周期截图已停止")
            return
        interval = self._config.get("debug", {}).get("periodic_interval", 0.5)
        timer = QTimer(self)
        timer.timeout.connect(self._periodic_tick)
        timer.start(int(interval * 1000))
        self._periodic_timer = timer
        self.status_message.emit(f"周期截图已开始（{interval}s 间隔）")
