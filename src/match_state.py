"""对局状态机 — 三阶段"硬币 → 先后攻 → 胜负"的纯数据管理。

从 MainWindow 中提取，只管状态推进/回退/缓存，
不涉及 UI 更新、CSV 写入、worker 同步等副作用。

================================================================================
状态转换
================================================================================

    阶段0 (等硬币)  ──advance_coin──→  阶段1 (等先后攻)
    阶段1 (等先后攻) ──advance_turn──→  阶段2 (等胜负)
    阶段2 (等胜负)  ──reset────────→   阶段0 (等硬币)

    任何阶段 ──undo──→ 上一阶段（阶段0 不可撤销）

    手动录入和自动识别共用同一个状态机，
    先到先得——手动选了硬币，自动识别就跳过硬币阶段。
"""


class MatchState:
    """三阶段对局状态机（纯数据，无 UI 依赖）。

    属性:
        stage: 当前阶段 (0=等硬币, 1=等先后攻, 2=等胜负)
        coin_cache: 硬币结果 ("win"/"lose"/"")
        turn_cache: 先后攻结果 ("first"/"second"/"")
        rank_cache: 段位升降 ("up"/"down"/"")
    """

    def __init__(self) -> None:
        self.stage: int = 0
        self.coin_cache: str = ""
        self.turn_cache: str = ""
        self.rank_cache: str = ""

    def advance_coin(self, coin_win: str) -> bool:
        """自动识别到硬币结果 → 推进到阶段1。

        仅当 stage == 0 时生效（先到先得）。
        返回是否推进成功。
        """
        if self.stage != 0:
            return False
        self.coin_cache = coin_win
        self.stage = 1
        return True

    def advance_turn(self, turn: str) -> bool:
        """自动识别到先后攻 → 推进到阶段2。

        仅当 stage == 1 时生效。
        返回是否推进成功。
        """
        if self.stage != 1:
            return False
        self.turn_cache = turn
        self.stage = 2
        return True

    def set_rank(self, rank: str) -> None:
        """缓存段位升降结果（不推进阶段）。"""
        self.rank_cache = rank

    def manual_step(self, side: str) -> tuple[int, str]:
        """手动按钮点击 → 根据当前阶段解释 side 语义并推进。

        返回 (new_stage, turn_value):
            阶段0: side = "win"/"lose" → 缓存硬币, 返回 (1, "")
            阶段1: side = "win"→"first" / "lose"→"second", 返回 (2, turn)
            阶段2: side = "win"/"lose" = 胜负, 返回 (2, side)  # 不推进，由调用方处理

        注意：阶段2的记录写入由 MainWindow 负责，此处不调用 add_record。
        """
        if self.stage == 0:
            self.coin_cache = side
            self.stage = 1
            return (1, "")
        elif self.stage == 1:
            turn = "first" if side == "win" else "second"
            self.turn_cache = turn
            self.stage = 2
            return (2, turn)
        else:
            # 阶段2: 返回结果让 MainWindow 写 CSV
            return (2, side)

    def undo(self) -> int:
        """撤销上一阶段选择，逐级回退。返回回退后的阶段号。"""
        if self.stage == 1:
            self.coin_cache = ""
            self.stage = 0
        elif self.stage == 2:
            self.turn_cache = ""
            self.stage = 1
        return self.stage

    def reset(self) -> None:
        """重置所有阶段到初始状态（一局完成后调用）。"""
        self.stage = 0
        self.coin_cache = ""
        self.turn_cache = ""
        self.rank_cache = ""

    def snapshot(self) -> dict[str, str]:
        """返回当前缓存的快照（用于 reset 前保存通知所需信息）。"""
        return {
            "coin": self.coin_cache,
            "turn": self.turn_cache,
            "rank": self.rank_cache,
        }
