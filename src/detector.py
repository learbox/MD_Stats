"""图像识别模块 — 使用 OpenCV 模板匹配检测游戏画面中的 UI 元素。

================================================================================
模板匹配原理
================================================================================

本模块使用 OpenCV 的 matchTemplate 函数，配合归一化相关系数方法
(TM_CCOEFF_NORMED)，在截图中搜索预定义的模板图片。

算法流程:
    1. 加载模板图片（从 resource/templates/ 目录）
    2. 在截图上滑动模板，计算每个位置的匹配度 (0.0 ~ 1.0)
    3. 找到匹配度最高的位置
    4. 如果最高匹配度 >= 阈值，判定为"匹配成功"

TM_CCOEFF_NORMED 的优势:
    - 对整体亮度变化不敏感（归一化处理）
    - 返回值范围固定 [0, 1]，易于设定阈值
    - 1.0 表示完美匹配，0.0 表示完全不相关

================================================================================
识别流程（三阶段）
================================================================================

对局过程中按以下顺序依次检测三个阶段：

    阶段 1 — 检测是否赢硬币:
        coin_win.png   → 赢了硬币（玩家选中了先后攻偏好）
        coin_lose.png  → 输了硬币（对手选中了先后攻偏好）

    阶段 2 — 检测先后攻:
        go_first.png   → 玩家先攻
        go_second.png  → 玩家后攻

    阶段 3 — 检测对局胜负:
        victory.png    → 玩家获胜
        defeat.png     → 玩家落败

每个阶段依次进行：前一个阶段未识别到，不会尝试识别后续阶段。
这防止了误将结果界面中的元素识别为硬币/先后攻的问题。

================================================================================
需要的模板图片
================================================================================

放入 resource/templates/ 目录，按游戏渲染分辨率组织：

    resource/templates/
    ├── 1920x1080/         ← 1080p 全屏 / 窗口模式下的模板
    │   ├── coin_win.png
    │   ├── coin_lose.png
    │   ├── go_first.png
    │   ├── go_second.png
    │   ├── victory.png
    │   └── defeat.png
    ├── 2560x1440/         ← 1440p 分辨率下的模板
    │   └── ...
    └── 3840x2160/         ← 4K 分辨率下的模板
        └── ...

分辨率子目录命名规则: {宽}x{高}，如 1920x1080、2560x1440。
程序会根据 Master Duel 窗口的客户区尺寸自动选择对应子目录。
如果子目录不存在或缺少模板，启动时会在状态栏显示警告。

    模板文件         | 用途            | 对应阶段
    ----------------+-----------------+----------
    coin_win.png    | 赢硬币标识      | 阶段 1
    coin_lose.png   | 输硬币标识      | 阶段 1
    go_first.png    | 先攻标识        | 阶段 2
    go_second.png   | 后攻标识        | 阶段 2
    victory.png     | 胜利标识        | 阶段 3
    defeat.png      | 失败标识        | 阶段 3

模板截取建议:
    - 选择特征明显且不随分辨率等比缩放的 UI 图标
    - 必须在目标分辨率下截取模板（不同分辨率下 UI 像素不同）
    - 模板不要太大（建议 50x50 ~ 200x200 像素），否则匹配耗时增加
    - 支持 PNG / JPG / BMP 三种格式
"""


import cv2
import numpy as np
from src.config import get_project_root

# ---------------------------------------------------------------------------
# 模板图片存放目录
# ---------------------------------------------------------------------------
_TEMPLATES_BASE = get_project_root() / "resource" / "templates"

# 当前分辨率子目录（由 set_resolution 设置），如 1920x1080/。
# 为 None 时只搜索根目录。
_resolution_subdir: str | None = None


def set_resolution(width: int, height: int) -> None:
    """设置当前游戏渲染分辨率，模板加载时使用对应子目录。

    根据传入的客户区宽高，构造子目录名 "{宽}x{高}"，如 "1920x1080"。
    后续 _get_cached_template 只从该子目录加载模板，不会回退到根目录。

    应在启动识别线程前调用一次。宽高通常来自 get_client_size()。

    Args:
        width:  游戏客户区宽度（像素）。
        height: 游戏客户区高度（像素）。
    """
    global _resolution_subdir
    _resolution_subdir = f"{width}x{height}"


_REQUIRED_TEMPLATES = ["coin_win", "coin_lose", "go_first", "go_second", "victory", "defeat"]

# 模板内存缓存：init_templates() 预加载后填充，后续 _get_cached_template 直接取用
# 键为模板名（不含扩展名），值为 numpy 数组或 None（加载失败时）
_template_cache: dict[str, np.ndarray | None] = {}


def _read_template_file(name: str) -> np.ndarray | None:
    """从磁盘加载单个模板文件（不经过缓存）。"""
    if _resolution_subdir is not None:
        search_dir = _TEMPLATES_BASE / _resolution_subdir
    else:
        search_dir = _TEMPLATES_BASE

    for ext in (".png", ".jpg", ".jpeg", ".bmp"):
        path = search_dir / f"{name}{ext}"
        if path.exists():
            img = cv2.imdecode(
                np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if img is not None:
                return img
    return None


def _get_cached_template(name: str) -> np.ndarray | None:
    """从内存缓存取模板（调用前需确保 init_templates 已执行）。"""
    return _template_cache.get(name)


def init_templates() -> str | None:
    """预加载全部模板到内存缓存，并返回缺失报告。

    一次磁盘 IO 完成加载和校验。后续 match_template 的每次调用
    通过 _get_cached_template 直接从缓存取值，不再访问磁盘。

    调用方应在返回非 None 时停止识别流程（模板不完整则无法识别）。

    Returns:
        None 表示全部就绪；否则返回人类可读的警告消息。
    """
    global _template_cache
    missing: list[str] = []

    for name in _REQUIRED_TEMPLATES:
        img = _read_template_file(name)
        _template_cache[name] = img
        if img is None:
            missing.append(f"{name}.png")

    if not missing:
        return None

    search_dir = f"resource/templates/{_resolution_subdir}/" if _resolution_subdir else "resource/templates/"
    count = len(missing)
    if count == len(_REQUIRED_TEMPLATES):
        return f"未找到任何模板 — 缺少目录: {search_dir}"
    else:
        return f"缺少 {count} 个模板: {', '.join(missing)}（路径: {search_dir}）"


def match_template(
    screenshot: np.ndarray, template_name: str, threshold: float = 0.8
) -> tuple[bool, float]:
    """在截图中搜索模板，判断是否匹配成功。

    这是本模块的核心函数，所有具体的识别（硬币、结果）都通过它实现。

    Args:
        screenshot:
            待搜索的截图，BGR 格式 numpy 数组，shape=(H, W, 3)。

        template_name:
            模板的名称（不含扩展名），对应 resource/templates/ 下的文件。
            例如 "coin_first" 对应 coin_first.png。

        threshold:
            匹配置信度阈值，范围 [0.0, 1.0]。
            匹配度 >= 阈值时返回 True。
            阈值越高，误识别越少但可能漏识别；
            阈值越低，越不容易漏识别但可能误识别。

    Returns:
        (是否匹配成功: bool, 最高匹配度: float)

    边界情况处理:
        1. 模板文件不存在 → 返回 (False, 0.0)
        2. 截图尺寸小于模板尺寸 → 返回 (False, 0.0)，因为无法进行模板匹配
           （OpenCV 要求被搜索图像 >= 模板图像）
    """
    # 1. 加载模板
    template = _get_cached_template(template_name)
    if template is None:
        return False, 0.0

    # 2. 尺寸检查：截图必须不小于模板
    #    OpenCV matchTemplate 要求: W_screenshot >= W_template 且 H_screenshot >= H_template
    if screenshot.shape[0] < template.shape[0] or screenshot.shape[1] < template.shape[1]:
        return False, 0.0

    # 3. 执行模板匹配
    #    TM_CCOEFF_NORMED: 归一化相关系数匹配法
    #    返回值是一个矩阵，每个元素 (i,j) 表示模板左上角放在截图 (i,j) 时的匹配度
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)

    # 4. 获取整个结果矩阵中的最大值（即最佳匹配位置的匹配度）
    #    minMaxLoc 返回 (minVal, maxVal, minLoc, maxLoc)
    #    我们只关心 maxVal（最高匹配度），位置信息不需要
    _, max_val, _, _ = cv2.minMaxLoc(result)

    # 5. 与阈值比较
    return max_val >= threshold, float(max_val)


def detect_coin_win(screenshot: np.ndarray, threshold: float = 0.8) -> str | None:
    """阶段 1 — 检测是否赢了硬币。

    在对局开始时，Master Duel 会通过"抛硬币"决定哪一方选择先后攻偏好。
    游戏画面中会显示硬币结果：赢硬币（玩家选中了偏好）或输硬币（对手选中了偏好）。
    本函数通过匹配 coin_win 和 coin_lose 模板来判断结果。

    Args:
        screenshot: 游戏截图（BGR 格式）。
        threshold: 匹配置信度阈值。

    Returns:
        'win'   — 赢了硬币
        'lose'  — 输了硬币
        None    — 未识别到（画面中不包含硬币结果 UI）

    注意事项:
        - 两个模板都会被尝试匹配，返回第一个匹配成功的（coin_win 优先）。
        - 如果两个都匹配成功，说明模板定义有问题（特征重叠），需检查模板。
        - 如果两个都没匹配到，说明当前画面不是硬币结果画面。
    """
    for key in ("coin_win", "coin_lose"):
        matched, _conf = match_template(screenshot, key, threshold)
        if matched:
            return "win" if key == "coin_win" else "lose"
    return None


def detect_turn(screenshot: np.ndarray, threshold: float = 0.8) -> str | None:
    """阶段 2 — 检测先后攻。

    硬币结果确定后，游戏会显示"先攻"或"后攻"的 UI 标识。
    注意：赢了硬币不代表一定先攻（玩家可能主动选择后攻），
    因此必须独立检测此阶段。

    本函数通过匹配 go_first 和 go_second 模板来判断结果。

    Args:
        screenshot: 游戏截图（BGR 格式）。
        threshold: 匹配置信度阈值。

    Returns:
        'first'  — 玩家先攻
        'second' — 玩家后攻
        None     — 未识别到（画面中不包含先后攻 UI）

    注意事项:
        - go_first 优先匹配，两个都命中时返回 'first'。
        - Master Duel 中先后攻的 UI 通常会持续显示几秒，足够检测到。
    """
    for key in ("go_first", "go_second"):
        matched, _conf = match_template(screenshot, key, threshold)
        if matched:
            return "first" if key == "go_first" else "second"
    return None


def detect_result(screenshot: np.ndarray, threshold: float = 0.8) -> str | None:
    """阶段 3 — 检测对局结果（胜利或失败）。

    对局结束后，Master Duel 会显示胜利或失败的界面。
    本函数通过匹配 victory 和 defeat 模板来判断结果。

    Args:
        screenshot: 游戏截图（BGR 格式）。
        threshold: 匹配置信度阈值。

    Returns:
        'win'   — 对局胜利
        'lose'  — 对局失败
        None    — 未识别到（画面中不包含对局结果 UI）

    注意事项:
        - 程序目前不支持识别平局结果（Master Duel 中极少出现）。
        - victory 优先匹配，两个都命中时返回 'win'。
    """
    for key in ("victory", "defeat"):
        matched, _conf = match_template(screenshot, key, threshold)
        if matched:
            return "win" if key == "victory" else "lose"
    return None
