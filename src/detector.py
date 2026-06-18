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
# =============================================================================

_RANK_ICONS_DIR = get_project_root() / "resource" / "templates" / "rankicons" / "large"

# 段位图标名 → 显示标签映射
_RANK_LABELS: dict[str, str] = {}

# 源素材缓存：{文件名: (BGR, Alpha)}，size = 290×290
_rank_icon_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}


def _init_rank_icons() -> None:
    """预加载全部段位图标源素材（RGBA）到内存缓存。"""
    global _RANK_LABELS, _rank_icon_cache
    if _rank_icon_cache:
        return

    _RANK_LABELS = {
        "img_rankicon_01": "Rookie", "img_rankicon_02": "Bronze",
        "img_rankicon_03": "Silver", "img_rankicon_04": "Gold",
        "img_rankicon_05": "Platinum", "img_rankicon_06": "Diamond",
        "img_rankicon_07": "Master",
    }

    for name in list(_RANK_LABELS) + [
        "img_rankicon_tier1", "img_rankicon_tier2", "img_rankicon_tier3",
        "img_rankicon_tier4", "img_rankicon_tier5",
    ]:
        path = _RANK_ICONS_DIR / f"{name}_l.png"
        if path.exists():
            raw = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
            if img is not None and img.shape[2] == 4:
                _rank_icon_cache[name] = (img[:, :, :3], img[:, :, 3])


def _sample_bg(screenshot: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """采样指定区域的平均背景色（BGR 三通道），用于 RGBA 合成。"""
    region = screenshot[max(0, y):y + h, max(0, x):x + w]
    if region.size == 0:
        return np.array([128, 128, 128], dtype=np.float32)
    return region.reshape(-1, 3).mean(axis=0).astype(np.float32)


def _composite_rank_icon(name: str, size: int, bg_color: np.ndarray) -> np.ndarray | None:
    """将源素材 RGBA 缩放到指定尺寸并合成到背景色上，返回 BGR 模板。"""
    entry = _rank_icon_cache.get(name)
    if entry is None:
        return None
    bgr, alpha = entry
    scaled_bgr = cv2.resize(bgr, (size, size))
    scaled_alpha = cv2.resize(alpha, (size, size))
    alpha_f = scaled_alpha.astype(np.float32) / 255.0
    bg = np.full((size, size, 3), bg_color, dtype=np.float32)
    return (scaled_bgr.astype(np.float32) * alpha_f[:, :, None]
            + bg * (1 - alpha_f[:, :, None])).astype(np.uint8)


def _detect_rank_in_roi(
    screenshot: np.ndarray, roi_x: int, roi_y: int, roi_w: int, roi_h: int,
    bg_color: np.ndarray, threshold: float = 0.7,
) -> tuple[str | None, float, int, int, int]:
    """在指定 ROI 内搜索最佳段位图标，返回 (图标名, 分数, x, y, 尺寸)。"""
    _init_rank_icons()

    roi = screenshot[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]

    min_sz = max(40, roi_h // 3)
    max_sz = min(roi_h * 2, roi_w // 2)

    best_name, best_score = None, 0.0
    best_x, best_y, best_sz = 0, 0, 0

    for name in _RANK_LABELS:
        # 先粗搜（步长 12），再精搜（缩小候选范围 ±8，步长 2）
        for sz in range(min_sz, max_sz, 12):
            tmpl = _composite_rank_icon(name, sz, bg_color)
            if tmpl is None or tmpl.shape[0] > roi.shape[0] or tmpl.shape[1] > roi.shape[1]:
                continue
            result = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(result)
            if val > best_score:
                best_score, best_name = val, name
                best_x, best_y = roi_x + loc[0], roi_y + loc[1]
                best_sz = sz

        # 如果找到高分候选，在临近尺寸精搜
        if best_name == name and best_score > 0.5:
            for sz in range(max(min_sz, best_sz - 10), min(max_sz, best_sz + 12), 2):
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
        return None, best_score, 0, 0, 0
    return best_name, best_score, best_x, best_y, best_sz


def _detect_tier_number(
    screenshot: np.ndarray, rank_x: int, rank_y: int, rank_w: int,
) -> tuple[int | None, float]:
    """从段位图标下方裁出数字区域，用连通组件投票识别 I~V。

    Returns:
        (数字 1-5 | None, 置信度 0-1)。None 表示无法确定。
    """
    h, w = screenshot.shape[:2]
    tx = int(rank_x + 0.39 * rank_w)
    ty = int(rank_y + 0.83 * rank_w)
    tw = int(0.22 * rank_w)
    th = int(0.11 * rank_w)

    # 边界检查
    if tx < 0 or ty < 0 or tx + tw > w or ty + th > h or tw <= 0 or th <= 0:
        return None, 0.0

    gray = cv2.cvtColor(
        screenshot[ty:ty + th, tx:tx + tw], cv2.COLOR_BGR2GRAY
    )

    # 多阈值投票连通块数
    votes: dict[int, int] = {}
    for thresh in range(60, 150, 5):
        _, b = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
        n, labels = cv2.connectedComponents(255 - b, connectivity=8)
        valid = sum(1 for i in range(1, n) if (labels == i).sum() >= 3)
        votes[valid] = votes.get(valid, 0) + 1

    count = max(votes, key=votes.get)  # type: ignore[arg-type]
    confidence = votes[count] / sum(votes.values())

    if count <= 0:
        return None, 0.0
    if count <= 3:
        return count, confidence

    # count >= 4 → 可能是 IV 或 V，用暗像素占比辅助判断
    dark_ratio = (gray < 120).mean()
    if dark_ratio < 0.3:
        return 4, confidence * 0.7  # IV 笔画稀疏
    return 5, confidence * 0.7      # V 更密


def detect_rank_icon(
    screenshot: np.ndarray, threshold: float = 0.7,
) -> dict[str, str | int | float | None]:
    """检测双方头像旁的段位图标和等级数字。

    应在 WAITING_TURN 阶段的截图上调用（UI 最稳定）。
    分左右半屏搜索：左侧 = 玩家，右侧 = 对手。

    Returns:
        {
            "player_rank": "Platinum" | None,
            "player_tier": 2 | None,
            "player_score": 0.94,
            "opponent_rank": "Diamond" | None,
            "opponent_tier": 1 | None,
            "opponent_score": 0.88,
        }
    """
    _init_rank_icons()
    h, w = screenshot.shape[:2]
    mid_x = w // 2

    # 采样背景色：取中上方空白区域
    bg_color = _sample_bg(screenshot, mid_x - 80, 10, 160, 30)

    result: dict[str, str | int | float | None] = {
        "player_rank": None, "player_tier": None, "player_score": 0.0,
        "opponent_rank": None, "opponent_tier": None, "opponent_score": 0.0,
    }

    # 左侧（玩家）
    name, score, rx, ry, rsz = _detect_rank_in_roi(
        screenshot, 0, 0, mid_x, h // 3, bg_color, threshold,
    )
    if name is not None:
        result["player_rank"] = _RANK_LABELS.get(name, name)
        result["player_score"] = score
        tier, _ = _detect_tier_number(screenshot, rx, ry, rsz)
        result["player_tier"] = tier

    # 右侧（对手）
    name, score, rx, ry, rsz = _detect_rank_in_roi(
        screenshot, mid_x, 0, w - mid_x, h // 3, bg_color, threshold,
    )
    if name is not None:
        result["opponent_rank"] = _RANK_LABELS.get(name, name)
        result["opponent_score"] = score
        tier, _ = _detect_tier_number(screenshot, rx, ry, rsz)
        result["opponent_tier"] = tier

    return result
