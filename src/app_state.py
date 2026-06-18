"""应用状态持久化 — 读写 .app_state.json。

存储窗口位置、列宽、分割条比例等运行时状态，
每次关闭窗口时写入，下次启动时恢复。
"""

import json
from typing import Any

from src.config import get_project_root

_APP_STATE_PATH = get_project_root() / ".app_state.json"

# 各字段默认值（集中管理兜底，新增字段在此添加）
# stats / record 为全部列宽（像素），record 不含隐藏列 0
# splitter 为 [上, 下] 分割条绝对尺寸，main_pos / float_pos 为 [x, y]
APP_STATE_DEFAULTS: dict[str, list[int]] = {
    "stats":     [80, 60, 45, 45, 70, 75, 75, 75, 85, 85, 80, 75, 70, 70, 75],
    "record":    [115, 90, 75, 80, 75, 80, 65, 70, 50, 65],
    "splitter":  [200, 300],
    "main_pos":  [100, 100],
    "float_pos": [100, 100],
}


def read_app_state() -> dict[str, Any]:
    """读取 .app_state.json，文件不存在/缺字段时用默认值补齐。

    用户手动删除文件或升级到新版本时，缺失的字段自动回填默认值，
    下次关闭窗口时写回完整文件。
    """
    try:
        with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data: dict[str, Any] = {}
    # 用默认值补齐缺失字段（不覆盖已有值）
    for key, default in APP_STATE_DEFAULTS.items():
        if key not in data:
            data[key] = default
    return data


def write_app_state(data: dict[str, Any]) -> None:
    """写入 .app_state.json。"""
    with open(_APP_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def parse_pos(raw: object, min_val: int = -100) -> list[int] | None:
    """验证并返回有效的 [x, y] 坐标列表，无效则返回 None。"""
    if isinstance(raw, list) and len(raw) == 2:
        if all(isinstance(v, (int, float)) for v in raw):
            x, y = int(raw[0]), int(raw[1])
            if x >= min_val and y >= min_val:
                return [x, y]
    return None
