"""屏幕截图模块 — 基于 PrintWindow / mss + pywin32 实现高性能窗口/屏幕捕获。

================================================================================
技术选型
================================================================================

窗口捕获（默认，capture_backend="printwindow"）:
    PrintWindow (user32) + PW_RENDERFULLCONTENT — 直接向窗口索取画面：
    - 拿到的是窗口自己的渲染画面（DWM 为每个窗口维护独立画面），
      不受悬浮窗/其他窗口遮挡影响，也不要求游戏处于前台
    - 代价是耗时高于屏幕抓取：实测 1280x720 单帧约 49ms
      （PrintWindow 调用约 44ms + 取像素约 5.5ms）
    - pywin32 未封装 PrintWindow，用 ctypes 直接调 user32

屏幕抓取（兼容模式，capture_backend="mss"）:
    mss (Multiple Screen Shots) — 屏幕像素采集：
    - Windows 上底层是 GDI BitBlt：截图直写 DIB 内存（无需 GetDIBits
      二次拷贝），比 PIL.ImageGrab / PyAutoGUI 的截图路径更高效、CPU 占用更低
    - macOS 上底层调用 CoreGraphics
    - 返回 BGRA 原始像素缓冲区，与 OpenCV 的 BGR 格式高度兼容，无需额外转码
    - 支持多显示器独立截取、任意坐标区域截取
    - 注意：截取的是屏幕上目标区域当前显示的画面，被遮挡会截入遮挡物

pywin32 — 窗口定位与位图操作：
    - win32gui 封装 USER32.dll 的窗口管理 API：窗口查找、属性读取
      （标题、位置、可见性、最小化状态）
    - win32ui 负责创建内存 DC / 位图（窗口捕获路径）

================================================================================
图像格式转换链
================================================================================

窗口捕获（printwindow）:
    PrintWindow 将客户区画入 32bpp 位图 → GetBitmapBits → numpy (H,W,4)
    → 丢弃 Alpha → BGR (H,W,3)
    （实测 GetBitmapBits 为 top-down 行序，与屏幕抓取路径方向一致，无需翻转）

屏幕抓取（mss）:
    win32gui 定位窗口 → GetClientRect 获取渲染区域 → ClientToScreen 转屏幕坐标
    → mss.grab() → BGRA 原始缓冲区 → numpy (H,W,4) → 丢弃 Alpha → BGR (H,W,3)

    注意: 两种方式截取的都是客户区（游戏实际渲染画面），
    不含标题栏和窗口边框。这确保全屏模式和窗口模式下的截图内容一致。
"""


import ctypes.wintypes  # 该写法同时绑定 ctypes 名（下方 WinDLL / wintypes 都会用到）

import numpy as np
import mss
import win32gui
import win32ui

from src import logger as _log


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class CaptureError(RuntimeError):
    """画面获取失败。

    suggest_fallback 标记"换另一种画面来源是否可能有效"：
      - True:  失败发生在来源方式本身（PrintWindow 被拒 / 屏幕抓取异常），
               调用方可提示用户切换画面来源；
      - False: 与来源方式无关（窗口不存在 / 已最小化 / 尺寸异常等），
               换另一种来源同样会失败，不应给出误导性提示。
    """

    def __init__(self, message: str, suggest_fallback: bool = False) -> None:
        super().__init__(message)
        self.suggest_fallback = suggest_fallback


# 截图调用可能抛出的"预期异常"。调用方（识别线程等）按这个元组捕获，
# 而不是笼统的 except Exception——否则真正的程序 bug 会被当成"截图失败"重试，
# 拖很久才暴露（且日志里看不到 traceback）。
#
#   CaptureError    — 本模块主动抛的（窗口关闭 / 已最小化 / 尺寸异常 / PrintWindow 失败）
#   win32ui.error   — pywin32 的 GDI 对象操作失败（如 CreateCompatibleBitmap 分配失败）
#   win32gui.error  — 即 pywintypes.error（实测 `win32gui.error is pywintypes.error`），
#                     覆盖 GetWindowDC / DeleteObject / ReleaseDC 等 Win32 API 失败
#
# 注意：后两者**直接继承 Exception**，既不是 OSError 也不是 RuntimeError（实测确认），
# 所以 `except (OSError, RuntimeError)` 接不住它们。
CAPTURE_ERRORS = (CaptureError, win32ui.error, win32gui.error)


def get_gdi_object_count() -> int:
    """当前进程的 GDI 对象数（诊断用；取不到时返回 -1）。

    抓图失败时把这个数字记进日志，便于区分"偶发单次失败"和"资源接近耗尽"
    （GDI 对象每进程上限 1 万）。
    """
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.wintypes.HANDLE
        k32.GetCurrentProcessId.restype = ctypes.wintypes.DWORD
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.GetGuiResources.restype = ctypes.wintypes.DWORD
        handle = k32.OpenProcess(0x1000, False, k32.GetCurrentProcessId())  # QUERY_LIMITED
        if not handle:
            return -1
        try:
            return int(u32.GetGuiResources(handle, 0))   # 0 = GR_GDIOBJECTS
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return -1


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


def get_window_rect(title_substring: str = "masterduel") -> str | None:
    """获取窗口的屏幕外框坐标（含标题栏和边框）。

    用于 TOML 元数据的 window_rect 字段，帮助排查多显示器 DPI 缩放问题。
    返回格式: "left,top,right,bottom"

    Args:
        title_substring: 窗口标题关键词，默认 "masterduel"。

    Returns:
        "left,top,right,bottom" 字符串或 None（窗口未找到时）。
    """
    found = _find_window_by_title(title_substring)
    if found is None:
        return None
    hwnd, _title = found
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return f"{left},{top},{right},{bottom}"


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
# 窗口捕获（PrintWindow）
# ---------------------------------------------------------------------------
#
# PrintWindow 向窗口请求"把你自己画到这块画布上"。配合 PW_RENDERFULLCONTENT
# 标志（Windows 8.1+），内容来自 DWM 为窗口维护的独立渲染画面 —— 不经过屏幕：
#   - 不受悬浮窗/其他窗口遮挡影响
#   - 不要求窗口处于前台
# 代价是耗时高于屏幕抓取（DWM 画面需要转换成 GDI 可读格式）。
#
# 标志选择（2026-10 实测于 Master Duel）：
#   flag 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT —— 只取客户区，内容完整
#   flag 2 会把标题栏画入画面，导致内容偏移、底部被裁，不可用
#   flag 0（传统 WM_PRINT）游戏不响应，返回白图

# pywin32 没有封装 PrintWindow，用 ctypes 直接调 user32
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.PrintWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC,
                                ctypes.wintypes.UINT]
_user32.PrintWindow.restype = ctypes.wintypes.BOOL

_PW_CLIENTONLY = 0x00000001         # 只绘制客户区
_PW_RENDERFULLCONTENT = 0x00000002  # 包含 DirectComposition 内容（Win8.1+）

# 客户区单边像素上限。位图按 32bpp 分配（8192×8192 ≈ 268MB），再大就可能分配失败，
# 而 pywin32 那时报出的是误导性的 "CreateCompatibleDC failed"（实测确认）。
# 8K 分辨率也才 7680 宽，超过这个数说明 GetClientRect 拿到了异常值。
_MAX_CLIENT_EDGE = 8192


# 各类资源"释放失败"的累计次数与日志限流。
# 某类释放若在特定环境下每帧都失败（截图频率可达 3~10 次/秒），逐次记日志会把
# 日志文件写爆，所以只记「首次 + 每 _RELEASE_LOG_EVERY 次」，计数继续累计。
_release_fail_counts: dict[str, int] = {}
_RELEASE_LOG_EVERY = 100


def _release_gdi(what: str, fn, *args) -> None:
    """释放一个 GDI 资源；失败只写日志，绝不向外抛。

    为什么单独包一层？
        清理发生在 finally 里，此时往往已经有异常在传播（例如位图根本没建成）。
        如果清理本身再抛，会同时造成两件坏事：

            1. 原始异常被顶掉——真正的原因（创建位图失败）再也看不到，
               只剩下 DeleteObject 的报错
            2. finally 里后面的释放语句被跳过 → 一次失败反而漏掉多个 GDI 对象。
               GDI 对象每进程上限 1 万，越失败越漏会加速恶化

    Args:
        what: 资源名称，用于日志定位（如 "删除位图"）。
        fn: 执行释放的可调用对象（如 win32gui.DeleteObject、mem_dc.DeleteDC）。
        *args: 传给 fn 的参数。
    """
    try:
        fn(*args)
    except Exception as e:      # 清理路径必须吞掉所有异常，不能影响主流程
        n = _release_fail_counts.get(what, 0) + 1
        _release_fail_counts[what] = n
        if n == 1 or n % _RELEASE_LOG_EVERY == 0:
            _log.write("ERROR", f"GDI 资源释放失败（{what}，累计 {n} 次）: {e}")


def _capture_window_pw(hwnd: int, w: int, h: int) -> np.ndarray:
    """用 PrintWindow 抓取窗口客户区（默认画面来源）。

    直接向窗口索取它自己的画面，不经过屏幕：
    不受悬浮窗/其他窗口遮挡影响，也不要求窗口处于前台。

    Args:
        hwnd: 目标窗口句柄。
        w: 客户区宽度（像素，与 GetClientRect 读到的尺寸一致）。
        h: 客户区高度（像素）。

    Returns:
        BGR 格式的 numpy 数组 (H, W, 3)，dtype=uint8。

    Raises:
        CaptureError: PrintWindow 调用失败（窗口已关闭、被系统拒绝等），
            带 suggest_fallback=True（换屏幕来源可能有效）。
    """
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mem_dc = None
    bmp = None
    old_bmp = None
    try:
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(src_dc, w, h)
        old_bmp = mem_dc.SelectObject(bmp)

        ok = _user32.PrintWindow(
            hwnd, mem_dc.GetSafeHdc(),
            _PW_CLIENTONLY | _PW_RENDERFULLCONTENT)
        if not ok:
            raise CaptureError("PrintWindow 调用失败（窗口可能已关闭）",
                               suggest_fallback=True)

        # True → 返回 bytes；数据为 32bpp BGRA，行序 bottom-up（Windows 位图惯例）
        bits = bmp.GetBitmapBits(True)
    finally:
        # GDI 资源显式释放（每帧创建/销毁，确保长时间运行不累积 GDI 对象）。
        # 顺序：位图先从 DC 反选 → 删位图 → 删 DC → 释放窗口 DC。
        # 每一步各自兜底（见 _release_gdi）：某一步失败不影响后面几步。
        if mem_dc is not None and old_bmp is not None:
            _release_gdi("反选原位图", mem_dc.SelectObject, old_bmp)
        if bmp is not None:
            # PyCBitmap 没有 DeleteObject 方法（pywin32 312 实测），经 GetHandle 删除。
            # CreateCompatibleBitmap 失败时内部句柄仍是 0（NULL），DeleteObject(0)
            # 会抛 pywintypes.error 并盖掉真正的异常 → 先判空。
            hbitmap = bmp.GetHandle()
            if hbitmap:
                _release_gdi("删除位图", win32gui.DeleteObject, hbitmap)
        if mem_dc is not None:
            _release_gdi("释放内存 DC", mem_dc.DeleteDC)
        # 注意：这里**不**对 src_dc 调 DeleteDC。
        # src_dc 是 GetWindowDC 句柄的包装，而按 Win32 语义，GetDC/GetWindowDC
        # 得到的 DC 必须用 ReleaseDC 释放、不能用 DeleteDC。
        # 真实环境日志（2026-10-17）显示这个调用会偶发抛 "DeleteDC failed"——
        # 在旧的清理代码里，它抛错会顶掉原始异常并跳过后面的 ReleaseDC，
        # 是段位检测线程静默死掉的一条隐藏路径。真正的释放靠下面这句 ReleaseDC。
        _release_gdi("释放窗口 DC", win32gui.ReleaseDC, hwnd, hwnd_dc)

    # 丢弃 Alpha，得到连续 BGR 数组。
    # 注意：GetBitmapBits 实测返回的就是 top-down 行序（CreateCompatibleBitmap
    # 的 DDB 在该路径下按从上到下排列），不要再翻转——翻转会导致画面颠倒。
    arr = np.frombuffer(bits, dtype=np.uint8).reshape(h, w, 4)
    return np.ascontiguousarray(arr[:, :, :3])


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def capture_window(title_substring: str = "masterduel",
                   backend: str = "printwindow") -> np.ndarray:
    """根据窗口标题关键词截取指定窗口的画面。

    典型用法::

        from capture import capture_window

        # 截取 Master Duel 游戏窗口（默认窗口捕获，不受遮挡影响）
        img = capture_window("masterduel")

        # 强制用屏幕抓取（兼容模式，旧行为）
        img = capture_window("masterduel", backend="mss")

    内部流程:
        1. 枚举所有顶层窗口，匹配标题
        2. 窗口最小化 → 直接报错（两种方式都拿不到有效画面）
        3. 按 backend 分发：
           - "printwindow": PrintWindow 直接取窗口画面（默认）
           - "mss":         屏幕抓取客户区所在区域（兼容模式）

    Args:
        title_substring: 窗口标题关键词，大小写不敏感。默认 "masterduel"。
        backend: 画面来源，"printwindow"（默认）或 "mss"；其他值按默认处理。

    Returns:
        BGR 格式的 numpy 数组 (H, W, 3)，dtype=uint8，可直接用于 OpenCV。

    Raises:
        CaptureError（RuntimeError 子类）: 未找到窗口 / 窗口已最小化 /
            画面来源抓取失败。异常的 suggest_fallback 属性标记换一种
            画面来源是否可能有效（调用方据此决定是否提示切换）。
    """
    result = _find_window_by_title(title_substring)
    if result is None:
        raise CaptureError(f"未找到标题包含 '{title_substring}' 的可见窗口")
    hwnd, title = result

    # 最小化时窗口停止渲染：屏幕抓取会截到任务栏缩略图位置的错误内容，
    # 窗口捕获只能拿到旧帧 —— 两种方式都没有有效画面，直接报错跳过
    # （与来源方式无关 → 不标记 suggest_fallback）
    if win32gui.IsIconic(hwnd):
        raise CaptureError(f"窗口 '{title}' 已最小化，无法截图")

    if backend == "mss":
        # 屏幕抓取（兼容模式）：截取客户区所在的屏幕区域
        region = _get_client_rect_screen(hwnd)
        try:
            return capture_screen(region=region)
        except Exception as e:
            # mss 自身的抓取失败（ScreenShotError 等）→ 换来源可能有效
            raise CaptureError(str(e), suggest_fallback=True) from e

    # 窗口捕获（默认）：直接用 PrintWindow 取窗口客户区画面
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        raise CaptureError("窗口客户区尺寸无效")
    # 上限保护：窗口处于异常状态（正在切换分辨率/全屏、窗口重建等）时
    # GetClientRect 可能返回离谱的尺寸，拿去分配位图会失败并报出误导性的
    # "CreateCompatibleDC failed"。这里提前挡掉，并给出可读的原因。
    if w > _MAX_CLIENT_EDGE or h > _MAX_CLIENT_EDGE:
        raise CaptureError(f"窗口客户区尺寸异常（{w}×{h}），已跳过本帧")
    try:
        return _capture_window_pw(hwnd, w, h)
    except CAPTURE_ERRORS as e:
        # 把诊断信息（客户区尺寸 / 当前 GDI 对象数）挂到异常上，调用方记日志时
        # 一并输出——失败原因不明的偶发故障，靠这两项才能区分"尺寸异常 / 资源耗尽"。
        # 挂属性失败（异常对象不允许时）忽略，不能因此改变原有异常。
        try:
            e.capture_context = f"客户区 {w}×{h}｜GDI 对象 {get_gdi_object_count()}"
        except Exception:
            pass
        raise


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
            以管理员权限运行或检查杀毒软件是否拦截了 GDI 抓屏调用）。

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
        #   - Windows: BitBlt 从屏幕 DC 抓取（GDI），直写 DIB 内存
        #   - macOS:   调用 CGDisplayCreateImage (CoreGraphics)
        # 返回 mss.ScreenShot 对象，底层是 BGRA 格式的像素缓冲区
        img = sct.grab(monitor)

        # 格式转换：BGRA → BGR
        #   BGRA: Blue(0), Green(1), Red(2), Alpha(3) — 每像素 4 字节
        #   BGR:  Blue(0), Green(1), Red(2)           — 每像素 3 字节
        #   用 asarray 零拷贝包装 mss 缓冲，[:, :, :3] 切片得到视图——
        #   相比 np.array 省一次全量拷贝（1600x900 实测约 1.9ms/帧）。
        #   注意：结果是"每像素步长 4 字节"的非连续视图，cv2 匹配/编码
        #   链路已实测兼容（需要连续内存处有 C_CONTIGUOUS 防护）。
        arr: np.ndarray = np.asarray(img)[:, :, :3]
        return arr
