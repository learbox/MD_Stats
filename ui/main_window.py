"""主窗口 GUI — 统计表格、记录表格、控制按钮的完整界面。

================================================================================
界面布局
================================================================================

┌──────────────────────────────────────────────────────────────┐
│  [启动] [停止]   使用卡组: [________] [修改卡组] [赢硬币] [输硬币] [撤销] │  ← 控制栏
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  卡组 │ 对局数 │ 胜 │ 负 │ 胜率 │ 赢硬币次数 │ 输硬币次数 │ 硬币胜率... │  ← 统计表格
│  ────┼───────┼────┼────┼─────┼──────────┼──────────┼───────────│    (上方)
│  炎兽 │  15   │ 10 │  5 │66.7%│    8     │    7     │ 53.3% ... │
│  闪刀 │   8   │  4 │  4 │50.0%│    2     │    6     │ 25.0% ... │
│  合计 │  23   │ 14 │  9 │60.9%│   10     │   13     │ 43.5% ... │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  日期 │ 时间 │ 使用卡组 │ ... │ 赢硬币 │ 先后攻 │ 结果 │ 备注 │  ← 记录表格
│  ────┼─────┼─────────┼─────┼───────┼───────┼─────┼─────│   (下方)
│  ...  │ ...  │  炎兽   │ ...  │  是   │ 先攻  │ 胜  │     │
│  ...  │ ...  │  炎兽   │ ...  │  否   │ 后攻  │ 负  │     │
│  ...  │ ...  │  ...    │ ...  │  ...  │ ...   │ ... │     │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  [加载数据] [复制统计] [打开CSV] [编辑配置] [重载配置] [删除最后] [关于]    │  ← 底部按钮
├──────────────────────────────────────────────────────────────┤
│  就绪 — 请点击"启动"开始                                     │  ← 状态栏
└──────────────────────────────────────────────────────────────┘

================================================================================
信号连接 (Signal-Slot 关系)
================================================================================

    StatsWorker (子线程)           MainWindow (主线程)
    ─────────────────────        ─────────────────────
    status_update    ──────────→ _on_status()         → 更新状态栏文字
    coin_win_detected ────────→ _on_coin_win_detected()→ 缓存硬币输赢结果
    turn_detected     ────────→ _on_turn_detected()    → 缓存先后攻和卡组名
    result_detected   ────────→ _on_result_detected()  → 写入 CSV，刷新表格

    GUI 按钮                 →  直接调用对应方法（主线程中执行）
    [启动]                  →  _on_start()            → 创建工作线程并启动
    [停止]                  →  _on_stop()             → 停止并销毁工作线程
    [手动按钮] [撤销]        →  _manual_step_clicked()  → 手动录入（与自动联动）
                               _on_undo()             → 逐级回退阶段
    [加载数据]               →  _on_load_data()        → 打开文件对话框切换 CSV
    [复制统计]              →  _copy_to_clipboard()   → 复制统计表格 TSV
    [打开 data.csv 目录]     →  _open_csv_dir()        → 打开文件资源管理器
    [编辑配置]               →  _on_edit_config()     → 用系统程序打开 config.toml
    [重新载入配置]            →  _on_reload_config()   → 重新加载配置并重启 Worker

================================================================================
数据流
================================================================================

    CSV 文件 (csv/data.csv)
         │
         ├── load_records() ──→ compute_stats() ──→ _refresh_stats_table()
         │                                           (刷新统计表格)
         │
         └── load_records() ───────────────────────→ _refresh_record_table()
                                                      (刷新记录表格)

"""


import json
import os
import subprocess
from pathlib import Path
from typing import Any, TypeVar

from PySide6.QtCore import QFile, Qt, QTimer
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
)

from src.config import load_config
from src.recorder import (
    add_record,
    COLUMNS as RECORD_COLUMNS,
    compute_stats,
    get_active_csv_path,
    init_active_csv_from_config,
    load_records,
    save_records,
    set_active_csv,
    STATS_COLUMNS,
)
from src.capture import get_window_status, is_window_open
from src.stats_worker import StatsWorker

# .ui 界面文件的绝对路径
UI_FILE = Path(__file__).resolve().parent / "main_window.ui"

# config.toml 的绝对路径
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"

# 表格列宽持久化文件
_COLUMN_WIDTHS_PATH = Path(__file__).resolve().parent.parent / ".column_widths.json"

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# 表格列委托 — 为特定列提供下拉菜单编辑
# ---------------------------------------------------------------------------

class ComboDelegate(QStyledItemDelegate):
    """固定选项的下拉菜单委托（用于赢硬币、先后攻、结果等列）。

    用户从下拉列表中选择后立即提交并关闭编辑器。
    """

    def __init__(self, items: list[str], parent: QTableWidget | None = None) -> None:
        super().__init__(parent)
        self._items = items

    def createEditor(
        self, parent_widget, _option, _index
    ) -> QComboBox:
        combo = QComboBox(parent_widget)
        combo.addItems(self._items)
        # activated 仅在用户从弹出列表中选择时触发，不会在 setEditorData 时误触发
        combo.activated.connect(  # type: ignore[reportUnknownMemberType]
            lambda _idx: self.commitData.emit(combo)  # type: ignore[reportUnknownMemberType]
        )
        combo.activated.connect(  # type: ignore[reportUnknownMemberType]
            lambda _idx: self.closeEditor.emit(combo)  # type: ignore[reportUnknownMemberType]
        )
        return combo

    def setEditorData(self, editor: QComboBox, index) -> None:
        value = index.data(Qt.ItemDataRole.EditRole)
        if value in self._items:
            editor.setCurrentText(value)
        elif self._items:
            editor.setCurrentIndex(0)

    def setModelData(self, editor: QComboBox, model, index) -> None:
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class EditableComboDelegate(QStyledItemDelegate):
    """可编辑的下拉菜单委托 — 允许从预设中选择或自由输入（用于对方卡组）。"""

    def __init__(self, items: list[str], parent: QTableWidget | None = None) -> None:
        super().__init__(parent)
        self._items = items

    def createEditor(
        self, parent_widget, _option, _index
    ) -> QComboBox:
        combo = QComboBox(parent_widget)
        combo.setEditable(True)
        combo.addItems(self._items)
        combo.setCurrentText("")
        return combo

    def setEditorData(self, editor: QComboBox, index) -> None:
        value = index.data(Qt.ItemDataRole.EditRole)
        if value:
            editor.setCurrentText(value)

    def setModelData(self, editor: QComboBox, model, index) -> None:
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


def _require_widget(widget: _T | None, name: str) -> _T:
    """类型收窄 findChild 的返回值 — 断言控件存在，消除 | None 警告。"""
    if widget is None:
        raise RuntimeError(f"UI 控件 '{name}' 未在 .ui 文件中找到")
    return widget


class MainWindow(QMainWindow):
    """程序的主窗口，包含所有 GUI 元素和交互逻辑。

    继承自 QMainWindow，使用中心控件 + 状态栏的标准布局。
    通过 Qt 的信号/槽机制与后台工作线程通信。
    """

    def __init__(self) -> None:
        """初始化主窗口：加载 .ui 界面文件、配置样式、连接信号、加载数据。"""
        super().__init__()

        # ---- 加载配置 ----
        self._config: dict[str, Any] = load_config()  # type: ignore[reportUnknownMemberType]

        # ---- 初始化活跃 CSV 文件 ----
        init_active_csv_from_config()  # type: ignore[reportUnknownMemberType]

        # ---- 运行时状态 ----
        self._worker: Any = None
        self._wait_timer: QTimer | None = None
        self._info_timer: QTimer | None = None
        # 统一阶段跟踪: 0=等硬币, 1=等先后攻, 2=等胜负
        self._stage: int = 0
        # 统一缓存：无论自动还是手动，硬币和先后攻结果都存这里
        # 卡组名在写 CSV 时直接从输入框读取，不做缓存
        self._coin_cache: str = ""
        self._turn_cache: str = ""
        # 防止 refresh_record_table 触发的 cellChanged 写回 CSV
        self._suppress_cell_changed: bool = False

        # ---- 从 .ui 文件加载界面 ----
        loader = QUiLoader()
        ui_file = QFile(str(UI_FILE))
        ui_file.open(QFile.OpenModeFlag.ReadOnly)
        widget = loader.load(ui_file)
        ui_file.close()
        self.setCentralWidget(widget)

        # 通过 objectName 获取各个控件的引用
        # _require_widget 将 findChild 的 X | None 收窄为 X，消除类型警告
        self._btn_start = _require_widget(widget.findChild(QPushButton, "btn_start"), "btn_start")
        self._btn_stop = _require_widget(widget.findChild(QPushButton, "btn_stop"), "btn_stop")
        self._deck_input = _require_widget(widget.findChild(QLineEdit, "deck_input"), "deck_input")
        self._btn_manual_win = _require_widget(widget.findChild(QPushButton, "btn_manual_win"), "btn_manual_win")
        self._btn_manual_lose = _require_widget(widget.findChild(QPushButton, "btn_manual_lose"), "btn_manual_lose")
        self._btn_undo = _require_widget(widget.findChild(QPushButton, "btn_undo"), "btn_undo")
        self._btn_lock_deck = _require_widget(widget.findChild(QPushButton, "btn_lock_deck"), "btn_lock_deck")
        self._stats_table = _require_widget(widget.findChild(QTableWidget, "stats_table"), "stats_table")
        self._record_table = _require_widget(widget.findChild(QTableWidget, "record_table"), "record_table")
        self._btn_reload = _require_widget(widget.findChild(QPushButton, "btn_reload"), "btn_reload")
        self._btn_copy = _require_widget(widget.findChild(QPushButton, "btn_copy"), "btn_copy")
        self._btn_delete_last = _require_widget(widget.findChild(QPushButton, "btn_delete_last"), "btn_delete_last")
        self._btn_about = _require_widget(widget.findChild(QPushButton, "btn_about"), "btn_about")
        self._btn_open_csv = _require_widget(widget.findChild(QPushButton, "btn_open_csv"), "btn_open_csv")
        self._btn_edit_config = _require_widget(widget.findChild(QPushButton, "btn_edit_config"), "btn_edit_config")
        self._btn_reload_config = _require_widget(widget.findChild(QPushButton, "btn_reload_config"), "btn_reload_config")
        self._splitter = _require_widget(widget.findChild(QSplitter, "splitter"), "splitter")

        # ---- 窗口基础设置 ----
        self.setWindowTitle("MD Stats")
        self.resize(
            self._config.get("window", {}).get("width", 1100),
            self._config.get("window", {}).get("height", 700),
        )

        # ---- 信号连接 ----
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_manual_win.clicked.connect(lambda: self._manual_step_clicked("win"))
        self._btn_manual_lose.clicked.connect(lambda: self._manual_step_clicked("lose"))
        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_lock_deck.clicked.connect(self._on_toggle_deck_lock)
        self._btn_reload.clicked.connect(self._on_load_data)
        self._btn_copy.clicked.connect(self._copy_to_clipboard)
        self._btn_delete_last.clicked.connect(self._on_delete_last)
        self._btn_about.clicked.connect(self._on_about)
        self._btn_open_csv.clicked.connect(self._open_csv_dir)
        self._btn_edit_config.clicked.connect(self._on_edit_config)
        self._btn_reload_config.clicked.connect(self._on_reload_config)

        # ---- 表格配置 ----
        self._stats_table.setColumnCount(len(STATS_COLUMNS))
        self._stats_table.setHorizontalHeaderLabels(STATS_COLUMNS)
        self._stats_table.horizontalHeader().setStretchLastSection(True)

        self._record_table.setColumnCount(len(RECORD_COLUMNS))
        self._record_table.setHorizontalHeaderLabels(RECORD_COLUMNS)
        self._record_table.setColumnHidden(0, True)  # 序号列不出现在界面中
        self._record_table.horizontalHeader().setStretchLastSection(True)

        # ---- 记录表格列委托（下拉菜单） ----
        # 赢硬币 (列 5): 是/否 下拉
        self._record_table.setItemDelegateForColumn(
            5, ComboDelegate(["是", "否"], self._record_table)
        )
        # 先后攻 (列 6): 先攻/后攻 下拉
        self._record_table.setItemDelegateForColumn(
            6, ComboDelegate(["先攻", "后攻"], self._record_table)
        )
        # 结果 (列 7): 胜/负 下拉
        self._record_table.setItemDelegateForColumn(
            7, ComboDelegate(["胜", "负"], self._record_table)
        )
        # 对方卡组 (列 4): 可编辑下拉 — 预设值来自 config.toml
        opponent_presets: list[str] = self._config.get(
            "opponent_decks", {}
        ).get("presets", [])
        self._record_table.setItemDelegateForColumn(
            4, EditableComboDelegate(opponent_presets, self._record_table)
        )

        # ---- 记录表格编辑 → CSV 同步 ----
        self._record_table.cellChanged.connect(self._on_record_cell_changed)

        # QSplitter 拉伸比例（统计表格 2 : 记录表格 3）
        self._splitter.setStretchFactor(0, 2)
        self._splitter.setStretchFactor(1, 3)

        # ---- 状态栏 ----
        self._status_bar = QStatusBar()
        self._status_bar.showMessage("就绪 — 请点击《启动》开始")
        # 右下角信息标签（与状态消息同行，靠右显示）
        self._info_label = QLabel()
        self._status_bar.addPermanentWidget(self._info_label)
        self.setStatusBar(self._status_bar)

        # ---- 右下角信息标签定时刷新 ----
        info_timer = QTimer(self)
        info_timer.timeout.connect(self._update_info_label)  # type: ignore[reportUnknownMemberType]
        info_timer.start(2000)
        self._info_timer = info_timer
        # 首次更新延迟到窗口显示后，避免 EnumWindows 阻塞界面出现
        QTimer.singleShot(200, self._update_info_label)

        # ---- 初始加载 CSV 数据并填充表格 ----
        self._reload_tables()
        self._restore_column_widths()

    # =========================================================================
    # 底部按钮状态管理
    # =========================================================================

    def _disable_bottom_buttons(self) -> None:
        """运行时禁用高风险按钮，只读操作和带确认弹窗的按钮不管。"""
        self._btn_edit_config.setEnabled(False)
        self._btn_reload_config.setEnabled(False)

    def _enable_bottom_buttons(self) -> None:
        """恢复底部按钮的可用状态。"""
        self._btn_edit_config.setEnabled(True)
        self._btn_reload_config.setEnabled(True)

    def _on_load_data(self) -> None:
        """弹出文件对话框切换活跃 CSV 文件，运行时需确认。

        选择后切换活跃文件并刷新表格，后续记录写入所选文件。
        """
        # 运行时切换 CSV 需确认，避免当前对局的记录写入错误文件
        if self._worker is not None:
            msg = QMessageBox(self)
            msg.setWindowTitle("切换数据文件")
            msg.setText("识别正在运行，切换数据文件可能导致\n当前对局记录写入错误的文件。\n\n确定要切换吗？")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg.setDefaultButton(QMessageBox.StandardButton.No)
            msg.button(QMessageBox.StandardButton.Yes).setText("是")
            msg.button(QMessageBox.StandardButton.No).setText("否")
            if msg.exec() != QMessageBox.StandardButton.Yes:
                return

        csv_dir = str(get_active_csv_path().parent.resolve())  # type: ignore[reportUnknownMemberType]
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 CSV 数据文件",
            csv_dir,
            "CSV 文件 (*.csv);;所有文件 (*)",
        )
        if not path:
            return
        filename = Path(path).name
        set_active_csv(filename)  # type: ignore[reportUnknownMemberType]
        self._reload_tables()
        self._status_bar.showMessage(f"已加载: {filename}")

    # =========================================================================
    # 启动 / 停止
    # =========================================================================

    def _on_start(self) -> None:
        """点击"启动"按钮: 检测 Master Duel 窗口，必要时启动游戏并等待。

        流程:
            1. 如果正在等待 Master Duel 启动 → 取消等待（"终止等待"）
            2. 如果 Master Duel 窗口已存在 → 直接启动识别
            3. 如果不存在 → 弹窗询问（中文 是/否）
               - 选"否" → 取消
               - 选"是" → 启动游戏，按钮变为"终止等待"，开始轮询窗口
            4. 轮询检测到窗口出现 → 自动进入识别流程
        """
        # ---- 正在等待中，用户点击"终止等待" ----
        if self._wait_timer is not None:
            self._cancel_wait()
            self._status_bar.showMessage("已取消等待 — 请先启动 Master Duel")
            return

        # ---- 窗口已存在，直接启动识别 ----
        if is_window_open("masterduel"):  # type: ignore[reportUnknownMemberType]
            self._start_worker()
            return

        # ---- 窗口不存在，弹窗询问 ----
        msg = QMessageBox(self)
        msg.setWindowTitle("Master Duel 未运行")
        msg.setText("未检测到 Master Duel 窗口。\n\n是否启动 Master Duel？")
        msg.setIcon(QMessageBox.Icon.Question)
        btn_yes = msg.addButton("是", QMessageBox.ButtonRole.YesRole)
        msg.addButton("否", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_yes)
        msg.exec()

        if msg.clickedButton() != btn_yes:
            self._status_bar.showMessage("已取消 — 请先启动 Master Duel")
            return

        # ---- 用户选择启动游戏 ----
        os.startfile("steam://rungameid/1449850")
        self._status_bar.showMessage("正在等待 Master Duel 启动…")

        # 将启动按钮改为"终止等待"
        self._btn_start.setText("终止等待")
        self._btn_start.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; "
            "font-weight: bold; padding: 6px 20px; }"
        )
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._disable_bottom_buttons()

        # 启动定时器，每 2 秒检测一次窗口
        timer = QTimer(self)
        timer.timeout.connect(self._on_wait_tick)  # type: ignore[reportUnknownMemberType]
        timer.start(2000)
        self._wait_timer = timer

    def _on_wait_tick(self) -> None:
        """轮询检测 Master Duel 窗口是否出现。"""
        if is_window_open("masterduel"):  # type: ignore[reportUnknownMemberType]
            self._cancel_wait()
            self._start_worker()
        else:
            self._status_bar.showMessage("正在等待 Master Duel 启动…")

    def _cancel_wait(self) -> None:
        """停止等待定时器，恢复启动按钮的原始状态。"""
        if self._wait_timer is not None:
            self._wait_timer.stop()
            self._wait_timer = None
        self._btn_start.setText("启动")
        self._btn_start.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 6px 20px; }"
            "QPushButton:disabled { background-color: #9E9E9E; }"
        )
        self._enable_bottom_buttons()

    def _start_worker(self) -> None:
        """创建并启动后台识别工作线程。"""
        self._worker = StatsWorker()

        self._worker.status_update.connect(self._on_status)           # type: ignore[reportUnknownMemberType]
        self._worker.coin_win_detected.connect(self._on_coin_win_detected)  # type: ignore[reportUnknownMemberType]
        self._worker.turn_detected.connect(self._on_turn_detected)          # type: ignore[reportUnknownMemberType]
        self._worker.result_detected.connect(self._on_result_detected)      # type: ignore[reportUnknownMemberType]
        # 线程正常退出后自动清理引用，避免 QThread 被 GC 时仍在运行
        self._worker.finished.connect(  # type: ignore[reportUnknownMemberType]
            lambda: setattr(self, "_worker", None)
        )

        self._worker.start()  # type: ignore[reportUnknownMemberType]

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lock_deck()
        self._disable_bottom_buttons()

    def _on_stop(self) -> None:
        """点击"停止"按钮: 停止并清理后台识别线程。

        执行步骤:
            1. 调用 worker.stop() 设置 _running = False
            2. 调用 worker.wait(2000) 等待线程退出（最多 2 秒）
            3. 释放 worker 引用
            4. 恢复按钮和输入框状态
        """
        if self._worker is not None:
            self._worker.stop()   # type: ignore[reportUnknownMemberType]
            self._worker.wait(2000)  # type: ignore[reportUnknownMemberType]
            # _worker 引用由 finished 信号自动清理

        self._reset_stage()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._unlock_deck()
        self._enable_bottom_buttons()

    # =========================================================================
    # 识别回调（由 StatsWorker 的信号触发，在主线程中执行）
    # =========================================================================

    def _on_status(self, msg: str) -> None:
        """接收后台线程的状态更新消息，显示在状态栏。

        特殊处理：如果消息表明 Master Duel 已关闭，自动恢复按钮状态。
        """
        self._status_bar.showMessage(msg)
        if msg.startswith("程序已关闭"):
            self._btn_start.setEnabled(True)
            self._btn_stop.setEnabled(False)
            self._unlock_deck()
            self._enable_bottom_buttons()

    def _on_coin_win_detected(self, coin_win: str) -> None:
        """阶段 1 回调：自动识别到硬币结果，缓存并同步手动按钮。

        仅当手动尚未抢先选择时生效。

        Args:
            coin_win: 'win' 或 'lose'，来自 StatsWorker.coin_win_detected 信号。
        """
        if self._stage != 0:
            return
        self._coin_cache = coin_win
        self._stage = 1
        self._update_manual_buttons()
        coin_text = "赢硬币" if coin_win == "win" else "输硬币"
        self._status_bar.showMessage(f"已识别: {coin_text} — 等待先后攻…")

    def _on_turn_detected(self, turn: str) -> None:
        """阶段 2 回调：自动识别到先后攻，缓存并同步手动按钮。

        同时捕获当前卡组名，防止后续修改导致错配。

        Args:
            turn: 'first' 或 'second'，来自 StatsWorker.turn_detected 信号。
        """
        if self._stage != 1:
            return
        self._turn_cache = turn
        self._stage = 2
        self._update_manual_buttons()
        turn_text = "先攻" if turn == "first" else "后攻"
        self._status_bar.showMessage(f"已识别: {turn_text} — 等待胜负…")

    def _on_result_detected(self, result: str) -> None:
        """阶段 3 回调：自动识别到胜负，取统一缓存写入 CSV。

        Args:
            result: 'win' 或 'lose'，来自 StatsWorker.result_detected 信号。
        """
        if self._stage != 2:
            return
        add_record(coin_win=self._coin_cache, turn=self._turn_cache, result=result, deck=self._deck_input.text().strip())  # type: ignore[reportUnknownMemberType]
        self._reset_stage()
        self._reload_tables()
        result_text = "胜" if result == "win" else "负"
        self._status_bar.showMessage(f"已记录: {result_text} — 等待下一局…")

    # =========================================================================
    # 卡组输入锁定
    # =========================================================================

    def _lock_deck(self) -> None:
        """锁定卡组输入框（运行时默认状态）。"""
        self._deck_input.setEnabled(False)
        self._btn_lock_deck.setText("修改卡组")

    def _unlock_deck(self) -> None:
        """解锁卡组输入框（停止时恢复）。"""
        self._deck_input.setEnabled(True)
        self._btn_lock_deck.setText("修改卡组")

    def _on_toggle_deck_lock(self) -> None:
        """切换卡组输入框的锁定状态。"""
        if self._deck_input.isEnabled():
            self._deck_input.setEnabled(False)
            self._btn_lock_deck.setText("修改卡组")
            self._status_bar.showMessage("卡组名已锁定")
        else:
            self._deck_input.setEnabled(True)
            self._btn_lock_deck.setText("锁定卡组")
            self._status_bar.showMessage("卡组名已解锁 — 修改后请锁定")

    # =========================================================================
    # 手动添加记录（三步向导：赢硬币 → 先后攻 → 胜负）
    # =========================================================================

    def _manual_step_clicked(self, side: str) -> None:
        """手动录入对局，两个按钮复用为每步的两个选项。

        按钮的 lambda 连接固定传 'win'（左按钮）或 'lose'（右按钮），
        根据当前统一的 _stage 状态决定 side 的语义:

            _stage==0 (硬币):   'win'→赢硬币,  'lose'→输硬币
            _stage==1 (先后攻): 'win'→先攻,    'lose'→后攻
            _stage==2 (胜负):   'win'→胜,      'lose'→负

        每次操作后同步 worker 状态，实现手动→自动联动。
        """
        if self._stage == 0:
            self._coin_cache = side
            self._stage = 1
            self._update_manual_buttons()
            self._sync_worker_stage()
            coin_text = "赢硬币" if side == "win" else "输硬币"
            self._status_bar.showMessage(f"手动: {coin_text} — 请选择先后攻")

        elif self._stage == 1:
            turn = "first" if side == "win" else "second"
            self._turn_cache = turn
            self._stage = 2
            self._update_manual_buttons()
            self._sync_worker_stage()
            turn_text = "先攻" if turn == "first" else "后攻"
            self._status_bar.showMessage(f"手动: {turn_text} — 请选择胜负")

        elif self._stage == 2:
            add_record(coin_win=self._coin_cache, turn=self._turn_cache, result=side, deck=self._deck_input.text().strip())  # type: ignore[reportUnknownMemberType]
            self._reset_stage()
            self._sync_worker_stage()
            self._reload_tables()
            result_text = "胜" if side == "win" else "负"
            self._status_bar.showMessage(f"手动添加: {result_text} — 已写入 CSV")

    def _on_undo(self) -> None:
        """撤销上一阶段的选择，逐级回退并同步 worker。"""
        if self._stage == 1:
            self._coin_cache = ""
            self._stage = 0
        elif self._stage == 2:
            self._turn_cache = ""
            self._stage = 1
        self._update_manual_buttons()
        self._sync_worker_stage()
        label = {0: "硬币", 1: "先后攻"}[self._stage]
        self._status_bar.showMessage(f"已撤销到: {label}")

    def _sync_worker_stage(self) -> None:
        """将当前 _stage 同步到后台工作线程的状态机。"""
        if self._worker is not None:
            self._worker.jump_to(self._stage)  # type: ignore[reportUnknownMemberType]

    def _reset_stage(self) -> None:
        """重置所有阶段到初始状态。"""
        self._stage = 0
        self._coin_cache = ""
        self._turn_cache = ""
        self._update_manual_buttons()

    def _update_manual_buttons(self) -> None:
        """根据当前 _stage 更新手动按钮的文本、颜色及撤销按钮可见性。

        按钮样式随阶段变化:
            _stage==0 (硬币):  #FF9800 橙色 — 左=赢硬币, 右=输硬币, 撤销隐藏
            _stage==1 (先后攻): #2196F3 蓝色 — 左=先攻, 右=后攻, 撤销可见
            _stage==2 (胜负):   #4CAF50 绿色 / #F44336 红色 — 左=胜, 右=负, 撤销可见
        """
        if self._stage == 0:
            left_text, right_text = "赢硬币", "输硬币"
            left_color = right_color = "#FF9800"
            self._btn_undo.setVisible(False)
        elif self._stage == 1:
            left_text, right_text = "先攻", "后攻"
            left_color = right_color = "#2196F3"
            self._btn_undo.setVisible(True)
        else:
            left_text, right_text = "胜", "负"
            left_color, right_color = "#4CAF50", "#F44336"
            self._btn_undo.setVisible(True)

        self._btn_manual_win.setText(left_text)
        self._btn_manual_win.setStyleSheet(
            f"QPushButton {{ background-color: {left_color}; color: white; "
            f"font-weight: bold; padding: 4px 12px; }}"
        )
        self._btn_manual_lose.setText(right_text)
        self._btn_manual_lose.setStyleSheet(
            f"QPushButton {{ background-color: {right_color}; color: white; "
            f"font-weight: bold; padding: 4px 12px; }}"
        )

    # =========================================================================
    # 表格刷新
    # =========================================================================

    def _reload_tables(self) -> None:
        """重新加载 CSV 数据并刷新两个表格。"""
        self._refresh_stats_table()
        self._refresh_record_table()

    def _refresh_stats_table(self) -> None:
        """刷新统计表格（上方表格）。

        数据来源: load_records() → compute_stats() → 逐行填充到 QTableWidget
        渲染规则: 所有单元格居中、"合计"行粗体、胜/负列上色。
        """
        records = load_records()  # type: ignore[reportUnknownMemberType]
        stats = compute_stats(records)  # type: ignore[reportUnknownMemberType]

        win_color = self._config.get("table", {}).get("win_color", "#4CAF50")
        lose_color = self._config.get("table", {}).get("lose_color", "#F44336")

        self._stats_table.setRowCount(len(stats))
        for row_idx, row_data in enumerate(stats):
            for col_idx, col_name in enumerate(STATS_COLUMNS):
                value = row_data.get(col_name, "")
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if row_data.get("卡组") == "合计":
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)

                if col_name == "胜":
                    item.setForeground(QColor(win_color))
                elif col_name == "负":
                    item.setForeground(QColor(lose_color))

                self._stats_table.setItem(row_idx, col_idx, item)

        # 列宽仅首次计算，后续刷新保持稳定

    def _refresh_record_table(self) -> None:
        """刷新记录表格（下方表格），最新记录显示在最前面。

        从 CSV 读取所有记录后倒序填充到 QTableWidget，
        刷新后自动滚动到最顶部（最新记录）。
        """
        # 阻止 cellChanged 信号在刷新时写回 CSV
        self._suppress_cell_changed = True

        records = load_records()  # type: ignore[reportUnknownMemberType]
        self._record_table.setRowCount(len(records))
        for row_idx, rec in enumerate(reversed(records)):
            for col_idx, col_name in enumerate(RECORD_COLUMNS):
                value = rec.get(col_name, "")
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # 序号/日期/时间 (列 0-2) 禁止编辑
                if col_idx in (0, 1, 2):
                    item.setFlags(
                        item.flags() & ~Qt.ItemFlag.ItemIsEditable
                    )

                self._record_table.setItem(row_idx, col_idx, item)

        # 列宽仅首次计算，后续刷新保持稳定
        if records:
            self._record_table.scrollToTop()

        self._suppress_cell_changed = False

    def _on_record_cell_changed(self, row: int, col: int) -> None:
        """用户在记录表格中编辑了单元格 → 将修改同步写回 CSV。

        通过"序号"列（列 0）定位被编辑的记录在 CSV 中的位置，
        读取修改后的值，更新记录并全量写回 CSV，最后刷新统计表格。

        参数 row/col 由 Qt 的 cellChanged 信号自动传入。
        """
        if self._suppress_cell_changed:
            return

        # 序号/日期/时间 不可编辑，但此处做安全检查
        if col in (0, 1, 2):
            return

        item = self._record_table.item(row, col)
        if item is None:
            return
        new_value = item.text().strip()

        # 通过序号定位记录
        seq_item = self._record_table.item(row, 0)
        if seq_item is None:
            return
        seq = seq_item.text().strip()

        records = load_records()  # type: ignore[reportUnknownMemberType]
        col_name = RECORD_COLUMNS[col]

        updated = False
        for rec in records:
            if rec.get("序号") == seq:
                if rec.get(col_name) != new_value:
                    rec[col_name] = new_value
                    updated = True
                break

        if updated:
            save_records(records)  # type: ignore[reportUnknownMemberType]
            self._refresh_stats_table()

    # =========================================================================
    # 删除最后记录
    # =========================================================================

    def _on_delete_last(self) -> None:
        """删除最后一条对战记录，需用户确认。

        确认后加载 CSV、删除最后一条、写回、刷新表格。
        记录为空时静默忽略。
        """
        records = load_records()  # type: ignore[reportUnknownMemberType]
        if not records:
            self._status_bar.showMessage("没有记录可删除")
            return

        last = records[-1]
        deck = last.get("使用卡组", "")
        result = last.get("结果", "")
        coin = "赢硬币" if last.get("赢硬币") == "是" else "输硬币"
        detail = f"{deck} / {coin} / {result}" if deck else f"{coin} / {result}"

        msg = QMessageBox(self)
        msg.setWindowTitle("确认删除")
        msg.setText(f"确定要删除最后一条记录吗？\n\n{detail}")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.button(QMessageBox.StandardButton.Yes).setText("是")
        msg.button(QMessageBox.StandardButton.No).setText("否")

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        records.pop()
        save_records(records)  # type: ignore[reportUnknownMemberType]
        self._reload_tables()
        self._status_bar.showMessage(f"已删除最后记录: {detail}")

    # =========================================================================
    # 关于
    # =========================================================================

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 MD Stats",
            "MD Stats\n\n"
            "版本: 1.1.0\n"
            "作者: learbox\n"
            "协议: MIT\n\n"
            "基于 OpenCV + PySide6\n"
            "Master Duel 对局自动统计工具",
        )

    # =========================================================================
    # 复制 / 打开
    # =========================================================================

    def _copy_to_clipboard(self) -> None:
        """将统计表格以 TSV 格式复制到系统剪贴板，可直接粘贴到 Excel。"""
        records = load_records()  # type: ignore[reportUnknownMemberType]
        stats = compute_stats(records)  # type: ignore[reportUnknownMemberType]

        lines = ["\t".join(STATS_COLUMNS)]
        for row in stats:
            lines.append("\t".join(str(row.get(c, "")) for c in STATS_COLUMNS))

        QApplication.clipboard().setText("\n".join(lines))
        self._status_bar.showMessage("已复制统计表格到剪贴板")

    @staticmethod
    def _open_csv_dir() -> None:
        """在文件资源管理器中打开活跃 CSV 文件所在的目录。

        跨平台: Windows 使用 os.startfile()，Linux/macOS 使用 xdg-open。
        出错时静默失败。
        """
        csv_dir = str(get_active_csv_path().parent.resolve())  # type: ignore[reportUnknownMemberType]
        try:
            if os.name == "nt":
                os.startfile(csv_dir)
            else:
                subprocess.Popen(["xdg-open", csv_dir])
        except OSError:
            pass

    def _on_edit_config(self) -> None:
        """用操作系统默认程序打开 config.toml 文件。"""
        config_path = str(_CONFIG_PATH.resolve())
        try:
            os.startfile(config_path)
        except OSError:
            self._status_bar.showMessage(f"无法打开配置文件: {config_path}")

    def _on_reload_config(self) -> None:
        """重新加载 config.toml，如果 Worker 正在运行则自动重启。

        这样用户修改截图间隔、匹配度阈值等配置后无需手动重启程序。
        """
        self._config = load_config()  # type: ignore[reportUnknownMemberType]
        init_active_csv_from_config()  # type: ignore[reportUnknownMemberType]
        self._update_info_label()

        # 如果 Worker 正在运行，停止后用新配置重启
        worker_was_running = self._worker is not None
        if worker_was_running:
            self._worker.stop()   # type: ignore[reportUnknownMemberType]
            self._worker.wait(2000)  # type: ignore[reportUnknownMemberType]
            self._start_worker()

        self._status_bar.showMessage(
            "配置已重新载入" + (" 并重启识别" if worker_was_running else "")
        )

    # =========================================================================
    # 窗口关闭事件
    # =========================================================================

    # =========================================================================
    # 右下角信息标签
    # =========================================================================

    def _update_info_label(self) -> None:
        """更新右下角的信息显示：截图间隔、阈值、Master Duel 窗口尺寸。"""
        interval = self._config.get("detection", {}).get("interval", 0.5)
        threshold = self._config.get("detection", {}).get("confidence_threshold", 0.8)

        size_info: str
        _hwnd, size, is_min = get_window_status("masterduel")  # type: ignore[reportUnknownMemberType]
        if _hwnd is None:
            size_info = "未启动"
        elif is_min:
            size_info = "窗口最小化"
        else:
            w, h = size  # type: ignore[misc]
            size_info = f"{w}×{h}"

        csv_name = get_active_csv_path().name  # type: ignore[reportUnknownMemberType]

        text = (
            f"数据: {csv_name} | "
            f"间隔: {interval}s | 阈值: {threshold} | "
            f"Master Duel: {size_info}"
        )
        self._info_label.setText(text)

    # =========================================================================
    # 列宽持久化
    # =========================================================================

    # 列宽默认值，首次运行时使用；用户调整后会被 .column_widths.json 覆盖
    _DEFAULT_COLUMN_WIDTHS = {
        "stats":    [70, 40, 25, 25, 50, 75, 75, 70, 70, 60, 60, 50, 50, 70, 70],
        "record":   [ 0, 78, 65, 64, 62, 50, 47, 39, 466],
    }

    def _restore_column_widths(self) -> None:
        """从 .column_widths.json 恢复上次列宽，首次运行使用默认值。"""
        try:
            with open(_COLUMN_WIDTHS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            saved = {}

        for table, widths, default in [
            (self._stats_table, saved.get("stats", []), self._DEFAULT_COLUMN_WIDTHS["stats"]),
            (self._record_table, saved.get("record", []), self._DEFAULT_COLUMN_WIDTHS["record"]),
        ]:
            w = widths if widths and len(widths) == table.columnCount() else default
            for col, val in enumerate(w):
                table.setColumnWidth(col, val)

    def _save_column_widths(self) -> None:
        """将当前表格列宽写入 .column_widths.json。"""
        data = {
            "stats": [
                self._stats_table.columnWidth(c)
                for c in range(self._stats_table.columnCount())
            ],
            "record": [
                self._record_table.columnWidth(c)
                for c in range(self._record_table.columnCount())
            ],
        }
        with open(_COLUMN_WIDTHS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # =========================================================================
    # 窗口关闭事件
    # =========================================================================

    def closeEvent(self, event: Any) -> None:
        """窗口关闭时保存列宽、安全停止后台工作线程和所有定时器。"""
        self._save_column_widths()
        if self._info_timer is not None:
            self._info_timer.stop()
            self._info_timer = None
        if self._wait_timer is not None:
            self._wait_timer.stop()
            self._wait_timer = None
        if self._worker is not None:
            self._worker.stop()   # type: ignore[reportUnknownMemberType]
            self._worker.wait(3000)  # type: ignore[reportUnknownMemberType]
        event.accept()
