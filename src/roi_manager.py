"""统一位置缓存管理 — 读写 roi.toml 和 rank_positions.toml。

================================================================================
为什么需要统一？
================================================================================

项目中有两套位置缓存系统，格式不统一：
    1. roi.toml（每分辨率一个）— 三阶段检测的搜索区域 [x, y, w, h]
    2. rank_positions.toml（全局一个）— 段位图标的屏幕位置 [x, y, size]

两套系统的核心需求相同：记住"目标在屏幕上的位置"，下次跳过全图搜索。
统一后格式为 [x, y, w, h]，段位图标用 w=h 的正方形。

================================================================================
使用示例
================================================================================

    from src.roi_manager import load_regions, save_region, load_icon_positions, save_icon_position

    # 三阶段 ROI
    regions = load_regions("1920x1080")  # → {"coin": (700,630,500,200), ...}
    save_region("1920x1080", "coin", 700, 630, 500, 200)

    # 段位图标位置
    icons = load_icon_positions()  # → {(1920,1080,"player"): (77,110,179,179), ...}
    save_icon_position(1920, 1080, "player", 77, 110, 179, 179)
"""

from __future__ import annotations

import tomllib

from src.config import get_project_root

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = get_project_root() / "resource" / "templates"
_ICON_POSITIONS_PATH = _TEMPLATES_DIR / "rankicons" / "rank_positions.toml"

# ---------------------------------------------------------------------------
# 三阶段 ROI（roi.toml）
# ---------------------------------------------------------------------------

def load_regions(resolution: str) -> dict[str, tuple[int, int, int, int]]:
    """加载指定分辨率的 ROI 配置。

    从 resource/templates/{分辨率}/roi.toml 读取 [coin]/[turn]/[result]/[rank]。
    文件不存在或格式损坏时返回空字典（调用方走全图搜索兜底）。

    Args:
        resolution: 分辨率字符串，如 "1920x1080"。

    Returns:
        {"coin": (x,y,w,h), "turn": (x,y,w,h), ...}  或  {}
    """
    path = _TEMPLATES_DIR / resolution / "roi.toml"
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    result: dict[str, tuple[int, int, int, int]] = {}
    for section in ("coin", "turn", "result", "rank"):
        if section in data:
            s = data[section]
            x = int(s.get("x", 0))
            y = int(s.get("y", 0))
            w = int(s.get("width", 0))
            h = int(s.get("height", 0))
            if w > 0 and h > 0:
                result[section] = (x, y, w, h)
    return result


def save_region(resolution: str, section: str,
                x: int, y: int, w: int, h: int) -> None:
    """保存一个 ROI 区域到指定分辨率的 roi.toml。

    以匹配点为中心、模板尺寸 +100px 为范围，留足余量防止下次偏移。
    已存在的 section 不重复写入（保持社区测量数据不被覆盖）。

    Args:
        resolution: 分辨率字符串，如 "1920x1080"。
        section: ROI 名称，"coin" / "turn" / "result" / "rank"。
        x: ROI 左上角 X 坐标（像素）。
        y: ROI 左上角 Y 坐标（像素）。
        w: ROI 宽度（像素）。
        h: ROI 高度（像素）。
    """
    path = _TEMPLATES_DIR / resolution / "roi.toml"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return  # 目录创建失败，静默降级

    if path.exists():
        text = path.read_text(encoding="utf-8")
        # 已存在该 section → 不覆盖（尊重社区测量数据）
        if f"[{section}]" in text:
            return
    else:
        text = _ROI_HEADER

    # 追加 section
    label_map = {"coin": "硬币检测", "turn": "先后攻检测",
                 "result": "胜负检测", "rank": "段位升降检测"}
    label = label_map.get(section, section)
    text += (
        f"\n# ---- {label} ----\n"
        f"[{section}]\n"
        f"x = {x}  # ROI 左上角 X 坐标（像素）\n"
        f"y = {y}  # ROI 左上角 Y 坐标（像素）\n"
        f"width = {w}  # ROI 宽度（像素）\n"
        f"height = {h}  # ROI 高度（像素）\n"
    )
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass  # 写文件失败不影响程序运行


_ROI_HEADER = """\
# ============================================================
# 模板匹配搜索区域 — 由 MD Stats 自动生成
#
# [coin]/[turn]/[result] 为社区测量数据。
# [rank] 首次检测到段位标识后自动写入。
#
# 坐标格式：x=左上角X, y=左上角Y, width=宽度, height=高度（像素）。
# 裁剪搜索区域后匹配速度提升约 18 倍。
# 手动删除此文件可重置为全图搜索。
# ============================================================
"""

# ---------------------------------------------------------------------------
# 段位图标位置（rank_positions.toml）
# ---------------------------------------------------------------------------

def load_icon_positions() -> dict[
    tuple[int, int, str], tuple[int, int, int, int]
]:
    """加载段位图标在屏幕上的位置缓存。

    从 resource/templates/rankicons/rank_positions.toml 读取，
    返回 {(宽, 高, "player"/"opponent"): (x, y, w, h)}。

    兼容旧格式 [x, y, size] → 自动转换为 [x, y, size, size]。

    Returns:
        位置缓存字典或空字典。
    """
    if not _ICON_POSITIONS_PATH.exists():
        return {}
    try:
        with open(_ICON_POSITIONS_PATH, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}

    result: dict[tuple[int, int, str], tuple[int, int, int, int]] = {}
    for side in ("player", "opponent"):
        section = data.get(side, {})
        for res_key, vals in section.items():
            if not isinstance(vals, list):
                continue
            parts = res_key.split("x")
            if len(parts) != 2:
                continue
            w_key, h_key = int(parts[0]), int(parts[1])
            if len(vals) == 3:
                # 旧格式 [x, y, size] → 新格式 [x, y, size, size]
                result[(w_key, h_key, side)] = (
                    int(vals[0]), int(vals[1]), int(vals[2]), int(vals[2]))
            elif len(vals) == 4:
                result[(w_key, h_key, side)] = (
                    int(vals[0]), int(vals[1]), int(vals[2]), int(vals[3]))
    return result


def save_icon_position(resolution_w: int, resolution_h: int,
                       side: str, x: int, y: int, w: int, h: int) -> None:
    """保存一个段位图标的位置到 rank_positions.toml。

    首次检测成功后调用，后续启动直接读取以跳过全图搜索。

    Args:
        resolution_w: 分辨率宽度（像素）。
        resolution_h: 分辨率高度（像素）。
        side: "player" 或 "opponent"。
        x: 图标左上角 X 坐标（像素）。
        y: 图标左上角 Y 坐标（像素）。
        w: 图标宽度（像素）。
        h: 图标高度（像素，通常 w = h）。
    """
    label_map = {"player": "己方", "opponent": "对方"}

    # 加载已有数据
    existing: dict[str, dict[str, list[int]]] = {}
    if _ICON_POSITIONS_PATH.exists():
        try:
            with open(_ICON_POSITIONS_PATH, "rb") as f:
                existing = tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError):
            pass

    # 更新内存中的条目
    if side not in existing:
        existing[side] = {}
    existing[side][f"{resolution_w}x{resolution_h}"] = [x, y, w, h]

    # 按侧分组写入
    lines: list[str] = [
        "# ============================================================",
        "# 段位图标位置缓存 — 由 MD Stats 自动生成",
        "#",
        "# 首次检测到段位图标后自动写入，后续启动直接读取以加速检测。",
        "# 格式: {分辨率} = [x, y, w, h]",
        "#   x  — 图标左上角 X 坐标（像素）",
        "#   y  — 图标左上角 Y 坐标（像素）",
        "#   w  — 图标宽度（像素）",
        "#   h  — 图标高度（像素，通常 w = h）",
        "# 手动删除此文件可强制重新全图搜索。",
        "# ============================================================",
        "",
    ]
    for s in ("player", "opponent"):
        entries = existing.get(s, {})
        if not entries:
            continue
        lines.append(f"# ---- {label_map.get(s, s)}段位图标 ----")
        lines.append(f"[{s}]")
        for res_key in sorted(entries.keys()):
            vals = entries[res_key]
            lines.append(f"{res_key} = {vals}")
        lines.append("")

    try:
        _ICON_POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ICON_POSITIONS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
