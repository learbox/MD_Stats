"""屏幕截图模块 — 跨平台窗口定位 + 高性能截图。

================================================================================
平台适配

本模块根据操作系统自动选择底层实现：

    Windows → capture_win.py（pywin32 窗口定位 + mss DirectX 截图）
    macOS   → capture_mac.py（Quartz 窗口定位 + mss CoreGraphics 截图）

对外提供统一的 6 个公开函数，调用方不需要关心平台差异。

================================================================================
公开 API

    get_window_status(title)   → (hwnd_or_info, (w,h), is_minimized)
    is_window_open(title)      → bool
    get_client_size(title)     → (w, h) | None
    is_window_minimized(title) → bool
    capture_window(title)      → np.ndarray (H, W, 3) BGR
    capture_screen(index, region) → np.ndarray (H, W, 3) BGR
"""

import os as _os

if _os.name == "nt":
    # Windows
    from src.capture_win import (        # noqa: F401
        get_window_status,
        is_window_open,
        get_client_size,
        is_window_minimized,
        capture_window,
        capture_screen,
    )
else:
    # macOS / Linux
    from src.capture_mac import (        # noqa: F401
        get_window_status,
        is_window_open,
        get_client_size,
        is_window_minimized,
        capture_window,
        capture_screen,
    )
