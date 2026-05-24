"""macOS 窗口定位与截图 — 基于 Quartz (CoreGraphics) + mss。

================================================================================
技术栈

Quartz (pyobjc-framework-Quartz) — macOS 的窗口管理框架
    CGWindowListCopyWindowInfo — 枚举所有窗口
    kCGWindowName / kCGWindowOwnerName — 窗口标题和所属程序名

mss — 高性能截图（macOS 底层走 CoreGraphics，GPU 加速）

================================================================================
坐标系警告

macOS 的 CoreGraphics 坐标系原点在屏幕左下角，而 Windows 在左上角。
mss 库的 region 参数使用左上角为原点的坐标系，所以需要转换：
    mac_y = screen_height - window_top - window_height

================================================================================
权限要求

macOS 要求用户在"系统设置 → 隐私与安全性 → 屏幕录制"中授权终端
或 Python 程序，否则 CGWindowListCopyWindowInfo 和截图都会失败。
"""

import numpy as np
import mss
import Quartz


# =============================================================================
# 内部：窗口查找
# =============================================================================

def _find_window_info(title_substring: str) -> dict | None:
    """遍历所有可见窗口，按标题关键词模糊匹配，返回首个命中窗口信息字典。

    CGWindowListCopyWindowInfo 返回的每个窗口字典包含：
        kCGWindowName        — 窗口标题
        kCGWindowOwnerName   — 所属程序名（如 "Yu-Gi-Oh! Master Duel"）
        kCGWindowBounds      — 窗口在屏幕上的位置和尺寸（CGRect -> dict）
        kCGWindowLayer       — 窗口层级（0=普通窗口）
        kCGWindowAlpha       — 窗口不透明度

    注意：macOS 没有 Windows 的"最小化窗口"概念。窗口被隐藏到 Dock
    时不再出现在 CGWindowListCopyWindowInfo 的普通窗口列表中。
    """
    # kCGWindowListOptionOnScreenOnly = 只列出当前屏幕上的窗口
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    )

    for window in window_list:
        # 跳过系统窗口（Dock、菜单栏等）
        layer = window.get(Quartz.kCGWindowLayer, 0)
        if layer != 0:
            continue

        # 窗口标题匹配（大小写不敏感）
        name = window.get(Quartz.kCGWindowName, "") or ""
        if title_substring.lower() in name.lower():
            return window

    # 如果标题匹配失败，尝试按程序名匹配
    for window in window_list:
        layer = window.get(Quartz.kCGWindowLayer, 0)
        if layer != 0:
            continue
        owner = window.get(Quartz.kCGWindowOwnerName, "") or ""
        if title_substring.lower() in owner.lower():
            return window

    return None


def _get_screen_region(window_info: dict) -> list[int]:
    """把 CGWindowBounds 转成 mss 兼容的 [left, top, width, height] 区域。

    macOS 的 CGWindowBounds 用左下角为原点的 Y 坐标。
    mss 需要左上角为原点的坐标。所以要做 Y 轴翻转：
        mss_top = screen_height - mac_y - height

    参数:
        window_info: CGWindowListCopyWindowInfo 返回的窗口字典

    返回:
        [left, top, width, height] — mss 兼容的截图区域（像素）
    """
    bounds = window_info.get(Quartz.kCGWindowBounds, {})
    x = int(bounds.get("X", 0))
    y = int(bounds.get("Y", 0))      # macOS 坐标：左下角为原点
    w = int(bounds.get("Width", 0))
    h = int(bounds.get("Height", 0))

    # 获取主屏幕高度用于坐标翻转
    main_display = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    screen_h = int(main_display.size.height)

    # macOS 的 Y 坐标是窗口左下角到屏幕底部的距离
    # mss 需要窗口左上角到屏幕顶部的距离
    mss_top = screen_h - y - h if y + h <= screen_h else 0

    return [x, mss_top, w, h]


# =============================================================================
# 公开 API
# =============================================================================

def get_window_status(title_substring: str = "masterduel"):
    """一次查询窗口是否存在、客户区尺寸、是否最小化。

    macOS 没有"最小化"概念（最小化 = 隐藏到 Dock，不在窗口列表中）。
    所以 is_minimized 始终返回 False（找不到窗口时也可能被视为隐藏）。

    返回:
        (None, None, False) — 未找到窗口
        (window_info, (width, height), False) — 找到窗口
    """
    info = _find_window_info(title_substring)
    if info is None:
        return None, None, False
    bounds = info.get(Quartz.kCGWindowBounds, {})
    w = int(bounds.get("Width", 0))
    h = int(bounds.get("Height", 0))
    return info, (w, h), False


def is_window_open(title_substring: str = "masterduel") -> bool:
    """检测指定标题的窗口是否当前可见。"""

    return _find_window_info(title_substring) is not None


def get_client_size(title_substring: str = "masterduel"):
    """获取窗口渲染区域尺寸。macOS 上窗口边界即渲染区域。"""

    info = _find_window_info(title_substring)
    if info is None:
        return None
    bounds = info.get(Quartz.kCGWindowBounds, {})
    return int(bounds.get("Width", 0)), int(bounds.get("Height", 0))


def is_window_minimized(title_substring: str = "masterduel") -> bool:
    """判断窗口是否被最小化。

    macOS 上最小化窗口不在窗口列表中，所以这儿返回 not is_window_open。
    如果需要更精确的判断（窗口存在但隐藏 vs 完全没开），
    需要用 NSWorkspace.runningApplications 检查进程状态。
    """
    # 简化处理：找不到窗口就当"最小化或不存在"
    return not is_window_open(title_substring)


def capture_window(title_substring: str = "masterduel") -> np.ndarray:
    """截取指定窗口。

    抛出 RuntimeError 如果窗口未找到。
    """
    info = _find_window_info(title_substring)
    if info is None:
        raise RuntimeError(f"未找到标题包含 '{title_substring}' 的窗口")
    region = _get_screen_region(info)
    return capture_screen(region=region)


def capture_screen(monitor_index: int = 0,
                   region: list[int] | None = None) -> np.ndarray:
    """截取指定显示器或区域的屏幕画面。mss 跨平台，代码同 Windows。"""
    with mss.MSS() as sct:
        monitors: list[dict] = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 0

        if region and len(region) == 4:
            x, y, w, h = region
            monitor = {"left": x, "top": y, "width": w, "height": h}
        else:
            monitor = monitors[monitor_index]

        img = sct.grab(monitor)
        arr: np.ndarray = np.array(img)[:, :, :3]
        return arr
