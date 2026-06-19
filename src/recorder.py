"""CSV 数据持久化模块 — 对局记录的存储、读取和统计。

================================================================================
数据存储
================================================================================

活跃 CSV 文件由 _active_csv_path 变量控制，默认为 csv/data.csv。
通过 set_active_csv() 可切换到其他文件（如按日期的 data-YYYY-MM-DD.csv）。
所有读写函数（load_records、save_records、add_record）均使用此变量。

CSV 文件使用 UTF-8 编码，表头如下:

    序号 | 日期 | 时间 | 使用卡组 | 己方段位 | 对方卡组 | 对方段位 | 赢硬币 | 先后攻 | 结果 | 段位升降 | 备注
    -----+------+------+---------+---------+---------+---------+-------+-------+------+---------+-----
    1    | ...  | ...  | ...     | 铂金 II | ...     | 钻石 I  | 是    | 先攻  | 胜   | 升段    | ...

各字段说明:
    - 序号:    自动递增的对局编号（从 1 开始）
    - 日期:    对局日期，格式 YYYY-MM-DD（自动填充当前日期）
    - 时间:    对局时间，格式 HH:MM:SS（自动填充当前时间）
    - 使用卡组: 玩家使用的卡组名称（手动输入或通过 GUI 填写）
    - 己方段位: 由图像识别自动检测（段位图标 + 等级数字），如 "铂金 II"
    - 对方卡组: 对手使用的卡组名称（需手动识别后填写）
    - 对方段位: 由图像识别自动检测，如 "钻石 I"

    - - 对方段位: 由图像识别自动检测，如 "钻石 I"

    - 赢硬币:   "是" 或 "否"（由图像识别自动填充，也可手动填写）
    - 先后攻:   "先攻" 或 "后攻"（由图像识别自动填充，也可手动填写）
    - 结果:     "胜" 或 "负"（由图像识别自动填充，也可手动填写）
    - 段位升降: "升段" / "降段" / ""（升段/降段局，普通局为空）
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
from src import logger as _log

# ---------------------------------------------------------------------------
# CSV 文件路径
# ---------------------------------------------------------------------------
_CSV_DIR = get_project_root() / "csv"

# 活跃 CSV 文件路径 — 由 set_active_csv() / init_active_csv_from_config() 设置。
# 所有读写操作均使用此变量。
_active_csv_path: Path = _CSV_DIR / "data.csv"

# 暂存队列 — 当 CSV 被其他程序（如 WPS/Excel）占用导致写入失败时，
# 将未能写入的记录暂存在内存中，等下次文件可用时自动补写。
_pending_records: list[dict[str, str]] = []

# ---------------------------------------------------------------------------
# CSV 表头定义
# ---------------------------------------------------------------------------
# 这些列名在整个项目中作为字典键使用，修改时需要同步更新所有引用位置。
# 记录表格列（与 CSV 表头一致）
COLUMNS = ["序号", "日期", "时间", "使用卡组", "己方段位", "对方卡组", "对方段位", "赢硬币", "先后攻", "结果", "段位升降", "备注"]

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


def get_pending_count() -> int:
    """返回暂存队列中的记录数（因文件占用等原因未能写入）。"""
    return len(_pending_records)


def clear_pending() -> int:
    """清空暂存队列（用户确认切换文件且放弃暂存时调用）。

    Returns:
        被清空的记录数。
    """
    global _pending_records
    count = len(_pending_records)
    _pending_records.clear()
    if count > 0:
        _log.write("CSVOK", f"已清空暂存队列: {count} 条")
    return count


def get_pending_records() -> list[dict[str, str]]:
    """返回暂存队列的浅拷贝，供 GUI 显示提醒。"""
    return list(_pending_records)


def try_flush_pending() -> bool:
    """尝试将暂存队列中的记录写入 CSV 文件。

    从 CSV 加载现有记录，将 pending 记录追加到末尾并重新编号序号，
    然后尝试全量写回。写入成功则清空暂存队列。

    此函数在 add_record() 被调用时自动执行，也可由外部（如用户点击
    "重试写入"按钮）手动调用。

    Returns:
        True  — 暂存记录全部写入成功（或队列本为空）
        False — 写入失败，暂存记录保留在内存中
    """
    global _pending_records
    if not _pending_records:
        return True
    records = load_records()
    # 重新编排序号：CSV 已有记录 + pending 记录统一编号
    next_seq = len(records) + 1
    for rec in _pending_records:
        rec["序号"] = str(next_seq)
        next_seq += 1
    records.extend(_pending_records)
    if save_records(records):
        count = len(_pending_records)
        _pending_records.clear()
        _log.write("CSVOK", f"暂存记录已补写: {count} 条")
        return True
    _log.write("ERROR", f"暂存记录补写失败，仍保留 {len(_pending_records)} 条")
    return False


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
                 "使用卡组": "炎兽", "己方段位": "铂金 II",
                 "对方卡组": "", "对方段位": "钻石 I",
                 "赢硬币": "是", "先后攻": "先攻", "结果": "胜",
                 "段位升降": "", "备注": ""},
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


def save_records(records: list[dict[str, str]]) -> bool:
    """将所有对局记录写入 CSV 文件（全量覆写）。

    先写临时文件，成功后再原子替换目标文件。这样即使写入中途
    磁盘满或进程崩溃，也不会破坏原有 CSV 数据。

    Args:
        records: 完整的对局记录列表，每条为字典。

    Returns:
        True  — 写入成功
        False — 写入失败（文件被占用 / 权限不足 / 磁盘满等），原 CSV 不受影响
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
        return True
    except Exception as e:
        # 写入失败 → 清理临时文件，原 CSV 不受影响
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        _log.write("ERROR", f"CSV 保存失败: {e}")
        return False


def add_record(
    coin_win: str = "",
    turn: str = "",
    result: str = "",
    deck: str = "",
    opponent_deck: str = "",
    notes: str = "",
    rank: str = "",
    player_rank: str = "",
    opponent_rank: str = "",
) -> dict[str, str] | None:
    """添加一条新的对局记录到 CSV 文件。

    暂存记录和本次记录合并为一次写入，减少磁盘 I/O。

    如果写入失败（如文件被 WPS/Excel 占用），本次记录存入暂存队列，
    之前已在队列中的暂存记录保持不变，下次一起重试。

    Returns:
        成功时返回新记录字典，失败时返回 None。

    内部代码 → 中文映射:
        - coin_win: 'win' → "是", 'lose' → "否"
        - turn:     'first' → "先攻", 'second' → "后攻"
        - result:   'win' → "胜", 'lose' → "负"
        - rank:     'up' → "升段", 'down' → "降段"
    """
    global _pending_records

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

    # 构造本次新记录（序号先占位，写入前统一编号）
    now = datetime.now()
    new_record = {
        "序号": "",  # 统一编号时填充
        "日期": now.strftime("%Y-%m-%d"),
        "时间": now.strftime("%H:%M:%S"),
        "使用卡组": deck,
        "己方段位": player_rank,
        "对方卡组": opponent_deck,
        "对方段位": opponent_rank,
        "赢硬币": _map_or_warn("赢硬币", coin_win),
        "先后攻": _map_or_warn("先后攻", turn),
        "结果": _map_or_warn("结果", result),
        "段位升降": _map_or_warn("段位升降", rank),
        "备注": notes,
    }

    # 合并：CSV 已有记录 + 暂存记录 + 本次新记录，统一编号一次写入
    to_write = list(records)
    seq = len(records) + 1
    for rec in _pending_records:
        rec["序号"] = str(seq)
        seq += 1
        to_write.append(rec)
    new_record["序号"] = str(seq)
    to_write.append(new_record)

    if save_records(to_write):
        count = len(_pending_records)
        _pending_records.clear()
        if count > 0:
            _log.write("CSVOK", f"暂存记录已补写: {count} 条")
        return new_record

    # 写入失败 → 本次记录加入暂存队列（旧暂存保持不动）
    _pending_records.append(new_record)
    _log.write("ERROR",
        f"CSV 写入失败，记录已暂存 (pending: {len(_pending_records)} 条)"
    )
    return None


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


def compute_rank_stats(
    records: list[dict[str, str]], deck: str = "",
) -> list[dict[str, str | int]]:
    """统计当前卡组 vs 各对手段位大段的胜率。

    只按段位大段分组（如"铂金 II"和"铂金 III"都归入"铂金"），
    未指定段位的对局归入"未知"。

    Args:
        records: load_records() 返回的对局记录列表。
        deck:    筛选的卡组名，空字符串=全部卡组。

    Returns:
        按段位排序的统计列表，含"合计"行。
    """
    # 段位顺序
    RANK_ORDER = ["新手", "青铜", "白银", "黄金", "铂金", "钻石", "大师", "巅峰"]

    def _tier_group(rank_str: str) -> str:
        """从'铂金 II'提取'铂金'，未知归'未知'。"""
        for tier in RANK_ORDER:
            if rank_str.startswith(tier):
                return tier
        return "未知"

    def _rate(win: int, total: int) -> str:
        if total == 0:
            return "-"
        return f"{win / total * 100:.1f}%"

    # 按大段分组计数：{段位: {"total":, "win":, "lose":}}
    ranks: dict[str, dict] = {r: {"total": 0, "win": 0, "lose": 0} for r in RANK_ORDER}
    ranks["未知"] = {"total": 0, "win": 0, "lose": 0}

    total_all = win_all = lose_all = 0

    for r in records:
        if deck and r.get("使用卡组", "") != deck:
            continue
        group = _tier_group(r.get("对方段位", ""))
        ranks[group]["total"] += 1
        total_all += 1
        if r.get("结果", "") == "胜":
            ranks[group]["win"] += 1
            win_all += 1
        else:
            ranks[group]["lose"] += 1
            lose_all += 1

    stats = []
    for rank_name in RANK_ORDER + ["未知"]:
        d = ranks[rank_name]
        if d["total"] > 0 or rank_name == "未知":
            stats.append({
                "段位": rank_name,
                "对局数": d["total"], "胜": d["win"], "负": d["lose"],
                "胜率": _rate(d["win"], d["total"]),
            })

    if total_all > 0:
        stats.append({
            "段位": "合计",
            "对局数": total_all, "胜": win_all, "负": lose_all,
            "胜率": _rate(win_all, total_all),
        })

    return stats


# =============================================================================
# 段位名称工具 — 用于详细统计弹窗的段位筛选
# =============================================================================

# 游戏中的 8 个大段位，按从低到高排列。
# CSV 中"己方段位"列存储的是完整段位字符串，如 "黄金 II"、"钻石 I"。
# 我们需要从这些字符串中提取出大段名（"黄金"、"钻石"）用于分组筛选。
KNOWN_RANK_TIERS = ["新手", "青铜", "白银", "黄金", "铂金", "钻石", "大师", "巅峰"]


def extract_rank_tier(rank_str: str) -> str:
    """从完整段位字符串中提取大段名（去掉 I~V 等级数字）。

    游戏里段位存储格式是 "大段名 + 空格 + 罗马数字等级"，例如：
        "黄金 II"  → 大段是 "黄金"
        "钻石 I"   → 大段是 "钻石"

    这个函数只返回大段名，忽略后面的等级数字。
    如果段位不在 8 大段中（比如未来新出的段位、或者空字符串），
    返回空字符串 ""，调用方会把它们归到 "无段位/其他" 分类。

    示例:
        >>> extract_rank_tier("黄金 II")
        '黄金'
        >>> extract_rank_tier("黑铁 IV")   # 黑铁不在 8 大段里
        ''
        >>> extract_rank_tier("")           # 空字符串
        ''
    """
    # 从高到低遍历已知大段，检查 rank_str 是否以它开头
    # 因为段位存储为 "黄金 II"，startswith("黄金") 成立
    for tier in KNOWN_RANK_TIERS:
        if rank_str.startswith(tier):
            return tier
    # 没找到匹配 → 未知段位或无段位
    return ""


def get_available_rank_tiers(records: list[dict[str, str]]) -> list[str]:
    """扫描所有对局记录，找出数据中实际出现过的已知段位大段。

    这个函数用于动态生成段位筛选下拉框：只列出数据中真正存在的段位，
    而不是把 8 个大段全部列出来（没数据的段位列出来没意义）。

    返回的列表按 KNOWN_RANK_TIERS 的顺序排列（低段位在前），
    方便用户按段位从低到高查看。

    Args:
        records: 从 CSV 加载的对局记录列表，每条记录是一个字典

    Returns:
        数据中出现过的已知段位大段列表，如 ["青铜", "黄金", "钻石"]
    """
    tiers_in_data: set[str] = set()  # 用集合自动去重
    for r in records:
        own = r.get("己方段位", "").strip()  # 取出己方段位，去掉首尾空格
        if own:
            tier = extract_rank_tier(own)     # 提取大段名
            if tier:
                tiers_in_data.add(tier)        # 加入集合（重复自动忽略）
    # 按 KNOWN_RANK_TIERS 的顺序输出，保证下拉框排列合理
    return [t for t in KNOWN_RANK_TIERS if t in tiers_in_data]


def compute_filtered_stats(
    records: list[dict[str, str]],
    deck: str = "",
    player_rank: str = "",
) -> dict[str, str | int]:
    """按卡组和己方段位筛选后，返回单行 17 项统计指标。

    详细统计弹窗的核心计算函数。做两件事：
        1. 筛选 — 根据用户选择的卡组和己方段位，过滤出符合条件的记录
        2. 统计 — 对筛选后的记录调用 compute_stats 计算 17 项指标

    筛选逻辑:
        - deck 为空 → 不按卡组过滤（对应"全部"）
        - player_rank 为空 → 不按段位过滤（对应"全部"）
        - player_rank 为具体段位（如"黄金"）→ 只保留己方段位以"黄金"开头的记录
          例如 "黄金 I"、"黄金 II" 都会被保留
        - player_rank 为 "无段位/其他" → 保留两种记录：
            1. 己方段位为空白的（还没有检测到段位）
            2. 己方段位不在 8 大段中的（如未来的"黑铁"）

    Args:
        records: 全部对局记录
        deck: 卡组名称，空字符串表示不过滤
        player_rank: 己方段位大段名，空字符串表示不过滤

    Returns:
        单行统计结果字典，包含 "对局数"、"胜率" 等 17 项指标
    """
    filtered = []
    for r in records:
        # ---- 卡组筛选 ----
        if deck and r.get("使用卡组", "") != deck:
            continue  # 卡组不匹配，跳过这条记录

        # ---- 己方段位筛选 ----
        if player_rank:
            own = r.get("己方段位", "").strip()  # 取出己方段位，如 "黄金 II"

            if player_rank == "无段位/其他":
                # 特殊处理：匹配空白段位 + 未知段位（如黑铁）
                # extract_rank_tier 对已知段位返回大段名，对未知段位返回 ""
                # own 非空且 extract_rank_tier 返回非空 → 是已知段位 → 跳过
                if own and extract_rank_tier(own):
                    continue
            elif not own.startswith(player_rank):
                # 正常筛选：己方段位不以选中的大段名开头 → 跳过
                # 例如 player_rank="黄金"，own="白银 I" → startswith 失败 → 跳过
                continue

        filtered.append(r)  # 通过所有筛选条件，保留

    result = compute_stats(filtered)
    # 如果筛选后没有记录，返回全零统计（避免空列表报错）
    return result[0] if result else compute_stats([])[0]
