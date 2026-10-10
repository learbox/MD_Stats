"""应用状态持久化 — 读写 .app_state.toml。

存储窗口位置、列宽、分割条比例等运行时状态，
每次关闭窗口时写入，下次启动时恢复。
"""

import tomllib
from pathlib import Path

from src.config import get_project_root

_APP_STATE_PATH = get_project_root() / ".app_state.toml"

# 各字段默认值（集中管理兜底，新增字段在此添加）
# stats / record — 全部列宽（像素），record 不含隐藏列 0
# splitter      — [上, 下] 分割条绝对尺寸
# main_pos      — 主窗口上次关闭时的屏幕位置 [x, y]
# float_pos     — 悬浮窗上次关闭时的屏幕位置 [x, y]
# float_visible — 上次退出时悬浮窗是否打开
# 注：stats / record / splitter 为调优后的首启布局（发布包 .app_state.toml 据此生成）；
#     位置类字段保持通用默认——首启位置与屏幕相关，由程序运行后自行记录
APP_STATE_DEFAULTS = {
    "stats":     [93, 64, 44, 45, 77, 91, 90, 94, 96, 93, 78, 78, 67, 64, 75],
    "record":    [115, 100, 100, 113, 100, 100, 72, 77, 74, 100],
    "splitter":  [191, 265],
    "main_pos":  [100, 100],
    "float_pos": [100, 100],
    "float_visible": False,   # 上次退出时悬浮窗是否打开
}


def read_app_state() -> dict:
    """读取 .app_state.toml，文件不存在/缺字段时用默认值补齐。

    用户手动删除文件或升级到新版本时，缺失的字段自动回填默认值，
    下次关闭窗口时写回完整文件。
    """
    try:
        with open(_APP_STATE_PATH, "rb") as f:
            data = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        data = {}
    for key, default in APP_STATE_DEFAULTS.items():
        if key not in data:
            data[key] = default
    return data


# 每个字段对应的中文注释
_STATE_COMMENTS: dict[str, str] = {
    "stats":     "统计表格各列宽度（像素），顺序与表格列一致",
    "record":    "记录表格各列宽度（像素），不包含隐藏的序号列和拉伸列",
    "splitter":  "主窗口上下分割比例 [统计区高度, 记录区高度]",
    "main_pos":  "主窗口上次关闭时的屏幕位置 [x, y]",
    "float_pos": "悬浮窗上次关闭时的屏幕位置 [x, y]",
    "float_visible": "上次退出时悬浮窗是否打开（true = 启动时自动恢复）",
}


def _format_state(data: dict) -> str:
    """将状态字典格式化为带注释的 TOML 文本（tomllib 只读，需手动生成）。

    按 APP_STATE_DEFAULTS 的字段顺序，输出 data 中实际存在的字段。
    """
    lines: list[str] = [
        "# ============================================================",
        "# 应用窗口状态 — 由 MD Stats 自动生成",
        "#",
        "# 保存主窗口和悬浮窗的位置、列宽、分割比例，",
        "# 下次启动时自动恢复到上次关闭时的状态。",
        "# 手动删除此文件可恢复默认布局。",
        "# ============================================================",
        "",
    ]
    for key in APP_STATE_DEFAULTS:
        if key not in data:
            continue
        val = data[key]
        comment = _STATE_COMMENTS.get(key, "")
        if isinstance(val, list):
            items = ", ".join(str(v) for v in val)
            lines.append(f"{key} = [{items}]  # {comment}")
        elif isinstance(val, bool):
            lines.append(f"{key} = {str(val).lower()}  # {comment}")
        else:
            lines.append(f"{key} = {val}  # {comment}")
    return "\n".join(lines) + "\n"


def write_app_state(data: dict) -> None:
    """写入 .app_state.toml（data 由 read_app_state 保证含全部字段）。"""
    _APP_STATE_PATH.write_text(_format_state(data), encoding="utf-8")


def generate_initial_state(path: Path) -> None:
    """生成发布包内的初始 .app_state.toml（仅预置布局字段）。

    仅包含列宽与分割比例（首启体验优化）；窗口位置与悬浮窗开关不预置——
    程序首启后按实际使用记录，缺失字段读取时按 APP_STATE_DEFAULTS 兜底。
    """
    preset = {k: APP_STATE_DEFAULTS[k] for k in ("stats", "record", "splitter")}
    path.write_text(_format_state(preset), encoding="utf-8")


def parse_pos(raw: object, min_val: int = -100) -> list[int] | None:
    """验证并返回有效的 [x, y] 坐标列表，无效则返回 None。"""
    if isinstance(raw, list) and len(raw) == 2:
        if all(isinstance(v, (int, float)) for v in raw):
            x, y = int(raw[0]), int(raw[1])
            if x >= min_val and y >= min_val:
                return [x, y]
    return None
