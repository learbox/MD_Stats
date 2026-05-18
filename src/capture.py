"""屏幕截图模块 — 基于 mss + pywin32 实现高性能屏幕/窗口捕获。

================================================================================
技术选型
================================================================================

mss (Multiple Screen Shots) — 屏幕像素采集：
    Python 生态中最快的截图库之一，原因如下：
    - Windows 上底层调用 DirectX Graphics Diagnostics API（非 GDI），比
      PIL.ImageGrab / PyAutoGUI 快 3-5 倍，且 CPU 占用更低
    - macOS 上底层调用 CoreGraphics，同样走硬件加速路径
    - 返回 BGRA 原始像素缓冲区，与 OpenCV 的 BGR 格式高度兼容，无需额外转码
    - 支持多显示器独立截取、任意坐标区域截取

pywin32 (win32gui) — 窗口定位：
    - 封装 Windows USER32.dll 的窗口管理 API
    - 负责窗口查找、属性读取（标题、位置、可见性、最小化状态）

================================================================================
图像格式转换链
================================================================================

全屏/区域截取:
    mss.grab() → BGRA 原始缓冲区 → numpy (H,W,4) → 丢弃 Alpha → BGR (H,W,3)

窗口截取（仅客户区）:
    win32gui 定位窗口 → GetClientRect 获取渲染区域 → ClientToScreen 转屏幕坐标
    → 传给 mss 做区域截取 → 同上

    注意: 截取的是客户区（游戏实际渲染画面），不含标题栏和窗口边框。
    这确保全屏模式和窗口模式下的截图内容一致。
"""


import numpy as np
import mss
# noinspection PyPackageRequirements
import win32gui


# ---------------------------------------------------------------------------
# 窗口定位工具函数
# ---------------------------------------------------------------------------
#
# Windows 窗口系统核心概念：
#   HWND (Window Handle) — 窗口句柄，Windows 内核为每个顶层窗口分配的
#   唯一整数标识。所有窗口操作（读取标题、获取位置、置顶等）都需要通过 HWND。
#
#   EnumWindows — USER32 提供的顶层窗口枚举 API，会遍历桌面上所有顶层窗口
#   （不包括子窗口/控件），对每个窗口调用一次回调函数。
#
#   回调签名: BOOL CALLBACK EnumWindowsProc(HWND hwnd, LPARAM lParam)
#   回调返回 True 继续枚举，返回 False 停止枚举。
#
#   IsIconic — 判断窗口是否处于"最小化"状态。最小化窗口的 GetWindowRect
#   返回的是任务栏缩略图坐标而非实际窗口区域，因此截图前需要先恢复。


def _find_window_by_title(title_substring: str) -> tuple[int, str] | None:
    """遍历所有顶层可见窗口，按标题关键词模糊匹配，返回首个命中的窗口。

    匹配规则：
        - 只检查可见窗口（IsWindowVisible），忽略隐藏/托盘窗口
        - 大小写不敏感的部分匹配（"masterduel" 可匹配 "Yu-Gi-Oh! Master Duel"）
        - 多个匹配时返回 EnumWindows 遍历到的第一个（遍历顺序由 Z-order 决定）

    Args:
        title_substring: 窗口标题关键词，支持中英文。

    Returns:
        (hwnd, window_title) — 窗口句柄和完整标题，未找到时返回 None。
    """
    # 用于收集匹配结果的容器，嵌套回调函数通过引用修改它
    result: list[tuple[int, str]] = []

    def enum_callback(hwnd: int, _results: list) -> bool:
        """EnumWindows 对每个顶层窗口调用的回调。

        Args:
            hwnd: 当前窗口句柄。
            _results: lParam 传入的 result 列表引用（win32gui 自动透传）。

        Returns:
            True 继续枚举，False 提前终止（此处始终继续直到遍历完）。
        """
        # 跳过不可见窗口（后台窗口、无 WS_VISIBLE 样式的窗口）
        if not win32gui.IsWindowVisible(hwnd):
            return True

        # 获取窗口标题文本（控件可能仅支持 WM_GETTEXT 长度限制，但足够用）
        text: str = win32gui.GetWindowText(hwnd)
        if not text:
            return True

        # 大小写不敏感的模糊匹配
        if title_substring.lower() in text.lower():
            _results.append((hwnd, text))

        return True

    # 发起顶层窗口枚举，result 作为 lParam 在每次回调中透传
    win32gui.EnumWindows(enum_callback, result)

    # 返回第一个匹配项（通常 Z-order 最高的那个）
    return result[0] if result else None


def get_window_status(title_substring: str = "masterduel") -> tuple[int | None, tuple[int, int] | None, bool]:
    """一次 EnumWindows 查询窗口是否存在、客户区尺寸、是否最小化。

    替代分别调用 is_window_minimized + get_client_size（两次遍历），
    调用方通过一次调用拿到全部信息，避免冗余的窗口枚举。

    Args:
        title_substring: 窗口标题关键词，默认 "masterduel"。

    Returns:
        (hwnd, size, is_minimized):
        - hwnd: 窗口句柄或 None（未找到）
        - size: (width, height) 或 None（未找到）
        - is_minimized: 仅 hwnd 非 None 时有效
    """
    found = _find_window_by_title(title_substring)
    if found is None:
        return None, None, False
    hwnd, _title = found
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return hwnd, (right - left, bottom - top), bool(win32gui.IsIconic(hwnd))


def is_window_open(title_substring: str = "masterduel") -> bool:
    """检测指定标题的窗口是否当前可见。

    这是 _find_window_by_title 的轻量封装，供外部模块判断目标程序
    是否正在运行，无需关心 HWND 细节。

    Args:
        title_substring: 窗口标题关键词，默认 "masterduel"。

    Returns:
        True 表示找到了匹配的可见窗口，False 表示未找到。
    """
    return _find_window_by_title(title_substring) is not None


def get_client_size(title_substring: str = "masterduel") -> tuple[int, int] | None:
    """获取窗口客户区的渲染尺寸（不含标题栏和边框）。

    客户区即游戏实际渲染画面的区域。在全屏模式下客户区 = 屏幕分辨率；
    在窗口模式下客户区 < 窗口外框尺寸（窗口多了标题栏和边框）。

    此尺寸用于确定模板匹配时应使用哪个分辨率的模板子目录。

    Args:
        title_substring: 窗口标题关键词，默认 "masterduel"。

    Returns:
        (width, height) 或 None（窗口未找到时）。
    """
    found = _find_window_by_title(title_substring)
    if found is None:
        return None
    hwnd, _title = found
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    # GetClientRect 的 left/top 始终为 0，right/bottom 即宽高
    return right - left, bottom - top


def is_window_minimized(title_substring: str = "masterduel") -> bool:
    """检测指定标题的窗口是否处于最小化状态。

    Args:
        title_substring: 窗口标题关键词，默认 "masterduel"。

    Returns:
        True 表示窗口存在且处于最小化状态，False 表示不存在或未最小化。
    """
    found = _find_window_by_title(title_substring)
    if found is None:
        return False
    hwnd, _title = found
    return bool(win32gui.IsIconic(hwnd))


def _get_client_rect_screen(hwnd: int) -> list[int]:
    """获取窗口客户区在屏幕坐标系中的位置和尺寸。

    与 GetWindowRect（返回窗口外框）不同，此函数使用 GetClientRect
    获取游戏渲染区域，再用 ClientToScreen 转换为屏幕绝对坐标。
    截图时只截取客户区 = 游戏实际画面，不含标题栏和窗口边框。

    Args:
        hwnd: 目标窗口句柄。

    Returns:
        [left, top, width, height] — 客户区屏幕坐标和尺寸（像素）。
    """
    # GetClientRect 返回客户区相对于窗口自身的坐标 (0, 0, w, h)
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    # 将客户区左上角 (0,0) 转换为屏幕绝对坐标
    screen_pt = win32gui.ClientToScreen(hwnd, (left, top))
    return [screen_pt[0], screen_pt[1], right - left, bottom - top]


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def capture_window(title_substring: str = "masterduel") -> np.ndarray:
    """根据窗口标题关键词截取指定窗口的画面。

    典型用法::

        from capture import capture_window

        # 截取 Master Duel 游戏窗口
        img = capture_window("masterduel")

        # 截取其他程序窗口
        img = capture_window("记事本")

    内部流程:
        1. 枚举所有顶层窗口，匹配标题
        2. 获取窗口屏幕坐标
        3. 调用 capture_screen() 对该区域截图

    Args:
        title_substring: 窗口标题关键词，大小写不敏感。默认 "masterduel"。

    Returns:
        BGR 格式的 numpy 数组 (H, W, 3)，dtype=uint8，可直接用于 OpenCV。

    Raises:
        RuntimeError: 未找到标题包含指定关键词的可见窗口。
    """
    result = _find_window_by_title(title_substring)
    if result is None:
        raise RuntimeError(f"未找到标题包含 '{title_substring}' 的可见窗口")
    hwnd, title = result
    # 截取客户区（游戏渲染画面），不含标题栏和窗口边框
    region = _get_client_rect_screen(hwnd)
    return capture_screen(region=region)


def capture_screen(monitor_index: int = 0, region: list[int] | None = None) -> np.ndarray:
    """截取指定显示器（或任意区域）的屏幕画面。

    典型用法::

        from capture import capture_screen

        # 截取整个主显示器
        img = capture_screen()

        # 截取副显示器（如果有）
        img = capture_screen(monitor_index=2)

        # 截取屏幕左上角 640x480 区域
        img = capture_screen(region=[0, 0, 640, 480])

    mss 显示器索引约定:
        - monitors[0] = 虚拟桌面（所有显示器拼接），通常不用于截图
        - monitors[1] = 主显示器
        - monitors[2+] = 扩展显示器（按 Windows 显示设置中的顺序）

    Args:
        monitor_index:
            显示器编号。传入 0 或 1 均截取主显示器。
            如果编号超出实际显示器数量，自动回退到 0（主显示器）。

        region:
            截取区域 [left, top, width, height]，以屏幕坐标为基准（像素）。
            传入 None 或空列表时截取整个显示器。
            常用于：
            - 仅截取游戏窗口区域，减少像素处理量
            - 截取屏幕特定部分进行 OCR / 模板匹配

    Returns:
        BGR 格式的 numpy 数组，shape=(H, W, 3)，dtype=uint8。

    Raises:
        mss.ScreenShotError: 无法访问显示器时抛出（通常因权限不足，
            以管理员权限运行或检查杀毒软件是否拦截了 DirectX 调用）。

    Performance:
        - 全屏 1920x1080: ~5-15ms（取决于 GPU / 显示驱动）
        - 区域截图与区域像素数成正比，通常比全屏更快
        - 每次调用创建并销毁 mss 实例（上下文管理器），避免资源泄漏
    """
    with mss.MSS() as sct:
        # mss.monitors 由 mss 在 __init__ 中通过 Win32 EnumDisplayMonitors API
        # 获取，返回列表，每项为 {"left","top","width","height"} 字典
        monitors: list[dict] = sct.monitors

        # 索引越界保护：如果用户传入的 monitor_index 超出范围，回退到 0
        if monitor_index >= len(monitors):
            monitor_index = 0

        if region and len(region) == 4:
            # 自定义截取区域模式
            # 构造与 mss monitor 字典一致的格式
            x, y, w, h = region
            monitor: dict = {"left": x, "top": y, "width": w, "height": h}
        else:
            # 整显示器模式：直接使用 mss 枚举的显示器信息
            monitor = monitors[monitor_index]

        # mss.grab() 是核心截图操作：
        #   - Windows: 调用 IDXGIOutputDuplication::AcquireNextFrame (DirectX)
        #   - macOS:   调用 CGDisplayCreateImage (CoreGraphics)
        # 返回 mss.ScreenShot 对象，底层是 BGRA 格式的像素缓冲区
        img = sct.grab(monitor)

        # 格式转换：BGRA → BGR
        #   BGRA: Blue(0), Green(1), Red(2), Alpha(3) — 每像素 4 字节
        #   BGR:  Blue(0), Green(1), Red(2)           — 每像素 3 字节
        #   [:, :, :3] 即取前 3 个通道，丢弃 Alpha（透明度对截图无意义）
        arr: np.ndarray = np.array(img)[:, :, :3]
        return arr
