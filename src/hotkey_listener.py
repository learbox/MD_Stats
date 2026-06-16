"""Windows 全局热键监听器 — 在独立线程中接收 WM_HOTKEY 消息。

绕过 PySide6 的 nativeEvent，直接在 Windows 消息循环中处理全局热键，
避免无边框窗口下 nativeEvent 收不到 WM_HOTKEY 的问题。

================================================================================
原理
================================================================================

    RegisterHotKey(hwnd, id, mod, vk)
        - hwnd=NULL 时，WM_HOTKEY 消息被发送到调用线程的消息队列
        - hwnd=窗口句柄 时，WM_HOTKEY 消息被发送到指定窗口

    当 hwnd=NULL 时，需要在线程的消息循环中用 GetMessage/PeekMessage 接收
    消息。Qt 的 nativeEvent 机制在无边框窗口下可能收不到 WM_HOTKEY，
    因此我们在独立线程中运行 Windows 消息循环，绕过 Qt 直接处理。

================================================================================
线程安全
================================================================================

    hotkey_pressed / register_failed 信号从子线程 emit，
    Qt 自动使用 QueuedConnection 投递到主线程事件队列，
    槽函数在主线程中执行，可以安全操作 GUI。
"""

import ctypes
import ctypes.wintypes
import threading

from PySide6.QtCore import QObject, Signal


def parse_hotkey(combo: str) -> tuple[int, int]:
    """解析热键字符串为 Windows API 所需的 (修饰键位掩码, 虚拟键码)。

    例如 "Ctrl+Shift+S" → (MOD_CONTROL | MOD_SHIFT = 0x0006, ord('S') = 0x53)

    RegisterHotKey 需要两个参数：
        fsModifiers — 修饰键的位掩码（MOD_ALT=0x0001, MOD_CONTROL=0x0002,
                      MOD_SHIFT=0x0004, MOD_WIN=0x0008）
        vk          — 主键的虚拟键码（A-Z → ord('A')-ord('Z'),
                      F1-F12 → 0x70-0x7B）
    """
    _modifiers = {"Ctrl": 0x0002, "Shift": 0x0004, "Alt": 0x0001, "Win": 0x0008}
    keys = combo.split("+")
    mod = 0
    vk = 0
    for k in keys:
        k = k.strip()
        if k in _modifiers:
            mod |= _modifiers[k]               # 累加修饰键位掩码
        elif len(k) == 1:
            vk = ord(k.upper())              # 单个字母/数字的虚拟键码
        else:
            for i in range(1, 13):           # F1-F12
                if k == f"F{i}":
                    vk = 0x70 + i - 1
                    break
    return mod, vk


class HotkeyListener(QObject):
    """在独立线程中监听 Windows 全局热键。

    使用 RegisterHotKey(None, id, mod, vk) 注册热键（hwnd=NULL），
    此时 WM_HOTKEY 消息会被发送到调用线程的消息队列。
    在独立线程中运行 GetMessageW 循环接收消息，收到后通过 Qt 信号
    通知主线程。

    信号:
        hotkey_pressed(int)  — 热键被按下，参数为热键 ID
        register_failed(str) — 热键注册失败，参数为失败的热键组合字符串
    """

    hotkey_pressed = Signal(int)
    register_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._ready = threading.Event()

    def start(self, hotkeys: list[tuple[int, int, int, str]]) -> None:
        """注册热键并启动监听线程。

        Args:
            hotkeys: [(id, mod, vk, combo_str), ...] 的列表
                     id: 热键 ID（用于区分不同热键）
                     mod: 修饰键位掩码 (MOD_ALT=1, MOD_CONTROL=2, MOD_SHIFT=4, MOD_WIN=8)
                     vk: 虚拟键码
                     combo_str: 热键组合字符串（如 "Ctrl+Shift+S"，用于注册失败时提示）
        """
        self.stop()
        self._ready.clear()
        thread = threading.Thread(
            target=self._run, args=(hotkeys,), daemon=True
        )
        self._thread = thread
        thread.start()
        # 等待线程启动并记录 thread_id（最多 2 秒）
        self._ready.wait(timeout=2)

    def stop(self) -> None:
        """停止监听线程并注销热键。"""
        if self._thread is not None and self._thread.is_alive():
            # Post WM_QUIT 到线程的消息队列以退出 GetMessage 循环
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, 0x0012, 0, 0  # WM_QUIT = 0x0012
            )
            self._thread.join(timeout=2)
        self._thread = None
        self._thread_id = 0

    def _run(self, hotkeys: list[tuple[int, int, int, str]]) -> None:
        """子线程入口：注册热键 → 消息循环 → 注销热键。"""
        user32 = ctypes.windll.user32

        # 记录线程 ID，主线程需要用它来 PostThreadMessage
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._ready.set()

        # 注册热键（hwnd=NULL，消息发送到本线程的消息队列）
        registered_ids: list[int] = []
        for hid, mod, vk, combo in hotkeys:
            if user32.RegisterHotKey(None, hid, mod, vk):
                registered_ids.append(hid)
            else:
                self.register_failed.emit(combo)

        # 消息循环 — GetMessage 在收到 WM_QUIT 时返回 0，退出循环
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                self.hotkey_pressed.emit(msg.wParam)

        # 注销所有已注册的热键
        for hid in registered_ids:
            user32.UnregisterHotKey(None, hid)
