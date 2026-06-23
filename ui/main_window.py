"""主窗口 GUI — 统计表格、记录表格、控制按钮的完整界面。

================================================================================
界面布局
================================================================================

┌──────────────────────────────────────────────────────────────────────────┐
│  [icon] MD Stats                                                 [─] [×] │  ← 标题栏
├──────────────────────────────────────────────────────────────────────────┤
│  [启动] [停止]  使用卡组: [________] [修改卡组] [赢硬币] [输硬币] [撤销] [锁定卡组] [详细统计] │
├──────────────────────────────────────────────────────────────────────────┤
│  卡组 │ 对局数 │ 胜 │ 负 │ 胜率 │ 赢硬币次数 │ ...                        │  ← 统计表格
│  炎兽 │  15   │ 10 │  5 │66.7%│    8      │ ...                        │    (上方)
│  合计 │  23   │ 14 │  9 │60.9%│   10      │ ...                        │
├──────────────────────────────────────────────────────────────────────────┤
│  日期 │ 时间 │ 卡组 │ 己方段位 │ 对方卡组 │ 对方段位 │ 赢硬币 │ 先后攻 │ … │  ← 记录表格
│  ...  │ ...  │ 炎兽 │ 铂金 IV  │  闪刀姬  │ 黄金 I   │  是   │ 先攻  │ … │    (下方)
├──────────────────────────────────────────────────────────────────────────┤
│  [加载数据] [复制统计] [打开 data.csv 目录] [删除最后记录] [悬浮窗] [设置] [关于] │  ← 底部按钮
├──────────────────────────────────────────────────────────────────────────┤
│  段位: 铂金 IV vs 黄金 I                       📁 data.csv               │  ← 状态栏
└──────────────────────────────────────────────────────────────────────────┘

================================================================================
信号连接 (Signal-Slot 关系)
================================================================================

    StatsWorker (子线程)           MainWindow (主线程)
    ─────────────────────        ─────────────────────
    status_update    ──────────→ _on_status()           → 更新状态栏文字
    coin_win_detected ────────→ _on_coin_win_detected() → 缓存硬币输赢结果
    rank_detected     ────────→ _on_rank_detected()     → 缓存升段/降段
    turn_detected     ────────→ _on_turn_detected()     → 缓存先后攻
    result_detected   ────────→ _on_result_detected()   → 写 CSV，通知段位线程

    RankWorker (独立线程)       MainWindow (主线程)
    ─────────────────────        ─────────────────────
    rank_icon_detected ────────→ _on_rank_icon_detected()→ 缓存段位图标结果

    GUI 按钮                 →  直接调用对应方法（主线程中执行）
    [启动]                  →  _on_start()             → 创建检测线程并启动
    [停止]                  →  _on_stop()              → 停止并销毁检测线程
    [赢硬币] [输硬币] [撤销]  →  _manual_step_clicked()  → 手动录入（与自动联动）
                                _on_undo()              → 逐级回退阶段
    [锁定卡组]              →  _on_toggle_deck_lock()  → 锁定/解锁卡组输入框
    [详细统计]              →  _open_rank_stats()      → 弹窗按卡组+段位筛选统计
    [加载数据]                  →  _on_load_data()         → 打开文件对话框切换 CSV
    [复制统计]                  →  _copy_to_clipboard()    → 复制统计表格 TSV
    [打开 data.csv 目录]               →  _open_csv_dir()         → 打开文件资源管理器
    [删除最后记录]              →  _on_delete_last()       → 确认后删除最后一条记录
    [悬浮窗]                →  _on_toggle_float()      → 开关悬浮统计窗
    [设置]                  →  _on_settings()          → 图形化配置编辑器
    [关于]                  →  _on_about()             → 弹窗显示程序信息

================================================================================
数据流
================================================================================

    CSV 文件 (csv/data.csv)
         │
         ├── load_records() ──→ compute_stats() ──→ _refresh_stats_table()
         │                                           (刷新统计表格 + 悬浮窗)
         │
         └── load_records() ───────────────────────→ _refresh_record_table()
                                                      (刷新记录表格)

================================================================================
三阶段状态机（手动/自动共用）
================================================================================

无论是自动识别还是手动录入，都使用统一的三阶段状态机:

    _stage == 0 → 等待硬币 (赢硬币/输硬币)
    _stage == 1 → 等待先后攻 (先攻/后攻)
    _stage == 2 → 等待胜负 (胜/负)

手动按钮的文字和颜色随 _stage 变化，自动识别通过 worker.jump_to()
同步状态。手动录入后自动识别从新状态继续，互不冲突。
"""


import ctypes
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QMenu,
    QSystemTrayIcon,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QToolButton,
    QWidget,
    QTableWidgetItem,
)

from src.app_state import read_app_state, write_app_state, parse_pos, APP_STATE_DEFAULTS
from src.config import get_project_root, load_config
from src.match_state import MatchState
from src.snapshot_controller import SnapshotController
from src import logger as _log
from src.recorder import (
    add_record,
    clear_pending,
    COLUMNS as RECORD_COLUMNS,
    compute_stats,
    get_active_csv_path,
    get_pending_count,
    init_active_csv_from_config,
    load_records,
    save_records,
    set_active_csv,
    STATS_COLUMNS,
    try_flush_pending,
)
# capture / stats_worker 延迟导入（启动时才需要 OpenCV，避免程序启动等待 ~260ms）
from src.theme_loader import Theme, load_theme
from ui.floating_window import FloatingWindow, _ROW_KEY_MAP
from ui.theme_manager import ThemeManager, ThemeWidgets
from ui.titlebar import TitleBar

_RESOURCE_DIR = get_project_root() / "resource"

_T = TypeVar("_T")


# =============================================================================
# _setup_combo_editor — QComboBox 表格编辑器公共初始化
# =============================================================================

def _setup_combo_editor(combo: QComboBox) -> None:
    """QComboBox 表格编辑器公共初始化：调色板覆盖 + 不透明背景。

    在 QTableWidget 中，QComboBox 编辑器是 viewport 的子控件。
    viewport 的 QPalette 被设为透明（以便 QSS 背景色正常显示），
    QComboBox 会继承这个透明调色板，导致两个问题：

        1. 弹出列表背景变黑 — 因为 QPalette 的 Base 是透明黑(0,0,0,0)
        2. 半透明主题下原文字透出 — 如 macaron 的 combo_body_bg 是 rgba

    解决方案：
        - 用 QApplication 的全局调色板覆盖继承的透明调色板
        - 用局部 QSS 设不透明背景色（取自 QPalette.Base），防止文字透出
    """
    combo.view().setFrameShape(QFrame.Shape.NoFrame)    # 去掉列表外框
    pal = QApplication.palette()                         # 取全局调色板（ThemeManager 已设好）
    combo.setPalette(pal)                                # QComboBox 本体用全局调色板
    combo.view().setPalette(pal)                         # 弹出列表也继承全局调色板
    bg = pal.color(QPalette.ColorRole.Base).name()       # 取 Base 色（widget_bg，不透明白色）
    combo.setStyleSheet(f"QComboBox {{ background-color: {bg}; }}")  # 覆盖半透明背景


# =============================================================================
# ComboDelegate — 固定选项下拉委托（赢硬币/先后攻/结果列）
# =============================================================================

class ComboDelegate(QStyledItemDelegate):
    """固定选项的下拉菜单委托。

    用于赢硬币（是/否）、先后攻（先攻/后攻）、结果（胜/负）三列。
    点击单元格 → QComboBox 弹出 → 用户选择 → 立即提交数据并关闭编辑器。

    QStyledItemDelegate 是 Qt 的"自定义编辑器"机制：
        createEditor()  — 创建编辑器控件（QComboBox）
        setEditorData() — 把单元格当前值填入编辑器
        setModelData()  — 把编辑器的新值写回表格模型
    """

    def __init__(self, items: list[str], parent: QTableWidget | None = None,
                 editable: bool = False) -> None:
        """初始化委托。

        参数:
            items    — 下拉选项列表，如 ["是", "否"]
            parent   — 所属的 QTableWidget（用于生命周期管理）
            editable — 是否允许用户自由输入（默认否）。用于段位升降等
                       需要"留空"的列：下拉选"升段/降段"，也可清空表示普通局。
        """
        super().__init__(parent)
        self._items = items
        self._editable = editable

    def createEditor(self, parent_widget, _option, _index) -> QComboBox:
        """创建编辑器：一个非可编辑的 QComboBox。

        setMaxVisibleItems(len(items)) — 弹出列表只预留足够显示所有选项的高度，
                                         避免默认 maxVisibleItems=10 导致大量留白。
        activated 信号 — 仅在用户从弹出列表中选择时触发，不会在 setEditorData 中误触发。
        commitData + closeEditor — 选择后立即提交数据并关闭编辑器（无需额外点击）。
        """
        combo = QComboBox(parent_widget)
        combo.addItems(self._items)
        combo.setEditable(self._editable)                # 可编辑模式：允许清空文本
        combo.setMaxVisibleItems(len(self._items))      # 弹出列表紧凑，不留白
        _setup_combo_editor(combo)                       # 公共初始化（调色板+不透明背景）
        combo.activated.connect(
            lambda _idx: self.commitData.emit(combo)     # 选择后提交数据
        )
        combo.activated.connect(
            lambda _idx: self.closeEditor.emit(combo)    # 选择后关闭编辑器
        )
        return combo

    def setEditorData(self, editor: QComboBox, index) -> None:
        """把单元格当前值填入编辑器。如果值不在选项中，默认选第一个。"""
        value = index.data(Qt.ItemDataRole.EditRole)     # 取单元格当前值
        if value in self._items:
            editor.setCurrentText(value)
        elif self._items:
            editor.setCurrentIndex(0)                    # 兜底：选第一个选项

    def setModelData(self, editor: QComboBox, model, index) -> None:
        """把编辑器选择的值写回表格模型。"""
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


# =============================================================================
# EditableComboDelegate — 可编辑下拉委托（对方卡组列）
# =============================================================================

class EditableComboDelegate(QStyledItemDelegate):
    """可编辑的下拉菜单委托。

    用于"对方卡组"列。用户既可以从预设列表选择，也可以自由输入任何文字。
    与 ComboDelegate 的关键区别：setEditable(True) 启用了 QLineEdit 子控件，
    用户可以自由输入，同时下拉列表仍提供预设选项快速选择。
    """

    def __init__(self, items: list[str], parent: QTableWidget | None = None) -> None:
        """初始化可编辑下拉委托。

        Args:
            items: 下拉预设选项列表（如对方卡组预设）。
            parent: 所属的 QTableWidget（用于生命周期管理）。
        """
        super().__init__(parent)
        self._items = items

    def createEditor(self, parent_widget, _option, _index) -> QComboBox:
        """创建编辑器：一个可编辑的 QComboBox。

        setEditable(True) — 允许自由输入，QLineEdit 子控件出现
        setMaxVisibleItems(min(...), 8) — 预设列表可能很长，限制最多显示 8 项
        setCurrentText("") — 初始为空，让用户看到提示文字（placeholderText 不可用）
        """
        combo = QComboBox(parent_widget)
        combo.setEditable(True)                           # 关键：允许自由输入
        combo.addItems(self._items)
        combo.setMaxVisibleItems(min(len(self._items), 8)) # 限制弹出列表高度
        combo.setCurrentText("")                           # 空初始值
        _setup_combo_editor(combo)                         # 公共初始化
        return combo

    def setEditorData(self, editor: QComboBox, index) -> None:
        """填入单元格当前值（如果非空）。"""
        value = index.data(Qt.ItemDataRole.EditRole)
        if value:
            editor.setCurrentText(value)

    def setModelData(self, editor: QComboBox, model, index) -> None:
        """写回用户输入的文字（可能是自由输入或从列表选择）。"""
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


# =============================================================================
# _require_widget — 类型收窄工具
# =============================================================================

def _require_widget(widget: _T | None, name: str) -> _T:
    """类型收窄 findChild 的返回值，断言控件一定存在。

    Qt 的 findChild() 返回 X | None，IDE 会标记可能为 None。
    这个方法用 assert 告诉类型检查器"这里不可能为 None"。
    如果控件真的不存在（.ui 文件损坏），抛出 RuntimeError 尽早失败。
    """
    if widget is None:
        raise RuntimeError(f"UI 控件 '{name}' 未在 .ui 文件中找到")
    return widget


# =============================================================================
# MainWindow
# =============================================================================

class MainWindow(QMainWindow):
    """程序的主窗口，包含所有 GUI 元素和交互逻辑。

    继承自 QMainWindow，使用 QMainWindow 的标准布局：
        - 中心控件（setCentralWidget）→ 从 .ui 文件加载的 content
        - 无边框窗口 + 自定义标题栏 + DWM 原生阴影

    通过 Qt 的信号/槽机制与后台工作线程（StatsWorker）通信。
    """

    # =========================================================================
    # 主题相关代理方法（将调用转发给 ThemeManager）
    # =========================================================================

    def _theme_colors(self) -> dict[str, str]:
        """返回当前主题的颜色表（缓存在 ThemeManager 中）。"""
        return self._tm.colors

    def _apply_theme_pixmaps(self, pixmaps: dict[str, str]) -> None:
        """缓存主题图片路径到 ThemeManager。"""
        self._tm.pixmap_paths = pixmaps

    def _do_apply_pixmaps(self) -> None:
        """首次显示时用 QPalette 贴背景图片（showEvent 中调用）。"""
        self._tm.do_apply_pixmaps(self._theme_widgets)

    # =========================================================================
    # 基础 UI 工具方法
    # =========================================================================

    def _show_status(self, msg: str) -> None:
        """更新状态栏消息（左下角的文字）+ 同步到悬浮窗状态行。

        如果有暂存记录（CSV 文件被占用），自动在消息末尾追加警告。
        """
        pending = get_pending_count()
        if pending > 0:
            msg = f"{msg}  |  ⚠ 文件被占用，{pending} 条暂存"
        self._status_label.setText(msg)
        if self._float_window is not None:
            self._float_window.update_status(msg)

    def _ask_yes_no(self, title: str, text: str) -> bool:
        """弹出"是/否"确认对话框。

        统一使用 QMessageBox，确保所有确认弹窗外观一致。
        默认按钮为"否"，防止误操作。

        返回: True=用户选了"是"，False=选了"否"或关闭窗口。
        """
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setWindowIcon(self.windowIcon())
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)  # 默认选中"否"
        msg.button(QMessageBox.StandardButton.Yes).setText("是")
        msg.button(QMessageBox.StandardButton.No).setText("否")
        return msg.exec() == QMessageBox.StandardButton.Yes

    # =========================================================================
    # 窗口外观 — DWM 阴影 + 边缘 resize + 无边框窗口
    #
    # 程序使用无边框窗口（FramelessWindowHint），Windows 自带的标题栏消失。
    # 为了让窗口看起来仍然像原生窗口，需要自己实现三个功能:
    #   1. DWM 阴影 — 调用 Windows API 扩展窗口边框区域来渲染系统阴影
    #   2. 边缘 resize — 检测鼠标是否在窗口边缘，让系统接管 resize
    #   3. 拖拽移动 — 由 TitleBar 处理
    # =========================================================================

    def _apply_dwm_style(self) -> None:
        """调用 Windows DWM API，给无边框窗口加系统阴影 + Win11 圆角。

        DWM（Desktop Window Manager）是 Windows 的桌面合成引擎。
        DwmExtendFrameIntoClientArea: 把窗口边框区域扩展进客户区，让 DWM 渲染阴影
        DwmSetWindowAttribute: 设置 Win11 的窗口圆角属性

        仅在 Windows 上可用，非 Windows 系统静默跳过。
        """
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())  # 获取窗口句柄（HWND）

            # ---- DWM 阴影 ----
            class _MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            margins = _MARGINS(1, 1, 1, 1)  # 每边扩展 1px
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(  # type: ignore[attr-defined]
                hwnd, ctypes.byref(margins),
            )

            # ---- Win11 圆角 ----
            dwmwa_window_corner_preference = 33
            dwmwcp_round = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd, dwmwa_window_corner_preference,
                ctypes.byref(ctypes.c_int(dwmwcp_round)),
                ctypes.sizeof(ctypes.c_int),
            )
        except OSError:
            pass  # DWM 不可用时静默跳过（如远程桌面、旧版 Windows）

    # 窗口边缘 resize 检测敏感宽度（像素），鼠标进入此范围触发 resize 光标
    _BORDER_WIDTH = 6
    _resize_edge: Any = None  # 当前 resize 边缘方向

    def _edge_at(self, global_pos) -> Any:
        """检测鼠标的全局坐标是否在窗口边缘，返回 Qt.Edge 或 None。

        用窗口的 geometry()（全局坐标）和鼠标位置比较，判断鼠标是否在
        窗口的上下左右边缘或四角（同时两个方向）。

        返回的 Qt.Edge 是位标志，可以组合（如 TopEdge | LeftEdge = 左上角）。
        """
        geo = self.geometry()                         # 窗口在屏幕上的位置和大小
        bw = self._BORDER_WIDTH                       # 边缘检测宽度
        x, y = global_pos.x(), global_pos.y()         # 鼠标的屏幕坐标

        left_edge   = x < geo.x() + bw                # 左边缘
        right_edge  = x >= geo.x() + geo.width() - bw # 右边缘
        top_edge    = y < geo.y() + bw                # 上边缘
        bottom_edge = y >= geo.y() + geo.height() - bw# 下边缘

        # 四角优先（两个箭头方向组合）
        if top_edge and left_edge:
            return Qt.Edge.LeftEdge | Qt.Edge.TopEdge  # type: ignore[return-value]
        if top_edge and right_edge:
            return Qt.Edge.RightEdge | Qt.Edge.TopEdge  # type: ignore[return-value]
        if bottom_edge and left_edge:
            return Qt.Edge.LeftEdge | Qt.Edge.BottomEdge  # type: ignore[return-value]
        if bottom_edge and right_edge:
            return Qt.Edge.RightEdge | Qt.Edge.BottomEdge  # type: ignore[return-value]
        # 单边
        if top_edge:
            return Qt.Edge.TopEdge    # 上边缘: ↑
        if bottom_edge:
            return Qt.Edge.BottomEdge # 下边缘: ↓
        if left_edge:
            return Qt.Edge.LeftEdge   # 左边缘: ←
        if right_edge:
            return Qt.Edge.RightEdge  # 右边缘: →
        return None  # 不在边缘区域

    def eventFilter(self, watched, event) -> bool:
        """将子控件（content widget）的鼠标事件转发给窗口级 resize 检测。"""
        from PySide6.QtCore import QEvent
        t = event.type()
        if t == QEvent.Type.MouseMove:
            # PySide6 类型存根中 QEvent 没有 globalPosition，但 MouseEvent 有
            self._update_resize_cursor(event.globalPosition().toPoint())  # type: ignore[attr-defined]
        elif t == QEvent.Type.MouseButtonPress:
            edge = self._edge_at(event.globalPosition().toPoint())  # type: ignore[attr-defined]
            if edge and self.windowHandle():
                self.windowHandle().startSystemResize(edge)
                return True
        return False

    def _update_resize_cursor(self, global_pos) -> None:
        """根据鼠标在窗口边缘的位置更新鼠标光标形状。

        光标类型由边缘方向决定:
            左右边缘 → 水平拉伸光标 (↔)
            上下边缘 → 垂直拉伸光标 (↕)
            对角线   → 斜向拉伸光标 (↖↗)
            非边缘   → 普通箭头
        """
        edge = self._edge_at(global_pos)
        if edge == Qt.Edge.LeftEdge or edge == Qt.Edge.RightEdge:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == Qt.Edge.TopEdge or edge == Qt.Edge.BottomEdge:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge == (Qt.Edge.LeftEdge | Qt.Edge.TopEdge) or edge == (Qt.Edge.RightEdge | Qt.Edge.BottomEdge):  # type: ignore[comparison-overlap]
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge == (Qt.Edge.RightEdge | Qt.Edge.TopEdge) or edge == (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):  # type: ignore[comparison-overlap]
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        """鼠标在窗口空白边缘按下 → 启动系统 resize。"""
        edge = self._edge_at(event.globalPosition().toPoint())
        if edge and self.windowHandle():
            self.windowHandle().startSystemResize(edge)
        else:
            super().mousePressEvent(event)  # 非边缘区域，正常处理（标题栏拖拽等）

    def mouseMoveEvent(self, event) -> None:
        """鼠标移动时更新边缘光标。"""
        self._update_resize_cursor(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def enterEvent(self, event) -> None:
        """鼠标划入窗口时重置光标为默认箭头，避免 resize 光标残留。"""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开窗口时恢复默认光标。"""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """双击边缘区域不处理（仅标题栏双击可自定义，当前为空实现）。"""
        if self._edge_at(event.globalPosition().toPoint()):
            return                         # 边缘双击 = 忽略
        super().mouseDoubleClickEvent(event)

    # =========================================================================
    # 主题应用代理方法
    # =========================================================================

    def _apply_static_button_palette(self) -> None:
        """应用停止/删除按钮的静态配色。"""
        self._tm.apply_static_button_palette(self._theme_widgets)

    def _apply_theme_to_widgets(self) -> None:
        """重新应用主题到所有控件（主题切换时调用）。"""
        self._tm.apply_to_widgets(self._theme_widgets)

    def _apply_table_viewport_palette(self) -> None:
        """应用表格 viewport 的背景色。"""
        self._tm.apply_table_viewport_palette(self._theme_widgets)

    # =========================================================================
    # __init__ — 主窗口初始化
    #
    # 初始化流程（按顺序）:
    #   1. 加载 config.toml 配置
    #   2. 初始化 ThemeManager
    #   3. 加载主题 → 设置 QSS + QPalette
    #   4. 设置无边框窗口 + DWM 阴影
    #   5. 从 .ui 文件加载界面控件
    #   6. 插入自定义标题栏
    #   7. 获取所有控件引用（findChild）
    #   8. 连接信号/槽
    #   9. 配置表格（列数/标题/委托）
    #   10. 构建 ThemeWidgets 容器
    #   11. 应用表格调色板
    #   12. 延迟加载 CSV 数据
    # =========================================================================

    def __init__(self) -> None:
        """初始化主窗口。"""
        super().__init__()

        # ---- 1. 加载配置 ----
        self._config: dict[str, Any] = load_config()
        # 如果用户开启了日志模式，初始化日志系统
        # 注意：init_log 多次调用只生效第一次（日志路径不变），
        #       set_scopes 每次都会更新（支持热重载时调整记录范围）
        if self._config.get("debug", {}).get("log_mode", False):
            _log.init_log(get_project_root() / "logs")
            _log.set_scopes(set(self._config.get("debug", {}).get("log_scope", ["status", "screenshots", "errors"])))

        # ---- 1b. 初始化系统托盘（气泡通知） ----
        icon_path = get_project_root() / "resource" / "icons" / "app_icon.png"
        icon = QIcon(str(icon_path)) if icon_path.exists() else self.windowIcon()
        if icon.isNull():
            icon = QApplication.style().standardIcon(
                QApplication.style().StandardPixmap.SP_MessageBoxInformation
            )
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("MD Stats")
        self._tray.activated.connect(self._on_tray_activated)

        # 截图热键
        self._snapshot_ctrl = SnapshotController(self._config, parent=self)
        self._snapshot_ctrl.status_message.connect(self._show_status)

        # 托盘右键菜单
        tray_menu = QMenu()
        tray_menu.addAction("显示窗口", self._show_from_tray)
        tray_menu.addAction("退出程序", self._quit_app)
        self._tray.setContextMenu(tray_menu)

        self._tray.show()  # 需要先 show 才能弹出气泡

        # ---- 2. 初始化主题管理器 ----
        self._tm = ThemeManager(self._config)

        # ---- 3. 初始化活跃 CSV 文件 ----
        init_active_csv_from_config()

        # ---- 4. 运行时状态变量 ----
        self._worker: Any = None              # 后台识别线程（StatsWorker）
        self._wait_timer: QTimer | None = None# 等待游戏启动的轮询定时器
        self._info_timer: QTimer | None = None# 右下角信息标签刷新定时器
        self._match = MatchState()               # 三阶段对局状态机
        self._rank_worker: Any | None = None  # type: ignore[annotation-unchecked] — 段位图标检测线程（延迟导入）
        self._rank_icon_result: dict | None = None        # 段位图标检测结果暂存
        self._notifying = False                         # 防_result_detected重入
        # 段位图标在硬币阶段（阶段1）显示，但数据要到对局结束才写入 CSV。
        # 检测结果先存在 _rank_icon_result，对局结束时取出写入记录。
        # _rank_icon_strs() 负责提取并清除缓存（每次对局最多调用一次）。
        self._suppress_cell_changed: bool = False # 刷新记录表时抑制 cellChanged（避免误写 CSV）
        self._cols_restored: bool = False     # 列宽是否已从持久化文件恢复

        # ---- 5. 加载主题 ----
        theme: Theme = load_theme(
            self._config.get("appearance", {}).get("theme", "dark")
        )
        self._tm.colors = theme.colors
        self._tm.titlebar_cfg = theme.titlebar
        self._tm.assets_dir = theme.assets_dir
        self.setStyleSheet(theme.qss)          # 应用全局 QSS
        self._tm.apply_app_palette()           # 应用全局 QPalette
        self._apply_theme_pixmaps(theme.pixmaps)

        # ---- 6. 无边框窗口 + DWM 原生阴影 ----
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setMouseTracking(True)            # 启用鼠标跟踪（边缘 resize 需要）
        self._apply_dwm_style()

        # ---- 7. 加载界面（预编译 .ui 避免 XML 解析，比 QUiLoader 快约 70ms） ----
        # ⚠ main_window_ui.py 是 pyside6-uic 从 main_window.ui 自动编译生成，
        #   严禁手动修改。所有界面改动请在 main_window.ui (Qt Designer) 中进行，
        #   然后运行: pyside6-uic ui/main_window.ui -o ui/main_window_ui.py
        from ui.main_window_ui import Ui_MainWindow
        content = QWidget()
        ui = Ui_MainWindow()
        ui.setupUi(content)
        content.setObjectName("contentWidget") # 覆盖 setupUi 设置的 objectName
        self._content = content

        # ---- 8. 插入自定义标题栏（到 content 布局的最顶部） ----
        assets_dir = self._tm.assets_dir or (get_project_root() / "resource")
        self._title_bar = TitleBar(
            "MD Stats", self._tm.titlebar_cfg, assets_dir, self
        )
        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.close_clicked.connect(self.close)
        root_layout = content.layout()
        if root_layout is not None:
            root_layout.insertWidget(0, self._title_bar)  # type: ignore[attr-defined]

        self.setCentralWidget(content)

        # 事件过滤器: 让子控件（content widget）的鼠标事件也能触发边缘 resize
        content.setMouseTracking(True)
        content.installEventFilter(self)

        # 提前显示窗口：用 singleShot(0) 延迟到下一帧，确保 __init__ 完整执行后
        # 再显示，避免 Qt 内部线程在构造未完成时触发
        QTimer.singleShot(0, self.show)

        # ---- 9. 窗口图标 ----
        icon_path = _RESOURCE_DIR / "icons" / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ---- 10. 获取所有控件引用 ----
        # _require_widget 将 findChild 的 X | None 收窄为 X，消除类型警告
        self._btn_start        = _require_widget(content.findChild(QPushButton, "btn_start"), "btn_start")
        self._btn_stop         = _require_widget(content.findChild(QPushButton, "btn_stop"), "btn_stop")
        self._deck_input       = _require_widget(content.findChild(QLineEdit, "deck_input"), "deck_input")
        self._btn_manual_win   = _require_widget(content.findChild(QPushButton, "btn_manual_win"), "btn_manual_win")
        self._btn_manual_lose  = _require_widget(content.findChild(QPushButton, "btn_manual_lose"), "btn_manual_lose")
        self._btn_undo         = _require_widget(content.findChild(QPushButton, "btn_undo"), "btn_undo")
        self._btn_lock_deck    = _require_widget(content.findChild(QPushButton, "btn_lock_deck"), "btn_lock_deck")
        self._btn_lock_deck.setText("锁定卡组")  # 初始: 输入框未锁定
        self._btn_rank_stats   = _require_widget(content.findChild(QPushButton, "btn_rank_stats"), "btn_rank_stats")
        self._stats_table      = _require_widget(content.findChild(QTableWidget, "stats_table"), "stats_table")
        self._record_table     = _require_widget(content.findChild(QTableWidget, "record_table"), "record_table")
        self._btn_reload       = _require_widget(content.findChild(QToolButton, "btn_reload"), "btn_reload")
        self._btn_copy         = _require_widget(content.findChild(QPushButton, "btn_copy"), "btn_copy")
        self._btn_delete_last  = _require_widget(content.findChild(QToolButton, "btn_delete_last"), "btn_delete_last")
        self._btn_about        = _require_widget(content.findChild(QPushButton, "btn_about"), "btn_about")
        self._btn_open_csv     = _require_widget(content.findChild(QPushButton, "btn_open_csv"), "btn_open_csv")
        self._btn_settings = _require_widget(content.findChild(QPushButton, "btn_settings"), "btn_settings")
        self._splitter         = _require_widget(content.findChild(QSplitter, "splitter"), "splitter")

        # ---- 11. 窗口基础设置 ----
        self.resize(
            self._config.get("window", {}).get("width", 1100),
            self._config.get("window", {}).get("height", 700),
        )
        self._restore_main_window_pos()          # 恢复上次窗口位置

        # ---- 12. 信号连接 ----
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        # 手动按钮用 lambda 固定传参 'win'（左）或 'lose'（右），语义随 _stage 变化
        self._btn_manual_win.clicked.connect(lambda: self._manual_step_clicked("win"))
        self._btn_manual_lose.clicked.connect(lambda: self._manual_step_clicked("lose"))
        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_lock_deck.clicked.connect(self._on_toggle_deck_lock)
        self._btn_reload.clicked.connect(self._on_load_data)
        self._btn_rank_stats.clicked.connect(self._open_rank_stats)

        # QToolButton MenuButtonPopup 模式：左侧点击加载数据，右侧箭头弹出菜单
        reload_menu = QMenu(self._btn_reload)
        reload_menu.addAction("备份数据", self._on_backup_data)
        reload_menu.addAction("新建数据", self._on_new_data)
        self._btn_reload.setMenu(reload_menu)
        self._btn_copy.clicked.connect(self._copy_to_clipboard)
        self._btn_delete_last.clicked.connect(self._on_delete_last)

        # QToolButton MenuButtonPopup 模式：左侧点击删除最后记录，右侧箭头弹出菜单
        del_menu = QMenu(self._btn_delete_last)
        del_menu.addAction("删除全部记录", self._on_delete_all_records)
        self._btn_delete_last.setMenu(del_menu)
        self._btn_about.clicked.connect(self._on_about)
        self._btn_open_csv.clicked.connect(self._open_csv_dir)
        self._btn_settings.clicked.connect(self._on_settings)

        # ---- 13. 悬浮窗按钮 ----
        self._btn_float = _require_widget(content.findChild(QPushButton, "btn_float"), "btn_float")
        self._btn_float.clicked.connect(self._on_toggle_float)
        self._float_window: Any = None           # 悬浮窗实例（延迟创建）

        # ---- 14. 表格配置 ----
        # 统计表格: 只读，整行选中
        self._stats_table.setColumnCount(len(STATS_COLUMNS))
        self._stats_table.setHorizontalHeaderLabels(STATS_COLUMNS)
        self._stats_table.horizontalHeader().setStretchLastSection(True)  # 最后一列自动填充
        self._stats_table.verticalHeader().setDefaultSectionSize(28)      # 行高 28px

        # 记录表格: 可编辑，整行选中
        self._record_table.setColumnCount(len(RECORD_COLUMNS))
        self._record_table.setHorizontalHeaderLabels(RECORD_COLUMNS)
        self._record_table.setColumnHidden(0, True)        # 序号列不出现在界面中
        self._record_table.horizontalHeader().setStretchLastSection(True)
        self._record_table.verticalHeader().setDefaultSectionSize(28)

        # 给横/竖表头设 objectName，QSS 可以区分贴不同的背景图
        for table in (self._stats_table, self._record_table):
            table.horizontalHeader().setObjectName("horizontalHeader")
            table.verticalHeader().setObjectName("verticalHeader")

        # ---- 15. 记录表格列委托（下拉菜单） ----
        # 列7: 赢硬币 (是/否)
        self._record_table.setItemDelegateForColumn(7, ComboDelegate(["是", "否"], self._record_table))
        # 列8: 先后攻 (先攻/后攻)
        self._record_table.setItemDelegateForColumn(8, ComboDelegate(["先攻", "后攻"], self._record_table))
        # 列9: 结果 (胜/负)
        self._record_table.setItemDelegateForColumn(9, ComboDelegate(["胜", "负"], self._record_table))
        # 列10: 段位升降 (升段/降段/空白=普通局)
        self._record_table.setItemDelegateForColumn(10, ComboDelegate(["升段", "降段", ""], self._record_table))
        # 列6: 对方卡组 (可编辑下拉 — 预设值来自 config.toml)
        opponent_presets: list[str] = self._config.get("opponent_decks", {}).get("presets", [])
        self._record_table.setItemDelegateForColumn(5, EditableComboDelegate(opponent_presets, self._record_table))

        # ---- 16. 记录表格编辑 → CSV 同步 ----
        self._record_table.cellChanged.connect(self._on_record_cell_changed)

        # QSplitter 分割比例：首次运行用默认值，后续从 .app_state.toml 恢复
        self._splitter.setStretchFactor(0, 2)
        self._splitter.setStretchFactor(1, 3)
        self._splitter.setSizes(read_app_state()["splitter"])

        # ---- 17. 状态栏（从 .ui 文件加载的控件） ----
        self._status_frame = _require_widget(content.findChild(QFrame, "customStatusBar"), "customStatusBar")
        self._status_label = _require_widget(content.findChild(QLabel, "statusMessage"), "statusMessage")
        self._info_label   = _require_widget(content.findChild(QLabel, "infoLabel"), "infoLabel")

        # ---- 18. 右下角信息标签定时刷新（每2秒更新一次） ----
        info_timer = QTimer(self)
        info_timer.timeout.connect(self._update_info_label)
        info_timer.start(2000)
        self._info_timer = info_timer
        QTimer.singleShot(200, self._update_info_label)  # 首次更新延迟200ms，让窗口先渲染

        # ---- 19. 初始化手动按钮样式 ----
        self._update_manual_buttons()            # 阶段0: 橙色"赢硬币/输硬币"
        self._btn_start.setStyleSheet(            # 启动按钮单独样式（绿色，稍大）
            self._tm.make_button_style(self._theme_colors()["start_bg"], padding="6px 20px")
        )

        # ---- 20. 构建主题控件引用容器（传给 ThemeManager） ----
        self._theme_widgets = ThemeWidgets(
            stats_table=self._stats_table,
            record_table=self._record_table,
            btn_start=self._btn_start,
            btn_stop=self._btn_stop,
            btn_delete_last=self._btn_delete_last,
            btn_reload=self._btn_reload,
            title_bar=self._title_bar,
            status_frame=self._status_frame,
            content=self._content,
            refresh_stats_table=self._refresh_stats_table,
            refresh_record_table=self._refresh_record_table,
            update_manual_buttons=self._update_manual_buttons,
        )

        # ---- 21. 控件调色板（需要 _theme_widgets 构建后才能调用） ----
        self._apply_table_viewport_palette()
        self._apply_static_button_palette()

        # ---- 22. 同步加载 CSV 数据（在 __init__ 末尾直接调用，确保列宽恢复先于 show） ----
        self._reload_tables()

        # ---- 23. 若开启"记住上次卡组"，自动填入 ----
        if self._config.get("recorder", {}).get("remember_last_deck", False):
            last_deck = self._last_record_deck()
            if last_deck:
                self._deck_input.setText(last_deck)

        # 初始化完成后再注册热键（__init__ 早期 _status_label 尚未创建）
        self._snapshot_ctrl.sync_hotkeys()


    # =========================================================================
    # 底部按钮状态管理
    #
    # 运行时（Worker 正在识别）禁用"编辑配置"和"重载配置"按钮，
    # 因为修改配置可能导致当前识别出现不一致。停止后恢复。
    # =========================================================================

    def _disable_bottom_buttons(self) -> None:
        """运行时禁用高风险按钮。"""
        self._btn_settings.setEnabled(False)

    def _enable_bottom_buttons(self) -> None:
        """停止时恢复底部按钮。"""
        self._btn_settings.setEnabled(True)

    # =========================================================================
    # CSV 数据加载
    # =========================================================================

    def _check_pending_before_switch(self, action: str) -> bool:
        """切换/备份/新建前统一拦截：有暂存记录则先尝试写入。

        三选一弹窗：重试写入 / 取消操作 / 放弃暂存并继续。
        返回 True 继续操作，False 取消。
        """
        pending = get_pending_count()
        if pending == 0:
            return True
        if try_flush_pending():
            return True
        while True:
            msg = QMessageBox(self)
            msg.setWindowTitle("暂存记录无法写入")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(f"有 {pending} 条暂存记录因 CSV 被占用无法写入。")
            msg.setInformativeText("请关闭占用该文件的程序（如 WPS、Excel），\n然后点击「重试写入」。")
            retry_btn = msg.addButton("重试写入", QMessageBox.ButtonRole.AcceptRole)
            cancel_btn = msg.addButton(f"取消{action}", QMessageBox.ButtonRole.RejectRole)
            discard_btn = msg.addButton("放弃暂存并继续", QMessageBox.ButtonRole.DestructiveRole)
            msg.setDefaultButton(retry_btn)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == retry_btn:
                if try_flush_pending():
                    return True
                pending = get_pending_count()
                if pending == 0:
                    return True
                continue
            elif clicked == cancel_btn:
                return False
            elif clicked == discard_btn:
                clear_pending()
                return True
            else:
                # 直接关弹窗 → 视为取消
                return False
        return False  # 不可达，消除类型检查器误报

    def _on_load_data(self) -> None:
        """弹出文件对话框切换活跃 CSV 数据文件。

        运行时切换 CSV 需用户确认（避免当前对局记录写入错误文件）。
        如有暂存记录，操作前先拦截处理。
        """
        if self._worker is not None:
            if not self._ask_yes_no(
                "切换数据文件",
                "识别正在运行，切换数据文件可能导致\n当前对局记录写入错误的文件。\n\n确定要切换吗？",
            ):
                return

        if not self._check_pending_before_switch("切换"):
            return

        csv_dir = str(get_active_csv_path().parent.resolve())
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 CSV 数据文件", csv_dir,
            "CSV 文件 (*.csv);;所有文件 (*)",
        )
        if not path:
            return
        filename = Path(path).name
        set_active_csv(filename)                # 切换到新文件
        self._reload_tables()                   # 重新读取并刷新
        self._show_status(f"已加载: {filename}")

    def _on_backup_data(self) -> None:
        """备份当前活跃 CSV 文件到新文件。

        操作前先拦截暂存记录（确保备份包含最新数据），再复制并切换。
        """
        if not self._check_pending_before_switch("备份"):
            return

        current_path = get_active_csv_path()
        stem = current_path.stem
        default_name = f"bak_{stem}.csv"

        csv_dir = str(current_path.parent.resolve())
        path, _ = QFileDialog.getSaveFileName(
            self, "备份数据", str(Path(csv_dir) / default_name),
            "CSV 文件 (*.csv);;所有文件 (*)",
        )
        if not path:
            return
        saved_name = Path(path).name

        import shutil
        shutil.copy2(str(current_path), path)
        self._show_status(f"已备份: {saved_name}")

        if self._ask_yes_no("切换数据文件",
                            f"备份已保存为 {saved_name}。\n\n是否切换到该文件？"):
            set_active_csv(saved_name)
            self._reload_tables()
            self._show_status(f"已切换到: {saved_name}")

    def _on_new_data(self) -> None:
        """新建空白 CSV 数据文件并询问是否切换。

        操作前先拦截暂存记录，再创建新文件并切换。
        """
        if not self._check_pending_before_switch("新建"):
            return

        cfg = load_config()
        daily = cfg.get("recorder", {}).get("daily_files", False)
        if daily:
            today = datetime.now().strftime("%Y-%m-%d")
            default_name = f"new_data-{today}.csv"
        else:
            default_name = "new_data.csv"

        csv_dir = str(get_active_csv_path().parent.resolve())
        path, _ = QFileDialog.getSaveFileName(
            self, "新建数据", str(Path(csv_dir) / default_name),
            "CSV 文件 (*.csv);;所有文件 (*)",
        )
        if not path:
            return

        import csv as csv_mod
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv_mod.writer(f).writerow(RECORD_COLUMNS)

        saved_name = Path(path).name
        self._show_status(f"已新建: {saved_name}")

        if self._ask_yes_no("切换数据文件",
                            f"空白文件已创建: {saved_name}。\n\n是否切换到该文件？"):
            set_active_csv(saved_name)
            self._reload_tables()
            self._show_status(f"已切换到: {saved_name}")

    # =========================================================================
    # 启动 / 停止识别
    #
    # 启动流程:
    #   1. 检测 Master Duel 窗口是否存在
    #   2. 存在 → 直接启动 StatsWorker
    #   3. 不存在 → 询问用户是否通过 Steam 启动游戏
    #   4. 用户同意 → 启动游戏 + 轮询等待窗口出现
    #
    # 停止流程:
    #   1. 设置 worker._running = False
    #   2. 等待线程退出（最多 2 秒）
    #   3. 恢复 UI 状态
    # =========================================================================

    def _on_start(self) -> None:
        """点击"启动"按钮: 检测 Master Duel 窗口，必要时启动游戏并等待。"""
        from src.capture import is_window_open

        # 情况1: 正在等待游戏启动中，点击表示"终止等待"
        if self._wait_timer is not None:
            self._cancel_wait()
            self._show_status("已取消等待 — 请先启动 Master Duel")
            return

        # 情况2: 窗口已存在，直接启动识别
        if is_window_open("masterduel"):
            self._start_worker()
            return

        # 情况3: 窗口不存在，弹窗询问是否启动游戏
        msg = QMessageBox(self)
        msg.setWindowTitle("Master Duel 未运行")
        msg.setText("未检测到 Master Duel 窗口。\n\n是否启动 Master Duel？")
        msg.setWindowIcon(self.windowIcon())
        msg.setIcon(QMessageBox.Icon.Question)
        btn_yes = msg.addButton("是", QMessageBox.ButtonRole.YesRole)
        msg.addButton("否", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_yes)
        msg.exec()

        if msg.clickedButton() != btn_yes:
            self._show_status("已取消 — 请先启动 Master Duel")
            return

        # 通过 Steam URI 协议启动游戏（steam://rungameid/1449850 = Master Duel）
        os.startfile("steam://rungameid/1449850")
        self._show_status("正在等待 Master Duel 启动…")

        # 将启动按钮改为"终止等待"按钮
        self._btn_start.setText("终止等待")
        self._btn_start.setStyleSheet(
            self._tm.make_button_style(self._theme_colors()["warning_bg"], padding="6px 20px")
        )
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._disable_bottom_buttons()

        # 启动定时器，每 2 秒检测一次游戏窗口是否出现
        timer = QTimer(self)
        timer.timeout.connect(self._on_wait_tick)
        timer.start(2000)
        self._wait_timer = timer

    def _on_wait_tick(self) -> None:
        """轮询检测 Master Duel 窗口是否出现（每 2 秒触发一次）。"""
        from src.capture import is_window_open
        if is_window_open("masterduel"):
            self._cancel_wait()          # 窗口出现，取消等待
            self._start_worker()         # 开始识别
        else:
            self._show_status("正在等待 Master Duel 启动…")

    def _cancel_wait(self) -> None:
        """停止等待定时器，恢复启动按钮的原始状态。"""
        if self._wait_timer is not None:
            self._wait_timer.stop()
            self._wait_timer = None
        self._btn_start.setText("启动")
        colors = self._theme_colors()
        self._btn_start.setStyleSheet(self._tm.make_button_style(colors["start_bg"], padding="6px 20px"))
        self._enable_bottom_buttons()

    def _start_worker(self) -> None:
        """创建并启动后台识别工作线程（StatsWorker）。

        连接 worker 的四个信号到对应回调:
            status_update      → _on_status (更新状态栏)
            coin_win_detected  → _on_coin_win_detected (缓存硬币结果)
            turn_detected      → _on_turn_detected (缓存先后攻)
            result_detected    → _on_result_detected (写入 CSV)

        finished 信号自动清理 worker 引用，避免 QThread 被 GC 时仍在运行。
        """
        from src.stats_worker import StatsWorker
        from src.rank_worker import RankWorker
        from src.failure_sample_manager import FailureSampleManager

        # 创建失败样本管理器（两个线程共用同一实例）
        failure_mgr = FailureSampleManager(self._config)

        self._worker = StatsWorker(failure_mgr=failure_mgr)
        self._worker.status_update.connect(self._on_status)
        self._worker.coin_win_detected.connect(self._on_coin_win_detected)
        self._worker.rank_detected.connect(self._on_rank_detected)
        self._worker.turn_detected.connect(self._on_turn_detected)
        self._worker.result_detected.connect(self._on_result_detected)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))

        self._worker.start()

        # ---- 段位图标检测线程 ----
        # 独立于主管线运行，以可配置间隔持续检测双方段位图标。
        # rank_icon_detected 信号在双方都检测到后发射，
        # 主窗口收到信号后更新状态栏 + 暂存结果等对局结束写入 CSV。
        if self._config.get("rank_detection", {}).get("enabled", True):
            self._rank_worker = RankWorker(failure_mgr=failure_mgr)
            self._rank_worker.rank_icon_detected.connect(self._on_rank_icon_detected)
            self._rank_worker.partial_update.connect(self._on_rank_partial)
            self._rank_worker.start()  # QThread.start() → 后台独立线程执行 run()
        self._snapshot_ctrl.sync_hotkeys()

        # 更新 UI 状态: 禁用启动、启用停止、锁定卡组、禁用危险按钮
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lock_deck()
        self._disable_bottom_buttons()
        self._update_manual_buttons()

    def _on_stop(self) -> None:
        """点击"停止"按钮: 停止后台识别线程并恢复 UI。

        停止方式: 设置 _running = False → 线程自行退出（不使用 terminate()）
        等待时间: 最多 500ms（线程在 interval 秒内退出，默认 0.3s）
        线程退出后 finished 信号自动清理引用。
        """
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(1000)
        if self._rank_worker is not None:
            self._rank_worker.stop()
            self._rank_worker.wait(1000)

        self._snapshot_ctrl.unregister_hotkeys()
        self._reset_stage()                      # 重置状态机
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._unlock_deck()
        self._enable_bottom_buttons()

    # =========================================================================
    # 自动识别回调（由 StatsWorker 的信号触发，在主线程中执行）
    #
    # Qt 的 Signal 是线程安全的: 子线程 emit → Qt 投递到主线程事件队列
    # → 主线程调用槽函数。所以这些回调中可以直接操作 GUI 控件。
    # =========================================================================

    def _on_status(self, msg: str) -> None:
        """接收后台线程的状态更新消息。

        特殊处理: 如果消息表明 Master Duel 已关闭（"程序已关闭"），
                  自动恢复按钮状态，用户可以点击"启动"重新开始。
        """
        _log.write("STATUS", msg)
        self._show_status(msg)
        if msg.startswith("程序已关闭"):
            self._btn_start.setEnabled(True)
            self._btn_stop.setEnabled(False)
            self._unlock_deck()
            self._enable_bottom_buttons()

    def _on_coin_win_detected(self, coin_win: str) -> None:
        """自动识别到硬币结果 → 缓存并推进到阶段1。

        仅当手动尚未抢先选择时生效（stage == 0 才处理）。
        状态栏消息由 worker 统一发送（含段位升降信息），此处不再重复。
        """
        if not self._match.advance_coin(coin_win):
            return
        self._update_manual_buttons()

    def _on_rank_detected(self, rank: str) -> None:
        """自动识别到段位升降 → 缓存结果。

        rank 可能的值: 'up'（升段）、'down'（降段）、''（普通局）。
        结果在 _on_result_detected 中随记录一起写入 CSV。
        """
        self._match.set_rank(rank)

    def _on_rank_icon_detected(self, rank_info: dict) -> None:
        """段位图标检测线程回调：收到双方段位 → 暂存结果 + 状态栏通知。

        这个槽连接到 RankWorker.rank_icon_detected 信号。
        信号在双方段位都检测到后发射（player 和 opponent 都有值）。

        虽然这里就收到了结果，但不立即写入 CSV——因为对局还没结束。
        结果暂存在 _rank_icon_result，等对局结束时 _rank_icon_strs() 取出。

        rank_info 格式:
            {"player_rank": "铂金", "player_tier": 2, "player_score": 0.92,
             "opponent_rank": "钻石", "opponent_tier": 1, "opponent_score": 0.88}
        """
        self._rank_icon_result = rank_info

        # 格式化段位字符串用于状态栏显示
        show_conf = self._config.get("debug", {}).get("show_confidence", False)
        def _fmt(key: str) -> str:
            rank = rank_info.get(f"{key}_rank") or "?"
            if rank == "?":
                return "?"                     # 未检测到，不显示假置信度 0.00
            icon_score = rank_info.get(f"{key}_score", 0)
            tier = rank_info.get(f"{key}_tier")
            tier_score = rank_info.get(f"{key}_tier_score", 0)
            if show_conf:
                rank_part = f"{rank} ({icon_score:.2f})"
            else:
                rank_part = rank
            if isinstance(tier, int) and 1 <= tier <= 5:
                tier_str = ["", "I", "II", "III", "IV", "V"][tier]
                if show_conf:
                    return f"{rank_part} {tier_str} ({tier_score:.2f})"
                return f"{rank} {tier_str}"
            return rank_part

        player = _fmt("player")
        opponent = _fmt("opponent")
        self._on_status(f"段位: {player} vs {opponent}")

    def _on_rank_partial(self, rank_info: dict) -> None:
        """增量进度回调：主循环首次检测到单方段位时更新状态栏。

        与 _on_rank_icon_detected 不同：
        - 此槽仅更新状态栏显示，不存储结果（_rank_icon_result 不变）
        - 等双方齐备后 rank_icon_detected 发射时才正式存储
        """
        show_conf = self._config.get("debug", {}).get("show_confidence", False)

        def _partial_fmt(key: str) -> str:
            rank = rank_info.get(f"{key}_rank")
            if not rank:
                return "?"
            icon_score = rank_info.get(f"{key}_score", 0)
            tier = rank_info.get(f"{key}_tier")
            tier_score = rank_info.get(f"{key}_tier_score", 0)
            if show_conf:
                rank_part = f"{rank} ({icon_score:.2f})"
            else:
                rank_part = rank
            if isinstance(tier, int) and 1 <= tier <= 5:
                tier_str = ["", "I", "II", "III", "IV", "V"][tier]
                if show_conf:
                    return f"{rank_part} {tier_str} ({tier_score:.2f})"
                return f"{rank} {tier_str}"
            return rank_part

        player = _partial_fmt("player")
        opponent = _partial_fmt("opponent")
        self._on_status(f"🔍 检测中: {player} vs {opponent}")

    def _rank_icon_strs(self) -> tuple[str, str]:
        """取出缓存的段位图标结果，返回 (己方段位字符串, 对方段位字符串)。

        调用后缓存被清空（取后即焚），保证每次对局最多用一次。
        RankWorker 可能检测到多次（如连续两帧都匹配到），但只有第一次有效。

        Returns:
            ("铂金 II", "钻石 I") 或 ("", "") 表示未检测到
        """
        info = self._rank_icon_result
        self._rank_icon_result = None  # 取后清空
        if not info:
            return "", ""
        result = []
        for key in ["player", "opponent"]:
            rank = info.get(f"{key}_rank") or ""
            tier = info.get(f"{key}_tier")
            if isinstance(tier, int) and 1 <= tier <= 5:
                tier_str = ["", "I", "II", "III", "IV", "V"][tier]
            else:
                tier_str = ""
            # "铂金 II" 或 "巅峰"（无等级数字）
            result.append(f"{rank} {tier_str}".strip() if tier_str else rank)
        return result[0], result[1]

    def _on_turn_detected(self, turn: str) -> None:
        """自动识别到先后攻 → 缓存并推进到阶段2。

        仅当手动尚未抢先选择时生效（stage == 1 才处理）。
        注意: 此时卡组名直接从输入框读取（不缓存），因为用户可能在识别期间
               修改了卡组名，放在写入 CSV 时再读可以拿到最新值。
        """
        if not self._match.advance_turn(turn):
            return
        # 段位图标已消失，通知 RankWorker 停止搜索
        if self._rank_worker is not None:
            self._rank_worker.stop_searching()
        self._update_manual_buttons()
        turn_text = "先攻" if turn == "first" else "后攻"
        self._show_status(f"已识别: {turn_text} — 等待胜负…")

    def _on_result_detected(self, result: str) -> None:
        """自动识别到胜负 → 取统一缓存写入 CSV，完成一局对局记录。

        仅当手动尚未抢先选择时生效（stage == 2 才处理）。
        写入 CSV 后重置状态机回到阶段0，等待下一局。

        如果 CSV 文件被其他程序占用（如 WPS/Excel），记录会暂存到内存，
        等下次文件可用时自动补写，状态机正常前进不会卡住。
        """
        if self._match.stage != 2:
            return
        cached = self._match.snapshot()
        coin_cache = cached["coin"]
        turn_cache = cached["turn"]
        rank_cache = cached["rank"]
        result_text = "胜" if result == "win" else "负"

        # 段位图标信息：从 RankWorker 缓存取出（如 "铂金 II"、"钻石 I"）
        # _rank_icon_strs() 取后清除缓存，保证同一局不会重复写入
        player_rank, opponent_rank = self._rank_icon_strs()
        new_record = add_record(coin_win=self._match.coin_cache,
                                turn=self._match.turn_cache,
                                result=result,
                                deck=self._deck_input.text().strip(),
                                rank=self._match.rank_cache,
                                player_rank=player_rank,       # 写入 CSV 己方段位列
                                opponent_rank=opponent_rank)   # 写入 CSV 对方段位列

        self._reset_stage()
        self._reload_tables()
        # 对局完成 → 通知段位检测线程准备搜索下一局的段位图标
        if self._rank_worker is not None:
            self._rank_worker.resume_for_next_game()

        if new_record is not None:
            self._show_status(f"已记录: {result_text} — 等待下一局…")
        else:
            self._show_status(f"{result_text} 暂存失败 — 请关闭占用 CSV 的程序")

        # 系统气泡通知
        self._notify_result(coin_cache, turn_cache, rank_cache,
                            result_text, new_record)

    # =========================================================================
    # 卡组输入锁定
    #
    # 启动识别后自动锁定卡组输入框，防止对局中途修改卡组名导致记录错乱。
    # 用户仍可通过"修改卡组"按钮临时解锁。
    # =========================================================================

    def _lock_deck(self) -> None:
        """锁定卡组输入框（运行时默认状态）。"""
        self._deck_input.setEnabled(False)
        self._btn_lock_deck.setText("修改卡组")

    def _unlock_deck(self) -> None:
        """解锁卡组输入框（停止时恢复）。"""
        self._deck_input.setEnabled(True)
        self._btn_lock_deck.setText("锁定卡组")

    def _on_toggle_deck_lock(self) -> None:
        """点击"修改卡组/锁定卡组"按钮，切换卡组输入框的锁定状态。"""
        if self._deck_input.isEnabled():
            self._deck_input.setEnabled(False)
            self._btn_lock_deck.setText("修改卡组")
            self._show_status("卡组名已锁定")
        else:
            self._deck_input.setEnabled(True)
            self._btn_lock_deck.setText("锁定卡组")
            self._show_status("卡组名已解锁 — 修改后请锁定")

    # =========================================================================
    # 手动录入对局（三步向导：赢硬币 → 先后攻 → 胜负）
    #
    # 两个手动按钮（_btn_manual_win / _btn_manual_lose）的文字和颜色随
    # 当前阶段变化。按钮的 clicked 信号通过 lambda 固定传 'win' 或 'lose'，
    # 在 _manual_step_clicked 内部根据 _stage 决定 side 的具体语义。
    #
    # lambda 传参 → _stage 决定语义:
    #   _stage==0: 'win'→赢硬币,  'lose'→输硬币
    #   _stage==1: 'win'→先攻,    'lose'→后攻
    #   _stage==2: 'win'→胜,      'lose'→负
    #
    # 每次操作后同步 worker 状态，实现手动→自动联动:
    #   手动点了"赢硬币" → worker.jump_to(1) → worker 跳过硬币检测，直接用自动检测先后攻
    # =========================================================================

    def _manual_step_clicked(self, side: str) -> None:
        """手动按钮被点击，根据当前阶段解释 side 的语义并推进。"""
        if self._match.stage == 0:
            # 阶段0: 选择赢硬币/输硬币
            self._match.manual_step(side)
            self._update_manual_buttons()
            self._sync_worker_stage()
            coin_text = "赢硬币" if side == "win" else "输硬币"
            self._show_status(f"手动: {coin_text} — 请选择先后攻")

        elif self._match.stage == 1:
            # 阶段1: 选择先攻/后攻
            _, turn = self._match.manual_step(side)
            self._update_manual_buttons()
            self._sync_worker_stage()
            turn_text = "先攻" if turn == "first" else "后攻"
            self._show_status(f"手动: {turn_text} — 请选择胜负")

        elif self._match.stage == 2:
            # 阶段2: 手动选择胜/负 → 一局完成，写入 CSV
            # 同样取出段位图标检测结果（如果有的话）
            player_rank, opponent_rank = self._rank_icon_strs()
            new_record = add_record(coin_win=self._match.coin_cache,
                                    turn=self._match.turn_cache,
                                    result=side,
                                    deck=self._deck_input.text().strip(),
                                    rank=self._match.rank_cache,
                                    player_rank=player_rank,
                                    opponent_rank=opponent_rank)
            # 先提取通知信息，再 reset（reset 会清空缓存）
            cached = self._match.snapshot()
            coin_cache = cached["coin"]
            turn_cache = cached["turn"]
            rank_cache = cached["rank"]
            result_text = "胜" if side == "win" else "负"
            self._reset_stage()
            self._sync_worker_stage()
            self._reload_tables()
            # 对局完成 → 段位检测线程准备下一局
            if self._rank_worker is not None:
                self._rank_worker.resume_for_next_game()
            if new_record is not None:
                self._show_status(f"手动添加: {result_text} — 已写入 CSV")
            else:
                self._show_status(f"手动添加: {result_text} — 暂存失败，请关闭占用 CSV 的程序")

            # 系统气泡通知
            self._notify_result(coin_cache, turn_cache, rank_cache,
                                result_text, new_record)

    def _notify_result(self, coin_cache: str, turn_cache: str,
                       rank_cache: str, result_text: str,
                       new_record: dict | None) -> None:
        """对局结束时弹出系统气泡通知。

        自动识别和手动添加共用此方法，消除重复代码。

        气泡内容格式: 赢硬币（升段局）→ 先攻 → 胜
        如果 CSV 写入失败（new_record is None），追加占用警告，
        图标从 ℹ 信息切换为 ⚠ 警告。

        Args:
            coin_cache:  硬币缓存 ('win'/'lose'/'')
            turn_cache:  先后攻缓存 ('first'/'second'/'')
            rank_cache:  段位缓存 ('up'/'down'/'')
            result_text: 结果中文文案 ('胜'/'负')
            new_record:  add_record 返回值，None 表示写入失败
        """
        if not self._config.get("notification", {}).get("enabled", False):
            return
        if self._notifying:                         # 防重入：避免同一结果弹两次气泡
            return
        self._notifying = True
        coin_text = "赢硬币" if coin_cache == "win" else "输硬币"
        rank_text = ""
        if rank_cache == "up":
            rank_text = "（升段局）"
        elif rank_cache == "down":
            rank_text = "（降段局）"
        turn_text = "先攻" if turn_cache == "first" else "后攻"
        msg = f"{coin_text}{rank_text} → {turn_text} → {result_text}"
        if new_record is None:
            msg += "\n⚠ CSV 文件被占用，记录已暂存"
        duration = self._config.get("notification", {}).get("duration", 5) * 1000
        self._tray.showMessage("MD Stats", msg,
                               QSystemTrayIcon.MessageIcon.Warning if new_record is None
                               else QSystemTrayIcon.MessageIcon.Information,
                               duration)
        self._notifying = False

    def _on_undo(self) -> None:
        """撤销上一阶段的选择，逐级回退并同步 worker。"""
        stage = self._match.undo()
        self._update_manual_buttons()
        self._sync_worker_stage()
        label = {0: "硬币", 1: "先后攻"}[stage]
        self._show_status(f"已撤销到: {label}")

    def _sync_worker_stage(self) -> None:
        """将当前 _stage 同步到后台工作线程的状态机。

        这是手动→自动联动的关键: 手动录入后，自动识别从新状态继续。
        例如手动选择了"赢硬币"→ worker 直接从 WAITING_TURN 状态开始检测先后攻。
        """
        if self._worker is not None:
            self._worker.jump_to(self._match.stage)

    def _reset_stage(self) -> None:
        """重置所有阶段到初始状态（一局完成后调用）。"""
        self._match.reset()
        self._rank_icon_result = None
        self._notifying = False              # 防重入标志复位
        self._update_manual_buttons()

    def _update_manual_buttons(self) -> None:
        """根据当前 _stage 更新手动按钮的文字、颜色及撤销按钮可见性。

        _stage==0: "赢硬币" / "输硬币" (橙色), 撤销按钮隐藏
        _stage==1: "先攻"   / "后攻"   (蓝色), 撤销按钮可见
        _stage==2: "胜"     / "负"     (绿/红), 撤销按钮可见
        """
        colors = self._theme_colors()
        if self._match.stage == 0:
            left_text, right_text = "赢硬币", "输硬币"
            left_color = right_color = colors["coin"]          # 橙色
            self._btn_undo.setVisible(False)                   # 阶段0无撤销对象
        elif self._match.stage == 1:
            left_text, right_text = "先攻", "后攻"
            left_color = right_color = colors["turn"]          # 蓝色
            self._btn_undo.setVisible(True)
        else:
            left_text, right_text = "胜", "负"
            left_color, right_color = colors["win"], colors["lose"]  # 绿/红
            self._btn_undo.setVisible(True)

        self._btn_manual_win.setText(left_text)
        self._btn_manual_win.setStyleSheet(self._tm.make_button_style(left_color))
        self._btn_manual_lose.setText(right_text)
        self._btn_manual_lose.setStyleSheet(self._tm.make_button_style(right_color))

    # =========================================================================
    # 表格刷新
    # =========================================================================

    def _reload_tables(self) -> None:
        """重新加载 CSV 数据并刷新两个表格（统计 + 记录）。"""
        self._refresh_stats_table()
        self._refresh_record_table()
        # 表格填充后即恢复列宽，不依赖 QTimer 时序，调用幂等无副作用
        self._restore_column_widths()

    def _refresh_stats_table(self) -> None:
        """刷新统计表格（上方表格）。

        数据流: load_records() → compute_stats() → 逐行填充 QTableWidget。
        渲染列由 config.toml 的 [stats].columns 控制（空 = 全部）。
        单元格居中，"合计"行粗体。完成后同步刷新悬浮窗内容。
        """
        records = load_records()
        stats = compute_stats(records)

        # 读取用户选择的统计列（空列表 = 显示全部）
        selected = self._config.get("stats", {}).get("columns")
        columns = selected if selected else list(STATS_COLUMNS)

        self._stats_table.setColumnCount(len(columns))
        self._stats_table.setHorizontalHeaderLabels(columns)

        self._stats_table.setRowCount(len(stats))
        for row_idx, row_data in enumerate(stats):
            for col_idx, col_name in enumerate(columns):
                value = row_data.get(col_name, "")
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # "合计"行加粗
                if row_data.get("卡组") == "合计":
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)

                self._stats_table.setItem(row_idx, col_idx, item)

        self._refresh_float_window()         # 悬浮窗也更新

    def _refresh_record_table(self) -> None:
        """刷新记录表格（下方表格），最新记录显示在最前面。

        从 CSV 读取所有记录后倒序填充（reversed），最新在顶部。
        刷新期间抑制 cellChanged 信号，避免触发误写回 CSV。
        前三列（序号/日期/时间）设为只读。
        刷新后自动滚动到顶部（最新记录）。
        """
        self._suppress_cell_changed = True   # 抑制 cellChanged → 防止误写 CSV

        records = load_records()
        self._record_table.setRowCount(len(records))
        for row_idx, rec in enumerate(reversed(records)):
            for col_idx, col_name in enumerate(RECORD_COLUMNS):
                value = rec.get(col_name, "")
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # 序号/日期/时间 (列 0-2) 禁止编辑
                if col_idx in (0, 1, 2):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                self._record_table.setItem(row_idx, col_idx, item)

        if records:
            self._record_table.scrollToTop() # 滚动到最新记录

        self._suppress_cell_changed = False

    def _on_record_cell_changed(self, row: int, col: int) -> None:
        """用户在记录表格中编辑了单元格 → 同步写回 CSV。

        通过"序号"列（列0）定位被编辑的记录在 CSV 中的位置。
        找到对应行后更新字段值，全量写回 CSV，刷新统计表格。
        """
        if self._suppress_cell_changed:      # 刷新期间忽略
            return
        if col in (0, 1, 2):                # 序号/日期/时间不可编辑
            return

        item = self._record_table.item(row, col)
        if item is None:
            return
        new_value = item.text().strip()

        # 通过序号列定位记录
        seq_item = self._record_table.item(row, 0)
        if seq_item is None:
            return
        seq = seq_item.text().strip()

        records = load_records()
        col_name = RECORD_COLUMNS[col]

        updated = False
        for rec in records:
            if rec.get("序号") == seq:
                if rec.get(col_name) != new_value:
                    rec[col_name] = new_value
                    updated = True
                break

        if updated:
            if not save_records(records):        # 全量写回
                self._show_status("修改失败 — CSV 文件被占用，请关闭 WPS/Excel 后重试")
                return
            self._refresh_stats_table()      # 刷新统计

    # =========================================================================
    # 删除最后记录
    # =========================================================================

    def _on_delete_last(self) -> None:
        """删除最后一条对战记录，需用户确认。

        只操作 CSV 文件，不触发暂存记录补写（补写只在对局结束时自动发生）。
        """
        records = load_records()
        if not records:
            self._show_status("没有记录可删除")
            return

        last = records[-1]
        deck = last.get("使用卡组", "")
        result = last.get("结果", "")
        coin = "赢硬币" if last.get("赢硬币") == "是" else "输硬币"
        detail = f"{deck} / {coin} / {result}" if deck else f"{coin} / {result}"

        confirm_text = f"确定要删除最后一条记录吗？\n\n{detail}"
        pending = get_pending_count()
        if pending > 0:
            confirm_text += f"\n\n（注意：内存中有 {pending} 条暂存记录尚未写入 CSV，不受本次删除影响）"

        if not self._ask_yes_no("确认删除", confirm_text):
            return

        records.pop()
        if not save_records(records):
            self._show_status("删除失败 — CSV 文件被占用，请关闭 WPS/Excel 后重试")
            return
        self._reload_tables()
        self._show_status(f"已删除最后记录: {detail}")

    def _on_delete_all_records(self) -> None:
        """删除全部对战记录 — 二次确认防止误删。

        只操作 CSV 文件，不触发暂存记录补写。
        """
        # 暂存记录不受删除影响，等下次对局结束时自动补写
        records = load_records()
        if not records:
            self._show_status("没有记录可删除")
            return

        confirm_text = f"确定要删除全部 {len(records)} 条记录吗？\n\n此操作不可恢复。"
        pending = get_pending_count()
        if pending > 0:
            confirm_text += f"\n\n（注意：内存中有 {pending} 条暂存记录尚未写入 CSV，不受本次删除影响）"

        if not self._ask_yes_no("确认删除全部", confirm_text):
            return

        if not save_records([]):
            self._show_status("删除失败 — CSV 文件被占用，请关闭 WPS/Excel 后重试")
            return
        self._reload_tables()
        self._show_status(f"已删除全部 {len(records)} 条记录")

    # =========================================================================
    # 悬浮窗管理
    #
    # 悬浮窗是一个独立的半透明顶层窗口，显示当前卡组的关键统计数据。
    # 用户可拖拽移动，位置会持久化到 .app_state.toml。
    # =========================================================================

    def _on_toggle_float(self) -> None:
        """打开/关闭悬浮统计窗。"""
        if self._float_window is not None:
            # ---- 关闭悬浮窗 ----
            self._save_float_window_pos()
            self._float_window.close()
            self._float_window = None
            self._btn_float.setText("悬浮窗")
            return

        # ---- 打开悬浮窗 ----
        cfg = self._config.get("floating_window", {})
        rows = cfg.get("rows")  # 用户自定义行；空列表或 None → FloatingWindow 内部使用默认行
        self._float_window = FloatingWindow(rows=rows if rows else None)
        self._apply_float_style(cfg)
        self._refresh_float_window()                   # 填入当前统计数据
        self._restore_float_window_pos()               # 恢复上次位置
        self._float_window.show()
        self._btn_float.setText("关闭悬浮")


    def _save_float_window_pos(self) -> None:
        """将悬浮窗当前位置保存到 .app_state.toml。"""
        if self._float_window is None:
            return
        saved = read_app_state()
        pos = self._float_window.pos()
        saved["float_pos"] = [pos.x(), pos.y()]
        write_app_state(saved)

    def _restore_float_window_pos(self) -> None:
        """从 .app_state.toml 恢复悬浮窗位置。

        恢复逻辑:
            1. 读取保存的位置 → 坐标格式有效且在屏幕范围内 → 恢复
            2. 否则居中放置在主屏幕上
        """
        pos = parse_pos(read_app_state().get("float_pos"), min_val=-1000)
        if pos is not None and self._is_pos_on_screen(pos[0], pos[1]):
            self._float_window.move(pos[0], pos[1])
            return
        # 兜底: 主屏幕中央
        screen = QApplication.primaryScreen()
        if screen is not None and self._float_window is not None:
            geo = screen.availableGeometry()
            sz = self._float_window.size()
            self._float_window.move(
                geo.x() + (geo.width() - sz.width()) // 2,
                geo.y() + (geo.height() - sz.height()) // 2,
            )

    def _apply_float_style(self, cfg: dict) -> None:
        """将配置中的样式应用到已存在的悬浮窗。

        悬浮窗创建和配置重载时共用此方法。
        从 cfg 中提取 use_theme_bg / float_bg 路径 / show_status，
        按正确顺序应用：先 update_style（设置样式并 resize），
        再 enable_status（底部状态行），确保尺寸计算准确。

        Args:
            cfg: floating_window 段的配置字典（来自 config.toml）
        """
        float_bg = None
        if cfg.get("use_theme_bg", False) and self._tm.pixmap_paths:
            float_bg = self._tm.pixmap_paths.get("__float_bg__")
        self._float_window.update_style(cfg, float_bg_path=float_bg)
        self._float_window.enable_status(cfg.get("show_status", False))

    def _refresh_float_window(self) -> None:
        """用当前统计表格数据刷新悬浮窗内容。

        从 CSV 加载统计数据，查找当前输入框中的卡组名称，
        把该卡组的统计行传给悬浮窗显示。
        """
        if self._float_window is None:
            return
        records = load_records()
        stats_list = compute_stats(records)
        deck_name = self._deck_input.text().strip()
        found = None
        for s in stats_list:
            if s.get("卡组") == deck_name:
                found = s
                break
        self._float_window.update_content(deck_name, found)

    # =========================================================================
    # 关于对话框
    # =========================================================================

    def _on_about(self) -> None:
        """显示"关于"对话框，与设置弹窗风格一致。"""
        from ui.about_dialog import AboutDialog
        close_hover = "#e74c3c"
        bg_path = None
        if self._tm.titlebar_cfg:
            close_hover = self._tm.titlebar_cfg.get("btn_close_hover", close_hover)
        if self._tm.pixmap_paths:
            bg_path = self._tm.pixmap_paths.get("__settings_bg__")
        dlg = AboutDialog(close_hover=close_hover,
                          assets_dir=self._tm.assets_dir,
                          bg_path=bg_path, parent=self,
                          widget_bg=self._tm.colors.get("widget_bg", "#ffffff"))
        dlg.exec()

    # =========================================================================
    # 复制统计 / 打开文件
    # =========================================================================

    @staticmethod
    def _last_record_deck() -> str:
        """返回最近一次对局记录的卡组名，无记录时返回空字符串。"""
        records = load_records()
        return records[-1].get("使用卡组", "").strip() if records else ""

    def _copy_to_clipboard(self) -> None:
        """将统计表格复制到系统剪贴板。行为受 config.toml [clipboard] 段控制。

        - vertical_layout: true=竖排(key\\tvalue)，false=横排 TSV
        - scope: "current"=当前卡组，"all"=全部卡组含合计
        - columns: 要复制的列名列表，空=悬浮窗默认 8 项
        """
        from ui.floating_window import _DEFAULT_ROWS
        cfg = self._config.get("clipboard", {})
        records = load_records()
        stats = compute_stats(records)

        columns: list[str] = cfg.get("columns") or list(_DEFAULT_ROWS)
        scope: str = cfg.get("scope", "all")
        vertical: bool = cfg.get("vertical_layout", False)

        # 过滤范围
        if scope == "current":
            deck_name = self._deck_input.text().strip()
            if not deck_name:
                deck_name = self._last_record_deck()
            matched = [s for s in stats if s.get("卡组") == deck_name]
            stats = matched if matched else stats
        # all 模式但只有一个卡组 → 去掉合计行，等同于 current
        actual_decks = [s for s in stats if s.get("卡组") != "合计"]
        if scope == "all" and len(actual_decks) <= 1:
            stats = actual_decks

        if vertical:
            # 竖排模式：all 每卡组前放 [卡组名]，跳过"卡组"列避免重复
            lines: list[str] = []
            for row in stats:
                deck = row.get("卡组", "")
                lines.append(f"[{deck}]")
                for col in columns:
                    if col == "卡组":
                        continue  # 卡组名已在标题行，不重复
                    keys = _ROW_KEY_MAP.get(col, (col,))
                    if len(keys) == 2:
                        val = f"{row.get(keys[0], 0)} / {row.get(keys[1], 0)}"
                    else:
                        val = row.get(keys[0], "")
                    lines.append(f"{col}\t{val}")
            QApplication.clipboard().setText("\n".join(lines))
        else:
            # 横排模式（TSV）："胜/负" 等合并列自动展开为 "v1 / v2"
            lines = ["\t".join(columns)]
            for row in stats:
                vals = []
                for c in columns:
                    keys = _ROW_KEY_MAP.get(c, (c,))
                    if len(keys) == 2:
                        vals.append(f"{row.get(keys[0], 0)} / {row.get(keys[1], 0)}")
                    else:
                        key = keys[0]
                        vals.append(str(row.get(key, "")))
                lines.append("\t".join(vals))
            QApplication.clipboard().setText("\n".join(lines))

        self._show_status("已复制统计表格到剪贴板")

    @staticmethod
    def _open_csv_dir() -> None:
        """在文件资源管理器中打开活跃 CSV 文件所在的目录。

        跨平台: Windows 用 os.startfile()，Linux/macOS 用 xdg-open。
        """
        csv_dir = str(get_active_csv_path().parent.resolve())
        try:
            if os.name == "nt":
                os.startfile(csv_dir)
            else:
                subprocess.Popen(["xdg-open", csv_dir])
        except OSError:
            pass  # 打开失败时静默忽略

    def _open_rank_stats(self) -> None:
        """打开详细统计信息弹窗（模态）。

        弹窗展示按卡组+己方段位筛选的 17 项统计指标：
            - 段位下拉从 CSV 数据动态生成（只显示实际出现过的段位）
            - 未知段位归入"无段位/其他"
            - 支持拖拽移动、一键复制、背景图主题半透明效果

        视觉参数从当前主题提取，保证弹窗外观与主窗口一致：
            - bg_path: 背景图路径（macaron 等有图主题）
            - widget_bg: 内容区背景色
            - main_bg: 对话框底色（纯色主题用偏移值形成对比）
        """
        from ui.rank_stats_dialog import RankStatsDialog
        # 如果主题提供了 __settings_bg__ 背景图，传给弹窗做半透明效果
        bg_path: str = self._tm.pixmap_paths.get("__settings_bg__", "") if self._tm.pixmap_paths else ""
        dialog = RankStatsDialog(
            self, self._config, self._tm.colors,
            bg_path=bg_path,
            widget_bg=self._tm.colors.get("widget_bg", "#ffffff"),
            main_bg=self._tm.colors.get("main_bg", "#f0f0f0"),
        )
        dialog.exec()  # exec() = 模态弹窗，阻塞直到用户关闭

    def _on_settings(self) -> None:
        """打开图形化设置弹窗，确定后自动写配置 + 重载。

        从当前主题中提取设置弹窗所需的视觉参数：
            - bg_path:     主题背景图路径（弹窗会以此为背景）
            - close_hover: 关闭按钮悬停色（标题栏配置中的 btn_close_hover）
            - widget_bg:   控件背景色（半透明面板的底色）
            - main_bg:     弹窗主背景色（无背景图时的底色）
        """
        from ui.config_dialog import ConfigDialog
        # 背景图：部分主题（如 dark）提供 settings_bg 图片作为弹窗背景
        bg_path = None
        if self._tm.pixmap_paths:
            bg_path = self._tm.pixmap_paths.get("__settings_bg__")
        # 关闭按钮悬停色：默认红色，主题可覆盖
        close_hover = "#e74c3c"
        if self._tm.titlebar_cfg:
            close_hover = self._tm.titlebar_cfg.get("btn_close_hover", close_hover)
        dialog = ConfigDialog(self._config, self,
                              bg_path=bg_path,
                              close_hover=close_hover,
                              assets_dir=self._tm.assets_dir,
                              widget_bg=self._tm.colors.get("widget_bg", "#ffffff"),
                              main_bg=self._tm.colors.get("main_bg", "#f0f0f0"))
        dialog.config_saved.connect(self._on_reload_config)
        dialog.exec()

    # =========================================================================
    # 重新载入配置
    #
    # 这是最复杂的操作之一: 不仅要重新加载主题，还要考虑 worker 的状态。
    # 如果 worker 正在运行，需要用新配置（如新的检测间隔）重启 worker。
    # =========================================================================

    def _on_reload_config(self) -> None:
        """重新加载 config.toml，包括主题、检测参数等所有配置。

        执行流程:
            1. 记录旧主题名 → 重新加载配置 → 对比新旧主题名
            2. 如果主题变了: 重新加载 QSS + QPalette + 表格背景 + 标题栏
            3. 如果 Worker 正在运行: 停止后用新配置重启（如新的检测间隔）
            4. 更新状态栏和信息标签
        """
        # 在覆盖旧配置前先记录需要比较的旧值
        old_obs_mode = self._config.get("notification", {}).get("obs_mode", False)
        self._config = load_config()                       # 重新读取 config.toml
        if self._config.get("debug", {}).get("log_mode", False):
            _log.init_log(get_project_root() / "logs")
            _log.set_scopes(set(self._config.get("debug", {}).get("log_scope", ["status", "screenshots", "errors"])))
        self._snapshot_ctrl.sync_hotkeys()
        self._snapshot_ctrl.update_config(self._config)    # 同步新配置到截图控制器
        self._tm._config = self._config                    # 同步到 ThemeManager
        new_theme_name = self._config.get("appearance", {}).get("theme", "dark")
        init_active_csv_from_config()
        self._update_info_label()

        # 重新加载主题文件（字体等可能已通过设置弹窗修改）
        theme = load_theme(new_theme_name)
        self._tm.colors = theme.colors
        self._tm.titlebar_cfg = theme.titlebar
        self._tm.assets_dir = theme.assets_dir
        self.setStyleSheet(theme.qss)
        self._tm.apply_app_palette()
        self._apply_theme_pixmaps(theme.pixmaps)
        self._apply_theme_to_widgets()

        # 悬浮窗已打开 → 用新配置刷新外观和行
        if self._float_window is not None:
            new_cfg = self._config.get("floating_window", {})
            new_rows = new_cfg.get("rows")

            # obs_mode 变化时需要重建悬浮窗（WindowFlags 无法运行时修改）
            new_obs = self._config.get("notification", {}).get("obs_mode", False)
            if old_obs_mode != new_obs:
                # obs_mode 变了 → 关闭旧窗口，重新创建
                self._save_float_window_pos()
                self._float_window.close()
                self._float_window = None
                self._on_toggle_float()  # 用新配置重建
            else:
                if new_rows:
                    self._float_window.set_rows(new_rows)
                self._apply_float_style(new_cfg)
                self._refresh_float_window()

        # 对方卡组预设更新
        new_presets = self._config.get("opponent_decks", {}).get("presets", [])
        self._record_table.setItemDelegateForColumn(6, EditableComboDelegate(new_presets, self._record_table))

        # Worker 正在运行 → 停止后用新配置重启
        worker_was_running = self._worker is not None
        if worker_was_running:
            self._worker.stop()
            self._worker.wait(1000)
        if self._rank_worker is not None:
            self._rank_worker.stop()
            self._rank_worker.wait(1000)
        if worker_was_running:
            self._start_worker()

        self._show_status(
            "配置已重新载入" + (" 并重启识别" if worker_was_running else "")
        )

    # =========================================================================
    # 右下角信息标签（定时刷新）
    #
    # 显示: 活跃 CSV 文件名 | 截图间隔 | 匹配置信度阈值 | Master Duel 窗口状态
    # 每 2 秒自动更新一次（由 _info_timer 驱动）
    # =========================================================================

    def _update_info_label(self) -> None:
        """更新右下角的信息显示。

        包含四个信息:
            - 当前活跃的 CSV 文件名
            - 截图间隔和匹配置信度（来自 config.toml）
            - Master Duel 窗口状态（未启动 / 已最小化 / 分辨率 W×H）
        """
        from src.capture import get_window_status

        interval = self._config.get("detection", {}).get("interval", 0.5)
        threshold = self._config.get("detection", {}).get("confidence_threshold", 0.8)

        size_info: str
        _hwnd, size, is_min = get_window_status("masterduel")
        if _hwnd is None:
            size_info = "未启动"
        elif is_min:
            size_info = "窗口最小化"
        else:
            w, h = size
            size_info = f"{w}×{h}"

        csv_name = get_active_csv_path().name

        text = (
            f"数据: {csv_name} | "
            f"间隔: {interval}s | 阈值: {threshold} | "
            f"Master Duel: {size_info}"
        )
        self._info_label.setText(text)

    # =========================================================================
    # 列宽持久化 + 窗口位置持久化 + 关闭事件
    #
    # 所有持久化数据存储在 .app_state.toml 中，格式:
    #   {"stats": [列宽...], "record": [列宽...], "main_pos": [x, y], "float_pos": [x, y]}
    #
    # 保存时机: 窗口关闭（closeEvent）
    # 恢复时机: 窗口首次显示（showEvent）
    # =========================================================================

    # 列宽默认值（像素），首次运行在 .app_state.toml 不存在时使用
    # stats  列序: 0=卡组 1=对局数 2=胜 3=负 4=胜率
    #              5=赢硬币次数 6=输硬币次数 7=赢硬币概率
    #              8=赢硬币胜率 9=输硬币胜率 10=先攻次数 11=后攻次数
    #              12=先攻胜 13=后攻胜 14=先攻胜率 15=后攻胜率(stretch)
    # stats  记录 15 列，列 15 由 stretchLastSection 自动填充
    # record 列序: 0=序号(隐藏,不记录) 1=日期 2=时间 3=使用卡组 4=对方卡组
    #              5=赢硬币 6=先后攻 7=结果 8=段位升降 9=备注(stretch,不记录)
    # record 记录 8 列（跳过隐藏列 0 和拉伸列 9）
    # 列宽默认值已迁移至 _APP_STATE_DEFAULTS（集中管理）
    # 列序注释保留，方便对照：
    # stats  列 0-14（15 列），列 15 由 stretchLastSection 填充
    # record 列 1-8（8 列），列 0（序号）隐藏 + 列 9（备注）stretch

    def showEvent(self, event) -> None:
        """窗口首次显示后，恢复列宽并应用背景图片。

        为什么不在 __init__ 中做？
            - 列宽恢复需要在表格首次填充后（否则设为默认值又被刷新覆盖）
            - QPixmap 缩放需要知道控件的实际尺寸，__init__ 阶段尺寸 = 默认值
            - showEvent 是窗口首次可见的时机，此时尺寸已确定

        QTimer.singleShot(0, ...) 让列宽恢复在下一帧执行（表格已渲染）
        QTimer.singleShot(100, ...) 给窗口渲染留出 100ms 缓冲
        """
        super().showEvent(event)
        if not self._cols_restored:
            self._cols_restored = True
            QTimer.singleShot(0, self._restore_column_widths)
            QTimer.singleShot(100, self._do_apply_pixmaps)

    def _restore_column_widths(self) -> None:
        """从 .app_state.toml 恢复列宽。

        恢复策略:
            1. 读取保存的列宽数组
            2. 逐列应用，宽度的最小值 = 20px（防止太窄看不见）
            3. 如果保存数据不足（列数增加了），后面的用默认值
            4. 最后一列由 stretchLastSection 管理，不在此处理
            5. record 表跳过列 0（序号，始终隐藏），从列 1 开始恢复
        """
        saved = read_app_state()

        defaults_map = APP_STATE_DEFAULTS
        for table, key in [(self._stats_table, "stats"), (self._record_table, "record")]:
            defaults: list[int] = defaults_map[key]
            widths = cast(list[int], saved.get(key, []))
            # record 表跳过多余的列 0（旧格式曾保存隐藏列"序号"的宽度 0）
            if key == "record" and widths and widths[0] == 0:
                widths = widths[1:]
            start_col = 1 if key == "record" else 0
            for col in range(start_col, table.columnCount() - 1):  # 跳过最后一列
                i = col - start_col  # widths 数组的索引
                if widths and i < len(widths):
                    table.setColumnWidth(col, max(20, widths[i]))
                elif i < len(defaults):
                    table.setColumnWidth(col, defaults[i])

    def _save_column_widths(self) -> None:
        """保存绝对列宽到 .app_state.toml。

        跳过最后一列（由 stretchLastSection 自动管理宽度）。
        record 表额外跳过列 0（序号，始终隐藏，不持久化）。
        """
        data = read_app_state()
        for table, key in [(self._stats_table, "stats"), (self._record_table, "record")]:
            if key == "record":
                data[key] = [table.columnWidth(c) for c in range(1, table.columnCount() - 1)]
            else:
                data[key] = [table.columnWidth(c) for c in range(table.columnCount() - 1)]
        write_app_state(data)

    # =========================================================================
    # 窗口关闭事件
    # =========================================================================

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """双击托盘图标 → 显示窗口。"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        """托盘右键"显示窗口"：恢复并置顶。"""
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def changeEvent(self, event: Any) -> None:
        """窗口状态变化时触发。最小化按钮正常最小化，不拦截。"""
        super().changeEvent(event)

    def _quit_app(self) -> None:
        """托盘右键退出：绕过托盘模式，直接保存状态并退出。"""
        self._real_close()  # 返回值忽略，托盘退出不阻止

    def closeEvent(self, event: Any) -> None:
        """关闭窗口：最小化到托盘模式 → 隐藏，否则正常退出。"""
        if self._config.get("notification", {}).get("minimize_to_tray", False):
            self.hide()
            self._tray.showMessage("MD Stats", "已最小化到托盘，程序在后台继续运行",
                                   QSystemTrayIcon.MessageIcon.Information, 1500)
            event.ignore()
        else:
            if not self._real_close():
                event.ignore()  # 用户取消退出（如点「不退出」）

    def _real_close(self) -> bool:
        """绕过托盘模式强制退出：保存状态 → 停止线程 → 退出。

        Returns:
            True  — 已执行退出流程
            False — 用户取消退出（如点「不退出」）
        """
        data = read_app_state()
        p = self.pos()
        data["main_pos"] = [p.x(), p.y()]
        if self._float_window is not None:
            fp = self._float_window.pos()
            data["float_pos"] = [fp.x(), fp.y()]
        # 保存列宽（跳过 stats 最后一列 stretch、record 列0隐藏列和最后一列 stretch）
        data["stats"] = [self._stats_table.columnWidth(c)
                         for c in range(self._stats_table.columnCount() - 1)]
        data["record"] = [self._record_table.columnWidth(c)
                          for c in range(1, self._record_table.columnCount() - 1)]
        data["splitter"] = self._splitter.sizes()
        write_app_state(data)

        # ---- 2. 尝试写入暂存记录，失败则让用户选择 ----
        pending = get_pending_count()
        if pending > 0:
            if try_flush_pending():
                pass  # 补写成功，静默处理
            else:
                # 补写仍失败 → 弹窗让用户选择：重试 / 不退出 / 强制退出
                while True:
                    msg = QMessageBox(self)
                    msg.setWindowTitle("记录丢失警告")
                    msg.setIcon(QMessageBox.Icon.Warning)
                    msg.setText(
                        f"有 {pending} 条对局记录因 CSV 文件被占用而无法写入。\n\n"
                        f"文件: {get_active_csv_path().name}"
                    )
                    msg.setInformativeText(
                        "请关闭占用该文件的程序（如 WPS、Excel），\n"
                        "然后点击「重试写入」保存记录。"
                    )
                    retry_btn = msg.addButton("重试写入", QMessageBox.ButtonRole.AcceptRole)
                    cancel_btn = msg.addButton("不退出", QMessageBox.ButtonRole.RejectRole)
                    force_btn = msg.addButton("强制退出（丢失记录）", QMessageBox.ButtonRole.DestructiveRole)
                    msg.setDefaultButton(retry_btn)
                    msg.exec()
                    clicked = msg.clickedButton()
                    if clicked == retry_btn:
                        if try_flush_pending():
                            break  # 写入成功，退出循环继续退出流程
                        # 写入仍失败 → 更新 pending 数量，再弹一次
                        pending = get_pending_count()
                        if pending == 0:  # 理论上不会，但安全起见
                            break
                        continue
                    elif clicked == cancel_btn:
                        return False  # 取消退出，留在程序中
                    elif clicked == force_btn:  # 强制退出 → 二次确认
                        confirm = QMessageBox(self)
                        confirm.setWindowTitle("确认丢失")
                        confirm.setIcon(QMessageBox.Icon.Warning)
                        confirm.setText(
                            f"确定要强制退出吗？\n\n"
                            f"{pending} 条暂存记录将永久丢失，无法恢复。"
                        )
                        confirm.setStandardButtons(
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        confirm.setDefaultButton(QMessageBox.StandardButton.No)
                        confirm.button(QMessageBox.StandardButton.Yes).setText("是")
                        confirm.button(QMessageBox.StandardButton.No).setText("否")
                        if confirm.exec() == QMessageBox.StandardButton.Yes:
                            break  # 用户确认，退出循环继续退出流程
                        # 否则回到选择弹窗
                        continue

        # ---- 3. 停止所有定时器和后台线程 ----
        if self._info_timer is not None:
            self._info_timer.stop()
        if self._wait_timer is not None:
            self._wait_timer.stop()
        worker = self._worker
        if worker is not None:
            worker.stop()               # 优雅停止：让最后一轮检测跑完并 emit 结果
            worker.wait(1000)           # 等最多 1 秒处理完 pending 写入
            if worker.isRunning():
                worker.terminate()       # 超时兜底
                worker.wait()
        if self._rank_worker is not None:
            self._rank_worker.terminate()  # 段位线程不影响 CSV，直接杀
            self._rank_worker.wait()

        # ---- 4. 注销全局热键并退出事件循环 ----
        self._snapshot_ctrl.unregister_hotkeys()
        QApplication.quit()
        return True

    @staticmethod
    def _is_pos_on_screen(x: int, y: int, margin: int = 50) -> bool:
        """检查坐标 (x, y) 是否在任一屏幕的可见区域内。

        多显示器环境下，保存的位置可能在副屏上。只要坐标落在
        任意一块屏幕的可见区域内（含 margin 像素容差），就认为有效。

        未找到屏幕信息时（极罕见），保守返回 True，不阻止恢复。

        Args:
            x:     窗口左上角 X 坐标
            y:     窗口左上角 Y 坐标
            margin: 容差像素（窗口边缘可以稍微超出屏幕）
        """
        for screen in QApplication.screens():
            geo = screen.availableGeometry()
            if (geo.x() - margin <= x <= geo.x() + geo.width() + margin and
                    geo.y() - margin <= y <= geo.y() + geo.height() + margin):
                return True
        return False

    def _restore_main_window_pos(self) -> None:
        """从 .app_state.toml 恢复主窗口位置。

        恢复逻辑:
            1. 读取保存的位置 → 坐标格式有效（x ≥ -100）且在屏幕范围内 → 恢复
            2. 否则不恢复（使用 Qt 默认位置，通常在主屏幕中央）
        """
        pos = parse_pos(read_app_state().get("main_pos"))
        if pos is not None and self._is_pos_on_screen(pos[0], pos[1]):
            self.move(pos[0], pos[1])

    def _save_main_window_pos(self) -> None:
        """保存主窗口位置到 .app_state.toml。"""
        data = read_app_state()
        p = self.pos()
        data["main_pos"] = [p.x(), p.y()]
        write_app_state(data)

