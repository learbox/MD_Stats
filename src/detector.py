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


_REQUIRED_TEMPLATES = ["coin_win", "coin_lose", "go_first", "go_second", "victory", "defeat", "rank_up", "rank_down"]

# 最近一次检测的最高匹配分数（供状态栏显示，0.0 = 无检测）
_last_match_score: float = 0.0

# 可选模板：缺失时不阻止检测启动，detect_rank() 会自动返回 None
_OPTIONAL_TEMPLATES = {"rank_up", "rank_down"}

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
    missing_opt: list[str] = []

    for name in _REQUIRED_TEMPLATES:
        img = _read_template_file(name)
        _template_cache[name] = img
        if img is None:
            if name in _OPTIONAL_TEMPLATES:
                missing_opt.append(f"{name}.png")   # 可选模板缺失不影响启动
            else:
                missing.append(f"{name}.png")       # 必选模板缺失是严重问题

    search_dir = f"resource/templates/{_resolution_subdir}/" if _resolution_subdir else "resource/templates/"

    # 必选模板缺失 → 返回警告，阻止检测
    if missing:
        if len(missing) == len(_REQUIRED_TEMPLATES) - len(_OPTIONAL_TEMPLATES):
            # 所有必选模板都缺失 = 模板目录可能不存在
            return f"未找到任何模板 — 缺少目录: {search_dir}"
        else:
            return f"缺少 {len(missing)} 个模板: {', '.join(missing)}（路径: {search_dir}）"

    # 仅可选模板缺失 → 不阻止检测，但告知用户
    if missing_opt:
        return f"缺少段位检测模板: {', '.join(missing_opt)}（已跳过，视为普通局）"

    return None


def match_template(
    screenshot: np.ndarray, template_name: str
) -> float:
    """在截图中搜索模板，返回最高匹配度。

    这是本模块的核心函数，所有具体的识别（硬币、结果）都通过它实现。
    阈值比较由调用方完成（取所有模板中的最高分后与 threshold 比较）。

    Args:
        screenshot:
            待搜索的截图，BGR 格式 numpy 数组，shape=(H, W, 3)。

        template_name:
            模板的名称（不含扩展名），对应 resource/templates/ 下的文件。
            例如 "coin_win" 对应 coin_win.png。

    Returns:
        最高匹配度 (0.0 ~ 1.0)，模板不存在或尺寸不匹配时返回 0.0
    """
    # 0. 防御：截图可能因窗口消失等原因返回 None
    if screenshot is None:
        return 0.0

    # 1. 加载模板
    template = _get_cached_template(template_name)
    if template is None:
        return 0.0

    # 2. 尺寸检查：截图必须不小于模板
    #    OpenCV matchTemplate 要求: W_screenshot >= W_template 且 H_screenshot >= H_template
    if screenshot.shape[0] < template.shape[0] or screenshot.shape[1] < template.shape[1]:
        return 0.0

    # 3. 执行模板匹配
    #    TM_CCOEFF_NORMED: 归一化相关系数匹配法
    #    返回值是一个矩阵，每个元素 (i,j) 表示模板左上角放在截图 (i,j) 时的匹配度
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)

    # 4. 获取整个结果矩阵中的最大值（即最佳匹配位置的匹配度）
    #    minMaxLoc 返回 (minVal, maxVal, minLoc, maxLoc)
    #    我们只关心 maxVal（最高匹配度），位置信息不需要
    _, max_val, _, _ = cv2.minMaxLoc(result)

    # 5. 返回原始分数（由调用方比较所有模板后决定结果）
    return float(max_val)


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
    best_key, best_score = "", 0.0
    for key in ("coin_win", "coin_lose"):
        score = match_template(screenshot, key)
        if score > best_score:
            best_score, best_key = score, key
    global _last_match_score
    _last_match_score = best_score
    if best_score >= threshold:
        return "win" if best_key == "coin_win" else "lose"
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
    best_key, best_score = "", 0.0
    for key in ("go_first", "go_second"):
        score = match_template(screenshot, key)
        if score > best_score:
            best_score, best_key = score, key
    global _last_match_score
    _last_match_score = best_score
    if best_score >= threshold:
        return "first" if best_key == "go_first" else "second"
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
    best_key, best_score = "", 0.0
    for key in ("victory", "defeat"):
        score = match_template(screenshot, key)
        if score > best_score:
            best_score, best_key = score, key
    global _last_match_score
    _last_match_score = best_score
    if best_score >= threshold:
        return "win" if best_key == "victory" else "lose"
    return None


def detect_rank(screenshot: np.ndarray, threshold: float = 0.8) -> str | None:
    """阶段 1 附 — 检测是否为升段局或降段局。

    在硬币结果画面的同一张截图上执行。Master Duel 在段位升降时
    会在硬币画面中额外显示升段/降段标识——与硬币结果同时出现、
    同时消失，是同一帧画面的一部分，因此复用 detect_coin_win
    的截图，无需额外截图或新增状态机阶段。

    模板（rank_up.png / rank_down.png）缺失时，match_template
    返回 (False, 0.0)，最终返回 None，视为普通局。

    注意：本函数是"附带"检测——返回值仅用于记录段位升降信息，
    不影响硬币/先后攻/胜负的主流程。误判或漏判都不会阻塞状态机。

    Args:
        screenshot: 游戏截图（BGR 格式），与 detect_coin_win 使用同一张。
        threshold: 匹配置信度阈值。

    Returns:
        'up'    — 升段局
        'down'  — 降段局
        None    — 未识别到（普通局，或模板缺失）
    """
    best_key, best_score = "", 0.0
    for key in ("rank_up", "rank_down"):
        score = match_template(screenshot, key)
        if score > best_score:
            best_score, best_key = score, key
    global _last_match_score
    _last_match_score = best_score
    if best_score >= threshold:
        return "up" if best_key == "rank_up" else "down"
    return None


def get_last_score() -> float:
    """最近一次 detect_* 调用的最高匹配分数（0.0 = 无结果）。"""
    return _last_match_score


# =============================================================================
# 段位图标检测（源素材 + 背景色合成 + NCC 匹配）
#
# 总体思路:
#   游戏中的段位图标是 RGBA 源素材叠加在复杂背景上的。如果直接用源素材
#   做模板匹配，背景差异会导致匹配分数极低。因此我们:
#     1. 从截图中采样实际背景色
#     2. 把源素材的 RGBA 合成到该背景色上 → 生成"模拟模板"
#     3. 用模拟模板做 NCC（归一化相关系数）匹配
#   这样模板的背景和截图背景一致，匹配分数大幅提高。
#
# 位置缓存:
#   首次检测需要缩略图粗搜 → 原图精搜的完整流程（较慢）。
#   一旦确定位置，就把 (分辨率, 侧, x, y, 尺寸) 存入 rank_positions.toml。
#   后续检测直接在该位置附近精搜（极快）。
#
# 等级数字识别:
#   段位图标下方有 I~V 的罗马数字（巅峰没有）。通过列投影峰值计数
#   + 峰宽分析识别：I=1窄峰, V=1宽峰(平顶山), II=2等宽窄峰,
#   IV=2峰(宽窄比>1.8), III=3窄峰。
# =============================================================================

_RANK_ICONS_DIR = get_project_root() / "resource" / "templates" / "rankicons"

# 段位图标名 → 显示标签映射，在 _init_rank_icons() 中填充
_RANK_LABELS: dict[str, str] = {}

# 源素材缓存：{文件名: (BGR通道, Alpha通道)}
# 源素材是 290×290 的 RGBA PNG，加载后拆分成颜色和透明度分别缓存
_rank_icon_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}

# 没有等级数字的段位（不触发 _detect_tier_number）
_NO_TIER_RANKS = {"巅峰"}

# 预合成模板缓存：{(图标名, 尺寸(px), 背景B, 背景G, 背景R): BGR模板}
# 避免每次检测都重新合成模板（合成涉及 resize + alpha 混合，较慢）
_composite_cache: dict[tuple, np.ndarray] = {}

# 段位图标位置缓存：{(分辨率宽, 分辨率高, "player"/"opponent"): (x, y, 尺寸)}
_position_cache: dict[tuple, tuple] = {}
_POSITION_CACHE_FILE = get_project_root() / "resource" / "templates" / "rank_positions.toml"


def _load_position_cache() -> None:
    """从 rank_positions.toml 加载段位图标在屏幕上的位置缓存。

    文件格式:
        [player]
        1920x1080 = [560, 420, 55]   # x, y, 图标尺寸(px)
        2560x1440 = [750, 560, 73]
        [opponent]
        ...

    缓存 key 为 (宽, 高, "player"/"opponent")，value 为 (x, y, size)。
    如果有缓存，后续检测直接在 (x,y) 附近小范围精搜，跳过缩略图粗搜。
    """
    global _position_cache
    if _position_cache:
        return  # 已经加载过，避免重复读文件
    try:
        import tomllib
        with open(_POSITION_CACHE_FILE, "rb") as f:
            data = tomllib.load(f)
        for side in ("player", "opponent"):
            section = data.get(side, {})
            for res, vals in section.items():
                if isinstance(vals, list) and len(vals) == 3:
                    w, h = res.split("x")  # "1920x1080" → 1920, 1080
                    _position_cache[(int(w), int(h), side)] = (
                        int(vals[0]), int(vals[1]), int(vals[2]))
    except (FileNotFoundError, KeyError, ValueError):
        pass  # 文件不存在或格式损坏 → 首次检测，走粗搜流程


def _save_position_cache() -> None:
    """将内存中的段位图标位置缓存持久化到 rank_positions.toml。

    只在首次检测成功后调用一次，后续检测直接读取缓存文件。
    按 side 分组，每组按分辨率排序，方便人工查看和调试。
    """
    lines = ["# 段位图标位置缓存（自动生成，首次检测后写入）",
             "# 格式: {分辨率} = [x, y, 尺寸]", ""]
    for side in ("player", "opponent"):
        lines.append(f"[{side}]")
        # 按分辨率排序，方便人工查看
        for (w, h, s), (x, y, sz) in sorted(_position_cache.items()):
            if s == side:
                lines.append(f"{w}x{h} = [{x}, {y}, {sz}]")
        lines.append("")
    try:
        _POSITION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _POSITION_CACHE_FILE.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass  # 写文件失败不影响程序运行（下次启动重新检测即可）


def _init_rank_icons() -> None:
    """预加载全部段位图标源素材（RGBA PNG）到内存缓存。

    段位图标存储在 resource/templates/rankicons/ 下：
        img_rankicon_01_l.png → 新手
        img_rankicon_02_l.png → 青铜
        ...
        img_rateicon_01_l.png → 巅峰

    每张图是 290×290 的 RGBA PNG。加载后拆分成：
        - BGR 通道（[:, :, :3]）：颜色信息
        - Alpha 通道（[:, :, 3]）：透明度遮罩

    用 np.fromfile + cv2.imdecode 而非 cv2.imread，避免中文路径问题。
    """
    global _RANK_LABELS, _rank_icon_cache
    if _rank_icon_cache:
        return  # 已经加载过，避免重复加载

    # 文件名 → 中文段位名
    _RANK_LABELS = {
        "img_rankicon_01": "新手", "img_rankicon_02": "青铜",
        "img_rankicon_03": "白银", "img_rankicon_04": "黄金",
        "img_rankicon_05": "铂金", "img_rankicon_06": "钻石",
        "img_rankicon_07": "大师", "img_rateicon_01": "巅峰",
    }

    for name in _RANK_LABELS:
        path = _RANK_ICONS_DIR / f"{name}_l.png"
        if path.exists():
            # fromfile 读原始字节 → imdecode 解码（支持中文路径）
            raw = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)  # 保留 RGBA
            if img is not None and img.shape[2] == 4:  # 确保是 RGBA 图
                _rank_icon_cache[name] = (img[:, :, :3], img[:, :, 3])


def _sample_bg(screenshot: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """从截图的指定矩形区域采样平均背景色，用于 RGBA 源素材合成。

    为什么需要采样背景色？
        游戏段位图标是半透明叠加在背景上的。如果直接用源素材 PNG 做模板
        匹配，PNG 的透明部分和截图的实际背景颜色不一致，NCC 匹配分数会
        极低。正确做法：把源素材 RGBA 合成到与实际背景相同的颜色上，
        生成的"模拟模板"和截图中的段位图标外观一致。

    采样位置 (w//2-80, 10, 160, 30) 是顶栏空白区域，通常没有 UI 元素。

    Returns:
        shape=(3,) 的 float32 数组，BGR 三通道平均值。失败时返回灰色。
    """
    region = screenshot[max(0, y):y + h, max(0, x):x + w]
    if region.size == 0:
        return np.array([128, 128, 128], dtype=np.float32)  # 灰色兜底
    # 把所有像素 reshape 成 (N, 3)，沿列求均值 → BGR 三通道平均值
    return region.reshape(-1, 3).mean(axis=0).astype(np.float32)


def _composite_rank_icon(name: str, size: int, bg_color: np.ndarray) -> np.ndarray | None:
    """将 RGBA 源素材缩放到目标尺寸，然后 Alpha 混合到背景色上，返回 BGR 模板。

    这是段位检测的核心合成步骤。分三步：
        1. 缩放 — 把 290×290 的源素材缩放到目标尺寸
        2. Alpha 混合 — 把 RGBA 叠加到背景色上
           结果像素 = 前景RGB × alpha + 背景RGB × (1 - alpha)
        3. 缓存 — 同一尺寸+同一背景色的模板下次直接用

    Args:
        name: 图标名，如 "img_rankicon_04"（黄金）
        size: 目标尺寸（px），图标缩放到 size×size
        bg_color: 背景色 BGR 三通道，shape=(3,)，float32

    Returns:
        size×size 的 BGR 模板，uint8。源素材不存在时返回 None。
    """
    global _composite_cache
    # 缓存 key：图标名 + 尺寸 + 背景色（取整后 BGR 元组）
    bg_key = (int(bg_color[0]), int(bg_color[1]), int(bg_color[2]))
    cache_key = (name, size, bg_key)
    if cache_key in _composite_cache:
        return _composite_cache[cache_key]

    entry = _rank_icon_cache.get(name)
    if entry is None:
        return None
    bgr, alpha = entry  # 解包 BGR 通道和 Alpha 通道

    # 1. 缩放到目标尺寸
    scaled_bgr = cv2.resize(bgr, (size, size))
    scaled_alpha = cv2.resize(alpha, (size, size))

    # 2. Alpha 混合：result = foreground × alpha + background × (1 - alpha)
    #    alpha 转为 0.0~1.0 的浮点数
    alpha_f = scaled_alpha.astype(np.float32) / 255.0
    bg = np.full((size, size, 3), bg_color, dtype=np.float32)  # 纯色背景
    composite = (scaled_bgr.astype(np.float32) * alpha_f[:, :, None]
                 + bg * (1 - alpha_f[:, :, None])).astype(np.uint8)

    _composite_cache[cache_key] = composite
    return composite


def _detect_rank_in_roi(
    screenshot: np.ndarray, roi_x: int, roi_y: int, roi_w: int, roi_h: int,
    bg_color: np.ndarray, threshold: float = 0.7,
) -> tuple[str | None, float, int, int, int]:
    """在截图的指定 ROI（感兴趣区域）内搜索最佳段位图标。

    采用"粗搜 + 精搜"两阶段策略：
        粗搜（第一遍）：步长 12px，快速扫描所有尺寸 × 所有图标类型
        精搜（第二遍）：如果粗搜有高分候选，在最佳尺寸 ±10px 范围内
                       以步长 2px 精细搜索

    为什么要粗搜+精搜？
        段位图标的实际尺寸取决于分辨率和 UI 缩放，不能预设一个值。
        遍历所有可能尺寸（20~150px）如果用步长 2px 会非常慢（65 次 × 8 图标
        × ROI 匹配 ≈ 520 次模板匹配，每次都要 NCC 卷积）。
        先用大步长 12px 快速定位大概尺寸，再用小步长 2px 精调，速度快 6 倍。

    Args:
        screenshot: 完整截图（BGR）
        roi_x, roi_y, roi_w, roi_h: ROI 区域
        bg_color: 采样背景色
        threshold: 匹配置信度阈值

    Returns:
        (图标名 | None, 最高分数, best_x, best_y, best_尺寸)
    """
    _init_rank_icons()  # 确保图标已加载

    roi = screenshot[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]

    # 尺寸搜索范围：最小 20px 或 屏幕宽/25，最大 屏幕宽/5
    img_w = screenshot.shape[1]
    min_sz = max(20, img_w // 25)
    max_sz = min(img_w // 5, roi_h, roi_w // 2)

    best_name, best_score = None, 0.0
    best_x, best_y, best_sz = 0, 0, 0

    for name in _RANK_LABELS:
        # ---- 第一遍：粗搜（步长 12px） ----
        for sz in range(min_sz, max_sz, 12):
            tmpl = _composite_rank_icon(name, sz, bg_color)
            # 模板比 ROI 大 → 跳过
            if tmpl is None or tmpl.shape[0] > roi.shape[0] or tmpl.shape[1] > roi.shape[1]:
                continue
            # TM_CCOEFF_NORMED：归一化互相关系数，对亮度变化不敏感
            result = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(result)
            if val > best_score:
                best_score, best_name = val, name
                best_x, best_y = roi_x + loc[0], roi_y + loc[1]
                best_sz = sz

        # ---- 第二遍：精搜（步长 2px，范围 best_sz±10） ----
        # 只有粗搜分数 > 0.5 才精搜（省计算）
        if best_name == name and best_score > 0.5:
            fine_start = max(min_sz, best_sz - 10)
            fine_end = min(max_sz, best_sz + 12)
            for sz in range(fine_start, fine_end, 2):
                tmpl = _composite_rank_icon(name, sz, bg_color)
                if tmpl is None or tmpl.shape[0] > roi.shape[0] or tmpl.shape[1] > roi.shape[1]:
                    continue
                result = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
                _, val, _, loc = cv2.minMaxLoc(result)
                if val > best_score:
                    best_score, best_name = val, name
                    best_x, best_y = roi_x + loc[0], roi_y + loc[1]
                    best_sz = sz

    if best_score < threshold or best_name is None:
        return None, best_score, 0, 0, 0  # 分数不够 → 视为未检测到
    return best_name, best_score, best_x, best_y, best_sz


def _detect_tier_number(
    screenshot: np.ndarray, rank_x: int, rank_y: int, rank_w: int,
    threshold: float = 0.7,
) -> tuple[int | None, float]:
    """识别段位图标下方的罗马数字等级（I~V）。

    段位图标右下角有一个小数字（I、II、III、IV、V），表示段位内的等级。
    巅峰没有数字等级（_NO_TIER_RANKS 处理）。

    算法：列投影峰值计数
        1. 从段位图标的相对位置裁出数字区域
           （位于图标右下角，约占图标 22%×11.5% 面积）
        2. 转灰度 + OTSU 二值化（数字白、背景黑）
        3. 反相后每列求和 → 得到"列投影"一维数组
        4. 数峰值个数 + 量每个峰的宽度 → 按峰数+峰宽判定

        实测结论（游戏实际字体，1600×900）：
          I   = 1 个窄峰（竖线占字符区 10~20%）
          V   = 1 个宽峰（两斜线在列投影中融合为平顶山，占 25~50%）
          II  = 2 个等宽窄峰（两根分离竖线）
          IV  = 2 个峰：窄峰(I) + 宽峰(V形)，宽窄比 > 1.8
          III = 3 个窄峰

    Args:
        screenshot: 原始分辨率截图
        rank_x, rank_y: 段位图标左上角坐标
        rank_w: 段位图标尺寸（宽=高）
        threshold: 等级置信度阈值，低于此值返回 None（默认 0.7）

    Returns:
        (数字 1-5 | None, 置信度)。置信度 < threshold 时数字为 None。
    """
    h, w = screenshot.shape[:2]

    # 数字区域相对于段位图标的位置（经验值，基于多分辨率测试）
    tx = int(rank_x + 0.39 * rank_w)  # 数字区域左上 x
    ty = int(rank_y + 0.81 * rank_w)  # 数字区域左上 y
    tw = int(0.22 * rank_w)           # 数字区域宽度
    th = int(0.115 * rank_w)          # 数字区域高度

    # 边界检查：数字区域不能超出截图
    if tx < 0 or ty < 0 or tx + tw > w or ty + th > h or tw <= 0 or th <= 0:
        return None, 0.0

    # 转灰度
    gray = cv2.cvtColor(
        screenshot[ty:ty + th, tx:tx + tw], cv2.COLOR_BGR2GRAY
    )

    # OTSU 自动阈值二值化（数字=白 255，背景=黑 0）
    _, bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    # 反相后列投影：每列的"黑像素"总数（数字笔画越密集，投影值越高）
    proj = (255 - bin_img).sum(axis=0)

    # ---- 数峰值 ----
    # 峰值定义：投影值超过最大值的 35% 算一个隆起
    peak_th = proj.max() * 0.35
    in_peak = False
    n_peaks = 0
    for v in proj:
        if v > peak_th and not in_peak:
            in_peak = True
            n_peaks += 1
        elif v <= peak_th * 0.5:  # 跌到阈值 50% 以下才算"离开峰"
            in_peak = False

    if n_peaks <= 0:
        return None, 0.0

    # ---- 峰宽计算（所有分支共用） ----
    def _measure_peaks(proj: np.ndarray, peak_th: float) -> list[int]:
        """量出投影中每个峰的宽度（列数），返回宽度列表。"""
        widths = []
        in_peak = False
        w_start = 0
        for i, v in enumerate(proj):
            if v > peak_th and not in_peak:
                in_peak = True
                w_start = i
            elif v <= peak_th * 0.5 and in_peak:
                in_peak = False
                widths.append(i - w_start)
        if in_peak:  # 峰在数组末尾没闭合
            widths.append(len(proj) - w_start)
        return widths

    total_w = len(proj)  # 字符区总宽度（列数）

    # 峰谷比（峰值/谷值），衡量信号清晰度，模糊图像峰谷差距小
    peak_values = sorted([v for v in proj if v > peak_th], reverse=True)
    valley_values = sorted([v for v in proj if v < peak_th * 0.5])
    clarity = 1.0  # 默认满分
    if peak_values and valley_values:
        avg_peak = sum(peak_values[:3]) / min(3, len(peak_values))
        avg_valley = sum(valley_values[:3]) / min(3, len(valley_values))
        if avg_valley > 0:
            clarity = min(1.0, (avg_peak / avg_valley - 1) / 5.0)
        clarity = max(0.3, clarity)  # 最低 0.3，不全盘否定

    def _conf(margin: float, max_margin: float = 1.0) -> float:
        """置信度 = 0.5 + 0.5 × min(离边界的距离 / 最大距离, 1)，再乘以清晰度。
        margin=0 表示刚好在边界上 → 0.5；margin=1 → 1.0。"""
        return 0.5 + 0.5 * min(abs(margin) / max_margin, 1.0)

    # ---- 分类判定 ----
    # 实测结论（基于游戏实际字体，1600×900 截图）：
    #   I   = 1 个窄峰（一根竖线占字符区 10~20%）
    #   V   = 1 个宽峰（两斜线在列投影中融合为平顶山，占 25~50%）
    #   II  = 2 个等宽窄峰（两根分离竖线）
    #   IV  = 2 个峰，一窄(I) + 一宽(V形)，宽窄比 > 1.8
    #   III = 3 个窄峰
    if n_peaks == 1:
        widths = _measure_peaks(proj, peak_th)
        if not widths:
            return None, 0.0
        peak_ratio = widths[0] / total_w  # 峰宽占比
        if peak_ratio > 0.25:
            # V: 宽峰，离 0.25 越远越确定
            conf = round(_conf(peak_ratio - 0.25, 0.25) * clarity, 2)
            if conf >= threshold:
                return 5, conf
            return None, conf
        else:
            # I: 窄峰
            conf = round(_conf(0.25 - peak_ratio, 0.12) * clarity, 2)
            if conf >= threshold:
                return 1, conf
            return None, conf

    if n_peaks == 2:
        widths = _measure_peaks(proj, peak_th)
        if len(widths) >= 2:
            wide_ratio = max(widths) / max(min(widths), 1)
            if wide_ratio > 1.8:
                # IV: 宽峰/窄峰比离 1.8 越远越确定
                conf = round(_conf(wide_ratio - 1.8, 1.0) * clarity, 2)
                if conf >= threshold:
                    return 4, conf
                return None, conf
            else:
                # II: 等宽峰
                conf = round(_conf(1.8 - wide_ratio, 1.0) * clarity, 2)
                if conf >= threshold:
                    return 2, conf
                return None, conf
        return None, 0.0

    if n_peaks == 3:
        conf = round(0.8 * clarity, 2)
        if conf >= threshold:
            return 3, conf
        return None, conf

    return None, 0.0


def detect_rank_icon(
    screenshot: np.ndarray, threshold: float = 0.7,
    skip_sides: set | None = None,
) -> dict[str, str | int | float | None]:
    """检测双方头像旁边的段位图标和等级数字。

    这是段位检测的主入口，由 RankDetector 线程每轮调用。

    搜索策略（两阶段）:
        ═══ 首次检测（无位置缓存）═══
        1. 截图缩放到 600px 宽（加速粗搜）
        2. 在缩略图上粗搜（_detect_rank_in_roi，粗+精两遍）
        3. 把缩略图坐标映射回原图坐标
        4. 在原图小范围内做一次精搜修正
        5. 把 (分辨率, 侧, x, y, 尺寸) 存入位置缓存

        ═══ 后续检测（有位置缓存）═══
        1. 从缓存读取上次的位置和尺寸
        2. 在缓存位置 ±25% 范围内直接精搜（步长 3px）
        3. 比全图搜索快 10 倍以上

    分左右半屏:
        左侧 ⅓ 宽度 = 玩家（player）
        右侧 ⅓ 宽度 = 对手（opponent）

    Args:
        screenshot: Master Duel 窗口截图（BGR 格式）
        threshold: NCC 匹配置信度阈值 (0~1)，低于此值的结果丢弃
        skip_sides: 要跳过的侧，如 {"player"} 只检测对手

    Returns:
        包含 8 个字段的字典:
            player_rank       — 己方段位，如 "铂金" / None
            player_tier       — 己方等级数字 1-5 / None（巅峰无等级）
            player_score      — 己方图标 NCC 匹配分数
            player_tier_score — 己方等级置信度
            opponent_rank     — 对方段位
            opponent_tier     — 对方等级数字
            opponent_score    — 对方图标 NCC 匹配分数
            opponent_tier_score — 对方等级置信度
    """
    _init_rank_icons()
    _load_position_cache()
    h, w = screenshot.shape[:2]

    # 从顶栏采样背景色（避免 UI 元素干扰）
    bg_color = _sample_bg(screenshot, w // 2 - 80, 10, 160, 30)

    # 初始化结果字典（双方都从 None 开始）
    result: dict[str, str | int | float | None] = {
        "player_rank": None, "player_tier": None, "player_score": 0.0, "player_tier_score": 0.0,
        "opponent_rank": None, "opponent_tier": None, "opponent_score": 0.0, "opponent_tier_score": 0.0,
    }

    # 缩略图粗搜：缩到 600px 宽，大幅减少匹配运算量
    # 原图 1920×1080 的 ROI 约 640×360 → 缩略图 200×120，匹配快约 10 倍
    scale = 600.0 / w
    small = cv2.resize(screenshot, (600, int(h * scale)))
    small_h = small.shape[0]
    small_mid = small.shape[1] // 2
    small_roi_w = small.shape[1] // 3   # 每侧占缩略图 ⅓ 宽度
    small_roi_h = small_h // 3          # 上部 ⅓ 高度

    if skip_sides is None:
        skip_sides = set()

    # 分别检测玩家（左侧）和对手（右侧）
    for side, sx in [("player", 0), ("opponent", small.shape[1] - small_roi_w)]:
        if side in skip_sides:
            continue  # 已检测到 → 跳过

        pos_key = (w, h, side)
        cached = _position_cache.get(pos_key)

        if cached:
            # ===== 有位置缓存：在已知位置附近精搜 =====
            cx, cy, csz = cached
            # 搜索范围：以缓存位置为中心，向四周扩展 25%
            px = max(0, cx - csz // 4)
            py = max(0, cy - csz // 4)
            pw = min(csz * 2, w - px)   # 最多 2 倍缓存尺寸
            ph = min(csz * 2, h - py)
            search_roi = screenshot[py:py + ph, px:px + pw]

            best_name, best_score = None, 0.0
            best_x = best_y = best_sz = 0
            for name in _RANK_LABELS:
                # 尺寸范围：缓存尺寸 ±15px，步长 3px
                for sz in range(max(30, csz - 15), min(csz + 18, pw, ph), 3):
                    tmpl = _composite_rank_icon(name, sz, bg_color)
                    if tmpl is None or tmpl.shape[0] >= search_roi.shape[0] or tmpl.shape[1] >= search_roi.shape[1]:
                        continue
                    res = cv2.matchTemplate(search_roi, tmpl, cv2.TM_CCOEFF_NORMED)
                    _, val, _, loc = cv2.minMaxLoc(res)
                    if val > best_score:
                        best_score, best_name = val, name
                        best_x, best_y = px + loc[0], py + loc[1]
                        best_sz = sz
            if best_score < threshold or best_name is None:
                continue  # 缓存失效（分辨率变了？），这一侧跳过
            name, score, rx, ry, rsz = best_name, best_score, best_x, best_y, best_sz
        else:
            # ===== 首次检测：缩略图粗搜 → 映射 → 原图精搜修正 =====
            name, score, fx, fy, fsz = _detect_rank_in_roi(
                small, sx, 0, small_roi_w, small_roi_h,
                bg_color, threshold,
            )
            if name is None:
                continue  # 这一侧没检测到

            # 把缩略图中的坐标映射回原图坐标
            rx = int(fx / scale)
            ry = int(fy / scale)
            rsz = int(fsz / scale)

            # 在原图映射位置附近做一次精搜修正（消除缩放误差）
            search_x = max(0, rx - rsz // 4)
            search_y = max(0, ry - rsz // 4)
            search_w = min(rsz * 2, w - search_x)
            search_h = min(rsz * 2, h - search_y)
            search_roi = screenshot[search_y:search_y + search_h,
                                    search_x:search_x + search_w]
            tmpl = _composite_rank_icon(name, rsz, bg_color)
            if tmpl is not None:
                res = cv2.matchTemplate(search_roi, tmpl, cv2.TM_CCOEFF_NORMED)
                _, _, _, loc = cv2.minMaxLoc(res)
                rx = search_x + loc[0]
                ry = search_y + loc[1]

            # 记住位置并持久化——下次就不用缩略图粗搜了
            _position_cache[pos_key] = (rx, ry, rsz)
            _save_position_cache()

        # 写入结果
        rank_label = _RANK_LABELS.get(name, name)
        result[f"{side}_rank"] = rank_label
        result[f"{side}_score"] = score
        # 巅峰不检测等级数字（_NO_TIER_RANKS）
        if rank_label not in _NO_TIER_RANKS:
            tier, tier_conf = _detect_tier_number(screenshot, rx, ry, rsz, threshold)
            result[f"{side}_tier"] = tier
            result[f"{side}_tier_score"] = tier_conf
        else:
            result[f"{side}_tier_score"] = 0.0

    return result
