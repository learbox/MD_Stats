"""CSV 数据持久化模块 — 对局记录的存储、读取和统计。

================================================================================
数据存储
================================================================================

活跃 CSV 文件由 _active_csv_path 变量控制，默认为 csv/data.csv。
通过 set_active_csv() 可切换到其他文件（如按日期的 data-YYYY-MM-DD.csv）。
所有读写函数（load_records、save_records、add_record）均使用此变量。

CSV 文件使用 UTF-8 编码，表头如下:

    序号 | 日期 | 时间 | 使用卡组 | 对方卡组 | 赢硬币 | 先后攻 | 结果 | 备注
    -----+------+------+---------+---------+-------+-------+------+-----
    1    | ...  | ...  | ...     | ...     | 是    | 先攻  | 胜   | ...

各字段说明:
    - 序号:    自动递增的对局编号（从 1 开始）
    - 日期:    对局日期，格式 YYYY-MM-DD（自动填充当前日期）
    - 时间:    对局时间，格式 HH:MM:SS（自动填充当前时间）
    - 使用卡组: 玩家使用的卡组名称（手动输入或通过 GUI 填写）
    - 对方卡组: 对手使用的卡组名称（需手动识别后填写）
    - 赢硬币:   "是" 或 "否"（由图像识别自动填充，也可手动填写）
    - 先后攻:   "先攻" 或 "后攻"（由图像识别自动填充，也可手动填写）
    - 结果:     "胜" 或 "负"（由图像识别自动填充，也可手动填写）
    - 备注:     自由文本备注

================================================================================
统计计算规则
================================================================================

compute_stats() 函数将对局记录按"使用卡组"分组，计算每组的:
    - 对局数、胜场数、负场数
    - 胜率 = 胜场 / 对局数 × 100%
    - 赢硬币次数、输硬币次数、赢硬币胜率、输硬币胜率
    - 先攻次数、后攻次数、先攻胜场、后攻胜场
    - 先攻胜率、后攻胜率

最后一行是"合计"行，汇总所有卡组的数据。
"""


import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from src.config import get_project_root, load_config

# ---------------------------------------------------------------------------
# CSV 文件路径
# ---------------------------------------------------------------------------
_CSV_DIR = get_project_root() / "csv"

# 活跃 CSV 文件路径 — 由 set_active_csv() / init_active_csv_from_config() 设置。
# 所有读写操作均使用此变量。
_active_csv_path: Path = _CSV_DIR / "data.csv"

# ---------------------------------------------------------------------------
# CSV 表头定义
# ---------------------------------------------------------------------------
# 这些列名在整个项目中作为字典键使用，修改时需要同步更新所有引用位置。
# 记录表格列（与 CSV 表头一致）
COLUMNS = ["序号", "日期", "时间", "使用卡组", "对方卡组", "赢硬币", "先后攻", "结果", "段位升降", "备注"]

# 统计表格列（与 compute_stats 输出的字典键一致）
STATS_COLUMNS = [
    "卡组", "对局数", "胜", "负", "胜率",
    "赢硬币次数", "输硬币次数", "赢硬币概率",
    "赢硬币胜率", "输硬币胜率",
    "先攻次数", "后攻次数", "先攻胜", "后攻胜",
    "先攻胜率", "后攻胜率",
    "升段次数", "降段次数", "升段胜率", "降段胜率",
]


def set_active_csv(filename: str) -> None:
    """切换活跃的 CSV 文件。后续所有读写将使用此文件。

    如果文件不存在，自动创建（含表头）。
    传入的文件名相对于 csv/ 目录，如 "data.csv" 或 "data-2026-05-15.csv"。

    Args:
        filename: csv/ 目录下的文件名。
    """
    global _active_csv_path
    _active_csv_path = _CSV_DIR / filename
    _ensure_csv()


def init_active_csv_from_config() -> None:
    """根据 config.toml 的 [recorder] 段初始化活跃 CSV 文件。

    应在程序启动和配置重载时调用。
    """
    cfg = load_config()
    daily = cfg.get("recorder", {}).get("daily_files", False)
    if daily:
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"data-{today}.csv"
    else:
        filename = "data.csv"
    set_active_csv(filename)


def get_active_csv_path() -> Path:
    """返回当前活跃的 CSV 文件绝对路径，供 GUI 显示。"""
    return _active_csv_path


def _ensure_csv() -> None:
    """确保活跃 CSV 文件及其所在目录存在，且文件包含正确的表头。

    此函数在每次读写 CSV 前被调用，作为安全检查:
        1. 如果 csv/ 目录不存在 → 创建它
        2. 如果活跃 CSV 文件不存在 → 创建文件并写入表头行
        3. 如果文件已存在 → 不做任何操作（保留已有数据）

    编码说明:
        使用 UTF-8 编码，确保中文字段（卡组名、先后攻、结果等）能正确存储。
    """
    csv_path = _active_csv_path
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)


def load_records() -> list[dict[str, str]]:
    """从 CSV 文件加载所有对局记录。

    Returns:
        对局记录列表，每条记录是一个字典，键为 COLUMNS 中的列名。
        例如:
            [
                {"序号": "1", "日期": "2025-01-01", "时间": "14:30:00",
                 "使用卡组": "炎兽", "对方卡组": "", "赢硬币": "是",
                 "先后攻": "先攻", "结果": "胜", "备注": ""},
                ...
            ]

    异常处理:
        - 如果 CSV 文件损坏或格式不正确，返回空列表 []
        - 不会抛出异常，以保护 GUI 不因数据问题而崩溃
    """
    _ensure_csv()
    records = []
    try:
        with open(_active_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)
    except (OSError, csv.Error, KeyError):
        # 文件损坏、权限不足或格式错误：返回空列表，GUI 显示"暂无数据"
        pass
    return records


def save_records(records: list[dict[str, str]]) -> None:
    """将所有对局记录写入 CSV 文件（全量覆写）。

    先写临时文件，成功后再原子替换目标文件。这样即使写入中途
    磁盘满或进程崩溃，也不会破坏原有 CSV 数据。

    Args:
        records: 完整的对局记录列表，每条为字典。
    """
    import os
    import tempfile
    _ensure_csv()
    csv_path = _active_csv_path
    # 写临时文件（与目标文件同目录，保证原子 rename 在同一文件系统内）
    fd, tmp_path = tempfile.mkstemp(dir=str(csv_path.parent), suffix='.csv')
    try:
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for rec in records:
                writer.writerow(rec)
        # 写入成功 → 原子替换
        os.replace(tmp_path, csv_path)
    except BaseException:
        # 写入失败 → 清理临时文件，原 CSV 不受影响
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def add_record(
    coin_win: str = "",
    turn: str = "",
    result: str = "",
    deck: str = "",
    opponent_deck: str = "",
    notes: str = "",
    rank: str = "",
) -> dict[str, str]:
    """添加一条新的对局记录到 CSV 文件。

    此函数会:
        1. 加载现有所有记录
        2. 自动填充序号（当前记录数 + 1）
        3. 自动填充日期和时间（调用时的本地时间）
        4. 将内部代码转换为中文显示
        5. 追加新记录到列表末尾
        6. 全量写回 CSV

    Args:
        coin_win:      硬币结果，'win' / 'lose'（来自图像识别），
                       或直接传中文 "是" / "否"。
        turn:          先后攻，'first' / 'second'（来自图像识别），
                       或直接传中文 "先攻" / "后攻"。
        result:        对局结果，'win' / 'lose'（来自图像识别），
                       或直接传中文 "胜" / "负"。
        deck:          玩家使用的卡组名称。
        opponent_deck: 对手使用的卡组名称（可选）。
        notes:         备注信息（可选）。
        rank:          段位升降结果，'up' / 'down' / ''（来自 detect_rank）。
                       也可直接传中文 "升段" / "降段"。默认空字符串表示普通局。

    Returns:
        新添加的记录字典。

    内部代码到中文的映射:
        - coin_win: 'win' → "是", 'lose' → "否"
        - turn:     'first' → "先攻", 'second' → "后攻"
        - result:   'win' → "胜", 'lose' → "负"
        - rank:     'up' → "升段", 'down' → "降段"
        如果传入的值不在映射表中，保持原值不变（以支持手动输入的中文）。
    """
    records = load_records()

    # 内部代码 → 中文映射
    _MAP = {
        "赢硬币": {"win": "是", "lose": "否"},
        "先后攻": {"first": "先攻", "second": "后攻"},
        "结果":   {"win": "胜", "lose": "负"},
        "段位升降": {"up": "升段", "down": "降段"},
    }

    def _map_or_warn(field: str, raw: str) -> str:
        if not raw:
            return ""
        mapped = _MAP[field].get(raw)
        if mapped is not None:
            return mapped
        known_display = {"是", "否", "先攻", "后攻", "胜", "负"}
        if raw not in known_display:
            import logging
            logging.getLogger("mdstats").warning(
                "add_record: 未识别的 %s 值 '%s'，已原样写入", field, raw
            )
        return raw

    now = datetime.now()
    new_record = {
        "序号": str(len(records) + 1),
        "日期": now.strftime("%Y-%m-%d"),
        "时间": now.strftime("%H:%M:%S"),
        "使用卡组": deck,
        "对方卡组": opponent_deck,
        "赢硬币": _map_or_warn("赢硬币", coin_win),
        "先后攻": _map_or_warn("先后攻", turn),
        "结果": _map_or_warn("结果", result),
        "段位升降": _map_or_warn("段位升降", rank),
        "备注": notes,
    }
    records.append(new_record)
    save_records(records)
    return new_record


def compute_stats(records: list[dict[str, str]]) -> list[dict[str, str | int]]:
    """根据对局记录计算统计数据（按卡组分组汇总）。

    这是统计表格的数据源。对每条记录按"使用卡组"字段分组，
    计算每组的各项统计指标。

    Args:
        records: load_records() 返回的对局记录列表。

    Returns:
        统计数据列表，每项是一个字典，包含:
            - 卡组: 卡组名称（最后一项固定为"合计"）
            - 对局数, 胜, 负, 胜率
            - 赢硬币次数, 输硬币次数, 赢硬币胜率, 输硬币胜率
            - 先攻次数, 后攻次数, 先攻胜, 后攻胜
            - 先攻胜率, 后攻胜率

        当无记录时，返回一行"暂无数据"的占位数据。

    统计规则:
        - 胜率 = 胜场数 / 总对局数 × 100%，保留一位小数
        - 分母为 0 时胜率显示 "-"
        - 使用卡组为空的对局归入"(未指定)"分组
        - 最终行按卡组名称排序，"合计"始终在最后

    实现细节:
        - 使用 collections.defaultdict 避免手动初始化每个卡组的累加器
        - 内部使用英文键（total/win/lose/coin_win/first/second 等），
          最终输出时映射为中文字段名以匹配 STATS_COLUMNS
    """
    # ---------- 无数据时返回占位行 ----------
    if not records:
        return [{
            "卡组": "暂无数据",
            "对局数": 0, "胜": 0, "负": 0,
            "胜率": "",
            "赢硬币次数": 0, "输硬币次数": 0,
            "赢硬币胜率": "", "输硬币胜率": "",
            "先攻次数": 0, "后攻次数": 0,
            "先攻胜": 0, "后攻胜": 0,
            "先攻胜率": "", "后攻胜率": "",
            "升段次数": 0, "降段次数": 0,
            "升段胜率": "", "降段胜率": "",
        }]

    # ---------- 初始化累加器 ----------
    decks: dict[str, dict] = defaultdict(lambda: {
        "total": 0,           # 总对局数
        "win": 0,             # 胜场数
        "lose": 0,            # 负场数
        "coin_win": 0,        # 赢硬币次数
        "coin_win_win": 0,    # 赢硬币且获胜次数
        "coin_lose": 0,       # 输硬币次数
        "coin_lose_win": 0,   # 输硬币但获胜次数
        "first": 0,           # 先攻次数
        "second": 0,          # 后攻次数
        "first_win": 0,       # 先攻时获胜次数
        "second_win": 0,      # 后攻时获胜次数
        "rank_up": 0,         # 升段次数
        "rank_down": 0,       # 降段次数
        "rank_up_win": 0,     # 升段且获胜次数
        "rank_down_win": 0,   # 降段且获胜次数
    })

    # ---------- 总计累加器 ----------
    total_all = 0
    win_all = 0
    lose_all = 0
    coin_win_all = 0
    coin_win_win_all = 0
    coin_lose_all = 0
    coin_lose_win_all = 0
    first_all = 0
    second_all = 0
    first_win_all = 0
    second_win_all = 0
    rank_up_all = 0
    rank_down_all = 0
    rank_up_win_all = 0
    rank_down_win_all = 0

    # ---------- 遍历所有记录，累加计数 ----------
    for r in records:
        deck = r.get("使用卡组", "") or "(未指定)"
        result = r.get("结果", "")
        coin_win_field = r.get("赢硬币", "")
        turn = r.get("先后攻", "")

        d = decks[deck]
        d["total"] += 1
        total_all += 1

        # 胜负统计
        if result == "胜":
            d["win"] += 1
            win_all += 1
        elif result == "负":
            d["lose"] += 1
            lose_all += 1

        # 硬币输赢统计
        if coin_win_field == "是":
            d["coin_win"] += 1
            coin_win_all += 1
            if result == "胜":
                d["coin_win_win"] += 1
                coin_win_win_all += 1
        elif coin_win_field == "否":
            d["coin_lose"] += 1
            coin_lose_all += 1
            if result == "胜":
                d["coin_lose_win"] += 1
                coin_lose_win_all += 1

        # 先后攻统计
        if turn == "先攻":
            d["first"] += 1
            first_all += 1
            if result == "胜":
                d["first_win"] += 1
                first_win_all += 1
        elif turn == "后攻":
            d["second"] += 1
            second_all += 1
            if result == "胜":
                d["second_win"] += 1
                second_win_all += 1

        # 段位升降统计
        seg = r.get("段位升降", "")
        if seg == "升段":
            d["rank_up"] += 1
            rank_up_all += 1
            if result == "胜":
                d["rank_up_win"] += 1
                rank_up_win_all += 1
        elif seg == "降段":
            d["rank_down"] += 1
            rank_down_all += 1
            if result == "胜":
                d["rank_down_win"] += 1
                rank_down_win_all += 1

    # ---------- 辅助函数：计算百分比 ----------
    def _rate(win_count: int, total: int) -> str:
        if total == 0:
            return "-"
        return f"{win_count / total * 100:.1f}%"

    # ---------- 组装输出 ----------
    stats = []
    for deck_name in sorted(decks):
        d = decks[deck_name]
        stats.append({
            "卡组": deck_name,
            "对局数": d["total"], "胜": d["win"], "负": d["lose"],
            "胜率": _rate(d["win"], d["total"]),
            "赢硬币次数": d["coin_win"],
            "输硬币次数": d["coin_lose"],
            "赢硬币概率": _rate(d["coin_win"], d["total"]),
            "赢硬币胜率": _rate(d["coin_win_win"], d["coin_win"]),
            "输硬币胜率": _rate(d["coin_lose_win"], d["coin_lose"]),
            "先攻次数": d["first"], "后攻次数": d["second"],
            "先攻胜": d["first_win"], "后攻胜": d["second_win"],
            "先攻胜率": _rate(d["first_win"], d["first"]),
            "后攻胜率": _rate(d["second_win"], d["second"]),
            "升段次数": d["rank_up"], "降段次数": d["rank_down"],
            "升段胜率": _rate(d["rank_up_win"], d["rank_up"]),
            "降段胜率": _rate(d["rank_down_win"], d["rank_down"]),
        })

    # ---------- 总计行（始终放在最后） ----------
    stats.append({
        "卡组": "合计",
        "对局数": total_all, "胜": win_all, "负": lose_all,
        "胜率": _rate(win_all, total_all),
        "赢硬币次数": coin_win_all,
        "输硬币次数": coin_lose_all,
        "赢硬币概率": _rate(coin_win_all, total_all),
        "赢硬币胜率": _rate(coin_win_win_all, coin_win_all),
        "输硬币胜率": _rate(coin_lose_win_all, coin_lose_all),
        "先攻次数": first_all, "后攻次数": second_all,
        "先攻胜": first_win_all, "后攻胜": second_win_all,
        "先攻胜率": _rate(first_win_all, first_all),
        "后攻胜率": _rate(second_win_all, second_all),
        "升段次数": rank_up_all, "降段次数": rank_down_all,
        "升段胜率": _rate(rank_up_win_all, rank_up_all),
        "降段胜率": _rate(rank_down_win_all, rank_down_all),
    })

    return stats
