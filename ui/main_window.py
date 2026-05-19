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


import ctypes
import json
import os
import subprocess
from pathlib import Path
from typing import Any, TypeVar

from PySide6.QtCore import QFile, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPalette, QIcon, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
)

from ui._meta import VERSION, AUTHOR, LICENSE, DESCRIPTION, REPO_URL, ACKNOWLEDGMENTS
from src.config import get_project_root, load_config
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
from src.theme_loader import Theme, load_theme
from ui.titlebar import TitleBar

# .ui 界面文件的绝对路径
UI_FILE = Path(__file__).resolve().parent / "main_window.ui"

# config.toml 的绝对路径（开发/打包兼容）
_CONFIG_PATH = get_project_root() / "config.toml"

# 表格列宽持久化文件
_COLUMN_WIDTHS_PATH = get_project_root() / ".column_widths.json"
_RESOURCE_DIR = get_project_root() / "resource"

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

    def _theme_colors(self) -> dict[str, str]:
        """返回当前主题的颜色表（缓存在 self._colors 中）。"""
        return self._colors

    def _apply_theme_pixmaps(self, pixmaps: dict[str, str]) -> None:
        self._pixmap_paths = pixmaps

    def _do_apply_pixmaps(self) -> None:
        """QPalette 设背景：关键控件先 QPalette 纯色，有图叠图。"""
        main_bg = self._colors.get("main_bg", "#f5f6fa")
        status_bg = self._colors.get("statusbar_bg", "#ecf0f1")

        # 标题栏 QSS 是 background: transparent，设 autoFillBackground 会覆盖透明
        # 让标题栏保持透明，透出 contentWidget 的背景图
        self._set_palette_bg(self._status_frame, None, status_bg)
        # content widget 从 QSS 中移掉 background-color，改用 QPalette
        self._set_palette_bg(self._content, None, main_bg)

        for selector, path in self._pixmap_paths.items():
            pm = QPixmap(path)
            if pm.isNull():
                continue
            if selector == "#contentWidget":
                self._set_palette_bg(self._content, pm, main_bg)
            elif selector == "#customStatusBar":
                self._set_palette_bg(self._status_frame, pm, status_bg)
            elif selector == "QTableWidget":
                for table in (self._stats_table, self._record_table):
                    self._set_palette_bg(table.viewport(), pm, main_bg)
            elif selector == "QHeaderView::section":
                for table in (self._stats_table, self._record_table):
                    hh = table.horizontalHeader()
                    self._set_palette_bg(hh, pm, main_bg)

    @staticmethod
    def _set_palette_bg(widget, pm, fallback_color: str) -> None:
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setAutoFillBackground(True)
        p = widget.palette()
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(widget.size(),
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            p.setBrush(p.ColorRole.Window, scaled)
            p.setBrush(p.ColorRole.Base, scaled)
        else:
            color = QColor(fallback_color)
            p.setColor(p.ColorRole.Window, color)
            p.setColor(p.ColorRole.Base, color)
        widget.setPalette(p)

    def _show_status(self, msg: str) -> None:
        """更新状态栏消息。"""
        self._status_label.setText(msg)

    def _ask_yes_no(self, title: str, text: str) -> bool:
        """弹出"是/否"确认对话框，返回 True 表示选"是"。"""
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setWindowIcon(self.windowIcon())
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.button(QMessageBox.StandardButton.Yes).setText("是")
        msg.button(QMessageBox.StandardButton.No).setText("否")
        return msg.exec() == QMessageBox.StandardButton.Yes

    def _is_dark_theme(self) -> bool:
        """判断当前是否为暗色主题。"""
        return self._config.get("appearance", {}).get("theme", "dark") == "dark"

    def _apply_dwm_style(self) -> None:
        """DWM 原生阴影 + Windows 11 圆角（失败时静默跳过）。"""
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())

            class _MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            margins = _MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(  # type: ignore[attr-defined]
                hwnd, ctypes.byref(margins),
            )

            # Windows 11 原生圆角
            dwmwa_window_corner_preference = 33
            dwmwcp_round = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd, dwmwa_window_corner_preference,
                ctypes.byref(ctypes.c_int(dwmwcp_round)),
                ctypes.sizeof(ctypes.c_int),
            )
        except OSError:
            pass

    # ---- 无边框窗口 resize 支持 ----
    _BORDER_WIDTH = 6
    _resize_edge: Any = None  # Qt.Edge | None

    def _edge_at(self, global_pos) -> Any:
        """检测全局坐标是否在窗口边缘，返回 Qt.Edge 或 None。"""
        geo = self.geometry()
        bw = self._BORDER_WIDTH
        x, y = global_pos.x(), global_pos.y()
        left_edge = x < geo.x() + bw
        right_edge = x >= geo.x() + geo.width() - bw
        top_edge = y < geo.y() + bw
        bottom_edge = y >= geo.y() + geo.height() - bw

        if top_edge and left_edge:
            return Qt.Edge.LeftEdge | Qt.Edge.TopEdge  # type: ignore[return-value]
        if top_edge and right_edge:
            return Qt.Edge.RightEdge | Qt.Edge.TopEdge  # type: ignore[return-value]
        if bottom_edge and left_edge:
            return Qt.Edge.LeftEdge | Qt.Edge.BottomEdge  # type: ignore[return-value]
        if bottom_edge and right_edge:
            return Qt.Edge.RightEdge | Qt.Edge.BottomEdge  # type: ignore[return-value]
        if top_edge:
            return Qt.Edge.TopEdge
        if bottom_edge:
            return Qt.Edge.BottomEdge
        if left_edge:
            return Qt.Edge.LeftEdge
        if right_edge:
            return Qt.Edge.RightEdge
        return None

    def eventFilter(self, watched, event) -> bool:
        """将子控件的鼠标事件转发给窗口级 resize 检测。"""
        from PySide6.QtCore import QEvent
        t = event.type()
        if t == QEvent.Type.MouseMove:
            self._update_resize_cursor(event.globalPosition().toPoint())  # type: ignore[attr-defined]
        elif t == QEvent.Type.MouseButtonPress:
            edge = self._edge_at(event.globalPosition().toPoint())  # type: ignore[attr-defined]
            if edge and self.windowHandle():
                self.windowHandle().startSystemResize(edge)
                return True
        return False

    def _update_resize_cursor(self, global_pos) -> None:
        """根据鼠标在窗口边缘的位置更新光标。"""
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
        """检测窗口边缘点击，触发系统 resize。"""
        edge = self._edge_at(event.globalPosition().toPoint())
        if edge and self.windowHandle():
            self.windowHandle().startSystemResize(edge)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """鼠标移动时更新边缘光标。"""
        self._update_resize_cursor(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """双击边缘区域不处理（仅标题栏双击可自定义）。"""
        if self._edge_at(event.globalPosition().toPoint()):
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _lighter(hex_color: str, factor: float = 0.25) -> str:
        """将十六进制颜色向白色方向提亮 factor*100%%。"""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _btn_style(self, bg: str, *, padding: str = "4px 14px") -> str:
        """生成带 hover 高亮效果的动态按钮样式。

        如果主题用了按钮纹理（macaron 之类），用 bg 作为饱和度更高的实色
        填充，覆盖底层水彩纹理 —— 让 [启动=绿] [赢硬币=黄] [先攻=蓝] [胜=绿/负=粉]
        这些按钮在面板中作为彩色音符跳出来，而不是被纹理混成一片粉色。
        """
        button_texture = self._pixmap_paths.get("QPushButton") if self._pixmap_paths else None

        if button_texture:
            text_color = self._readable_on(bg)
            hover_bg = self._lighter(bg, 0.12)
            pressed_bg = self._darker(bg, 0.08)
            border_disabled = self._colors.get("border_disabled", "#f5eef4")
            text_disabled = self._colors.get("text_disabled", "#d5ccd8")
            # 关键：用 `background:` 简写而不是 background-color/background-image 分开写，
            # 因为 Qt QSS 在合并 setStyleSheet 和全局 QSS 时，分写形式有时不会清掉
            # 全局规则里的 background-image: url(button_texture)，导致整个按钮还显示
            # 水彩纹理，颜色只露出边框那一圈。`background: <solid color>` 是清除
            # 所有 background 子属性的唯一可靠方式。
            return (
                "QPushButton { "
                f"background: {bg}; "
                f"color: {text_color}; font-weight: bold; "
                f"padding: {padding}; border-radius: 12px; "
                f"border: 1px solid {bg}; "
                "} "
                "QPushButton:hover { "
                f"background: {hover_bg}; "
                f"border-color: {hover_bg}; "
                "} "
                "QPushButton:pressed { "
                f"background: {pressed_bg}; "
                f"border-color: {pressed_bg}; "
                "} "
                "QPushButton:disabled { "
                f"background: {self._colors.get('button_disabled_bg', 'rgba(245,238,244,220)')}; "
                f"color: {text_disabled}; "
                f"border-color: {border_disabled}; "
                "}"
            )

        # 默认（dark/light）：保持原来的纯色按钮样式
        border = self._colors.get("border", "#dcdde1")
        hover_bg = self._lighter(bg)
        disabled_bg = self._colors.get("button_disabled_bg", "#9E9E9E")
        disabled_color = self._colors.get("text_disabled", "#e0e0e0")
        disabled_border = self._colors.get("border_disabled", "#888")
        return (
            f"QPushButton {{ background-color: {bg}; color: white; "
            f"font-weight: bold; padding: {padding}; border-radius: 6px; "
            f"border: 1px solid {border}; }}"
            f"QPushButton:hover {{ background-color: {hover_bg}; "
            f"border-color: {hover_bg}; }}"
            f"QPushButton:disabled {{ background-color: {disabled_bg}; "
            f"color: {disabled_color}; border-color: {disabled_border}; }}"
        )

    @staticmethod
    def _darker(hex_color: str, factor: float = 0.15) -> str:
        """将十六进制颜色向黑色方向加深 factor*100%。"""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _apply_static_button_palette(self) -> None:
        """给少数语义重要的按钮上色，其余保持水彩纹理底色（参考 Uilbox 目标图）。

        有纹理主题（macaron）时用语义色上色；无纹理主题时清除局部 stylesheet，
        让全局 QSS 接管，避免从 macaron 切换后残留旧样式。
        动态按钮（启动/手动 win/lose）由 _update_manual_buttons / _cancel_wait
        在状态切换时另行调 _btn_style 重新设色。

        着色原则：跟"动作 / 状态变化 / 警告"相关的按钮才上色，
        像"加载 / 复制 / 打开 / 编辑 / 重新载入 / 关于"这种常规操作保持原色，
        避免一面墙的彩色按钮淹没主题的水彩气质。
        """
        c = self._colors
        if self._pixmap_paths and self._pixmap_paths.get("QPushButton"):
            # 有纹理主题：用语义色上色
            self._btn_stop.setStyleSheet(self._btn_style(c.get("lose", "#f0a5b5")))
            self._btn_delete_last.setStyleSheet(self._btn_style(c.get("lose", "#f0a5b5")))
        else:
            # 无纹理主题：清除局部 stylesheet，让全局 QSS 接管
            self._btn_stop.setStyleSheet("")
            self._btn_delete_last.setStyleSheet("")

    @staticmethod
    def _readable_on(hex_color: str) -> str:
        """根据底色亮度返回易读的文字色：浅底用深紫灰，深底用白。"""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        # 感知亮度 (ITU-R BT.601)
        luma = (0.299 * r + 0.587 * g + 0.114 * b)
        return "#4a3a52" if luma > 170 else "#ffffff"

    def _apply_table_viewport_palette(self) -> None:
        """表格/表头 viewport 背景：清旧样式，有资源图用 QPalette 贴图，无图涂纯色。"""
        # 先清空所有 viewport/header 上旧主题遗留的 stylesheet 和 QPalette
        for table in (self._stats_table, self._record_table):
            for w in (table.viewport(), table.verticalHeader(), table.horizontalHeader()):
                w.setStyleSheet("")
                w.setAutoFillBackground(False)
                p = w.palette()
                p.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
                p.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
                p.setBrush(QPalette.ColorRole.Window, QBrush())
                p.setBrush(QPalette.ColorRole.Base, QBrush())
                w.setPalette(p)

        # 有资源图：用 QPalette 直接把图贴在 viewport/header 上，
        # 绕过 QAbstractScrollArea 内部对 viewport 的 autoFillBackground 干扰。
        if self._pixmap_paths:
            table_path = self._pixmap_paths.get("QTableWidget")
            header_path = self._pixmap_paths.get("QHeaderView::section")
            main_bg = self._colors.get("main_bg", "#f5f6fa")
            table_pm = QPixmap(table_path) if table_path else None
            header_pm = QPixmap(header_path) if header_path else None
            for table in (self._stats_table, self._record_table):
                self._set_palette_bg(table.viewport(), table_pm, main_bg)
                self._set_palette_bg(table.horizontalHeader(), header_pm, main_bg)
                self._set_palette_bg(table.verticalHeader(), header_pm, main_bg)
            return

        base = self._colors.get("widget_bg", "#ffffff")
        header_bg = self._colors.get("main_bg", "#f5f6fa")
        # 亮色主题下表头用 statusbar_bg
        if self._config.get("appearance", {}).get("theme", "dark") != "dark":
            header_bg = self._colors.get("statusbar_bg", header_bg)

        for table in (self._stats_table, self._record_table):
            vp = table.viewport()
            self._set_palette_bg(vp, None, base)
            vp.setStyleSheet(f"background-color: {base};")

            vh = table.verticalHeader()
            self._set_palette_bg(vh, None, header_bg)
            vh.setStyleSheet(f"background-color: {header_bg};")

            hh = table.horizontalHeader()
            self._set_palette_bg(hh, None, header_bg)
            hh.setStyleSheet(f"background-color: {header_bg};")

    def _wrap_layouts_in_frames(self, content) -> None:
        """把 ctrlLayout 和 bottomLayout 各自塞进一个 QFrame，便于 QSS 贴 panel_bg。

        只在主题带资源图（pixmaps 非空）时执行；dark / light 主题没有 panel_bg，
        让它们的布局保持和原来完全一致，避免 14px 内边距移位。
        已存在同名 QFrame 时跳过，防止重复包裹。
        """
        if not self._pixmap_paths:
            return
        root_layout = content.layout()
        if root_layout is None:
            return

        for layout_name, frame_name in (("ctrlLayout", "topPanel"),
                                         ("bottomLayout", "bottomPanel")):
            # 已存在同名 QFrame，说明之前已包裹过，跳过
            if content.findChild(QFrame, frame_name) is not None:
                continue
            layout = content.findChild(QHBoxLayout, layout_name)
            if layout is None:
                continue
            # 找到 layout 在 rootLayout 中的位置
            idx = -1
            for i in range(root_layout.count()):
                if root_layout.itemAt(i).layout() is layout:
                    idx = i
                    break
            if idx < 0:
                continue
            root_layout.takeAt(idx)
            frame = QFrame(content)
            frame.setObjectName(frame_name)
            frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            frame.setLayout(layout)
            # 留一点内边距让 panel_bg 的画笔边缘可见
            layout.setContentsMargins(14, 6, 14, 6)
            root_layout.insertWidget(idx, frame)

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
        self._cols_restored: bool = False

        # ---- 加载主题 ----
        theme: Theme = load_theme(
            self._config.get("appearance", {}).get("theme", "dark")
        )
        self._colors = theme.colors
        self._titlebar_cfg = theme.titlebar
        self._assets_dir = theme.assets_dir
        self.setStyleSheet(theme.qss)
        self._apply_theme_pixmaps(theme.pixmaps)

        # ---- 无边框窗口 + DWM 原生阴影 ----
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setMouseTracking(True)
        self._apply_dwm_style()

        # ---- 从 .ui 文件加载界面 ----
        loader = QUiLoader()
        ui_file = QFile(str(UI_FILE))
        ui_file.open(QFile.OpenModeFlag.ReadOnly)
        content = loader.load(ui_file)
        ui_file.close()
        content.setObjectName("contentWidget")
        self._content = content

        # ---- 插入自定义标题栏 ----
        self._title_bar = TitleBar(
            "MD Stats", self._titlebar_cfg, self._assets_dir, self
        )
        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.close_clicked.connect(self.close)
        root_layout = content.layout()
        if root_layout is not None:
            root_layout.insertWidget(0, self._title_bar)  # type: ignore[attr-defined]

        self.setCentralWidget(content)

        # 事件过滤器：让子控件的鼠标事件也能触发边缘 resize
        content.setMouseTracking(True)
        content.installEventFilter(self)

        # ---- 窗口图标（系统资源，不随主题变化）----
        icon_path = _RESOURCE_DIR / "icons" / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # 将顶部控制行与底部按钮行各自包进 QFrame，方便 QSS 给它们贴 panel_bg。
        # .ui 里 ctrlLayout/bottomLayout 是裸 QHBoxLayout 直接挂在 rootLayout 上，
        # 没有可绘制的容器；运行时改造一次即可。
        self._wrap_layouts_in_frames(content)

        # 通过 objectName 获取各个控件的引用
        # _require_widget 将 findChild 的 X | None 收窄为 X，消除类型警告
        self._btn_start = _require_widget(content.findChild(QPushButton, "btn_start"), "btn_start")
        self._btn_stop = _require_widget(content.findChild(QPushButton, "btn_stop"), "btn_stop")
        self._deck_input = _require_widget(content.findChild(QLineEdit, "deck_input"), "deck_input")
        self._btn_manual_win = _require_widget(content.findChild(QPushButton, "btn_manual_win"), "btn_manual_win")
        self._btn_manual_lose = _require_widget(content.findChild(QPushButton, "btn_manual_lose"), "btn_manual_lose")
        self._btn_undo = _require_widget(content.findChild(QPushButton, "btn_undo"), "btn_undo")
        self._btn_lock_deck = _require_widget(content.findChild(QPushButton, "btn_lock_deck"), "btn_lock_deck")
        self._stats_table = _require_widget(content.findChild(QTableWidget, "stats_table"), "stats_table")
        self._record_table = _require_widget(content.findChild(QTableWidget, "record_table"), "record_table")
        self._btn_reload = _require_widget(content.findChild(QPushButton, "btn_reload"), "btn_reload")
        self._btn_copy = _require_widget(content.findChild(QPushButton, "btn_copy"), "btn_copy")
        self._btn_delete_last = _require_widget(content.findChild(QPushButton, "btn_delete_last"), "btn_delete_last")
        self._btn_about = _require_widget(content.findChild(QPushButton, "btn_about"), "btn_about")
        self._btn_open_csv = _require_widget(content.findChild(QPushButton, "btn_open_csv"), "btn_open_csv")
        self._btn_edit_config = _require_widget(content.findChild(QPushButton, "btn_edit_config"), "btn_edit_config")
        self._btn_reload_config = _require_widget(content.findChild(QPushButton, "btn_reload_config"), "btn_reload_config")
        self._splitter = _require_widget(content.findChild(QSplitter, "splitter"), "splitter")

        # ---- 窗口基础设置 ----
        self.resize(
            self._config.get("window", {}).get("width", 1100),
            self._config.get("window", {}).get("height", 700),
        )

        # ---- 静态按钮调色板（macaron 主题用，给每个按钮分配不同的语义色） ----
        self._apply_static_button_palette()

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
        self._stats_table.verticalHeader().setDefaultSectionSize(28)

        self._record_table.setColumnCount(len(RECORD_COLUMNS))
        self._record_table.setHorizontalHeaderLabels(RECORD_COLUMNS)
        self._record_table.setColumnHidden(0, True)  # 序号列不出现在界面中
        self._record_table.horizontalHeader().setStretchLastSection(True)
        self._record_table.verticalHeader().setDefaultSectionSize(28)

        # 修复表格空白区域背景色（QSS 可能无法覆盖 viewport 的 palette 色）
        self._apply_table_viewport_palette()

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

        # ---- 自定义状态栏（包在 content 内，共享阴影容器） ----
        self._status_frame = QFrame()
        self._status_frame.setObjectName("customStatusBar")
        sf_layout = QHBoxLayout(self._status_frame)
        sf_layout.setContentsMargins(12, 3, 12, 3)
        sf_layout.setSpacing(10)

        self._status_label = QLabel("就绪 — 请点击《启动》开始")
        self._status_label.setObjectName("statusMessage")
        sf_layout.addWidget(self._status_label, 1)

        self._info_label = QLabel()
        sf_layout.addWidget(self._info_label)

        root_layout.addWidget(self._status_frame)  # type: ignore[union-attr]

        # ---- 右下角信息标签定时刷新 ----
        info_timer = QTimer(self)
        info_timer.timeout.connect(self._update_info_label)  # type: ignore[reportUnknownMemberType]
        info_timer.start(2000)
        self._info_timer = info_timer
        # 首次更新延迟到窗口显示后，避免 EnumWindows 阻塞界面出现
        QTimer.singleShot(200, self._update_info_label)

        # ---- 初始加载 CSV 数据并填充表格 ----
        self._reload_tables()

        # ---- 初始化手动按钮样式（阶段 0 = 橙色赢硬币/输硬币） ----
        self._update_manual_buttons()
        # 启动按钮有局部 stylesheet，需显式设置语义色
        self._btn_start.setStyleSheet(
            self._btn_style(self._theme_colors()["start_bg"], padding="6px 20px")
        )

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
            if not self._ask_yes_no(
                "切换数据文件",
                "识别正在运行，切换数据文件可能导致\n当前对局记录写入错误的文件。\n\n确定要切换吗？",
            ):
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
        self._show_status(f"已加载: {filename}")

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
            self._show_status("已取消等待 — 请先启动 Master Duel")
            return

        # ---- 窗口已存在，直接启动识别 ----
        if is_window_open("masterduel"):  # type: ignore[reportUnknownMemberType]
            self._start_worker()
            return

        # ---- 窗口不存在，弹窗询问 ----
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

        # ---- 用户选择启动游戏 ----
        os.startfile("steam://rungameid/1449850")
        self._show_status("正在等待 Master Duel 启动…")

        # 将启动按钮改为"终止等待"
        self._btn_start.setText("终止等待")
        self._btn_start.setStyleSheet(
            self._btn_style(self._theme_colors()["warning_bg"], padding="6px 20px")
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
            self._show_status("正在等待 Master Duel 启动…")

    def _cancel_wait(self) -> None:
        """停止等待定时器，恢复启动按钮的原始状态。"""
        if self._wait_timer is not None:
            self._wait_timer.stop()
            self._wait_timer = None
        self._btn_start.setText("启动")
        colors = self._theme_colors()
        self._btn_start.setStyleSheet(self._btn_style(colors["start_bg"], padding="6px 20px"))
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
        self._update_manual_buttons()

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
        self._show_status(msg)
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
        self._show_status(f"已识别: {coin_text} — 等待先后攻…")

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
        self._show_status(f"已识别: {turn_text} — 等待胜负…")

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
        self._show_status(f"已记录: {result_text} — 等待下一局…")

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
            self._show_status("卡组名已锁定")
        else:
            self._deck_input.setEnabled(True)
            self._btn_lock_deck.setText("锁定卡组")
            self._show_status("卡组名已解锁 — 修改后请锁定")

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
            self._show_status(f"手动: {coin_text} — 请选择先后攻")

        elif self._stage == 1:
            turn = "first" if side == "win" else "second"
            self._turn_cache = turn
            self._stage = 2
            self._update_manual_buttons()
            self._sync_worker_stage()
            turn_text = "先攻" if turn == "first" else "后攻"
            self._show_status(f"手动: {turn_text} — 请选择胜负")

        elif self._stage == 2:
            add_record(coin_win=self._coin_cache, turn=self._turn_cache, result=side, deck=self._deck_input.text().strip())  # type: ignore[reportUnknownMemberType]
            self._reset_stage()
            self._sync_worker_stage()
            self._reload_tables()
            result_text = "胜" if side == "win" else "负"
            self._show_status(f"手动添加: {result_text} — 已写入 CSV")

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
        self._show_status(f"已撤销到: {label}")

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
        """根据当前 _stage 更新手动按钮的文本、颜色及撤销按钮可见性。"""
        colors = self._theme_colors()
        if self._stage == 0:
            left_text, right_text = "赢硬币", "输硬币"
            left_color = right_color = colors["coin"]
            self._btn_undo.setVisible(False)
        elif self._stage == 1:
            left_text, right_text = "先攻", "后攻"
            left_color = right_color = colors["turn"]
            self._btn_undo.setVisible(True)
        else:
            left_text, right_text = "胜", "负"
            left_color, right_color = colors["win"], colors["lose"]
            self._btn_undo.setVisible(True)

        self._btn_manual_win.setText(left_text)
        self._btn_manual_win.setStyleSheet(self._btn_style(left_color))
        self._btn_manual_lose.setText(right_text)
        self._btn_manual_lose.setStyleSheet(self._btn_style(right_color))

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
        渲染规则: 所有单元格居中、"合计"行粗体。
        """
        records = load_records()  # type: ignore[reportUnknownMemberType]
        stats = compute_stats(records)  # type: ignore[reportUnknownMemberType]

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
            self._show_status("没有记录可删除")
            return

        last = records[-1]
        deck = last.get("使用卡组", "")
        result = last.get("结果", "")
        coin = "赢硬币" if last.get("赢硬币") == "是" else "输硬币"
        detail = f"{deck} / {coin} / {result}" if deck else f"{coin} / {result}"

        if not self._ask_yes_no(
            "确认删除",
            f"确定要删除最后一条记录吗？\n\n{detail}",
        ):
            return

        records.pop()
        save_records(records)  # type: ignore[reportUnknownMemberType]
        self._reload_tables()
        self._show_status(f"已删除最后记录: {detail}")

    # =========================================================================
    # 关于
    # =========================================================================

    def _on_about(self) -> None:
        lines = [
            "<h3>MD Stats</h3>",
            f"<p>版本: {VERSION}<br>",
            f"作者: {AUTHOR}<br>",
            f"协议: {LICENSE}</p>",
        ]
        if REPO_URL:
            lines.append(
                f'<p>仓库: <a href="{REPO_URL}">{REPO_URL}</a></p>'
            )
        lines.append(f"<p>{DESCRIPTION.replace(chr(10), '<br>')}</p>")
        if ACKNOWLEDGMENTS:
            ack = ACKNOWLEDGMENTS.replace("\n", "<br>")
            lines.append(f"<p><b>特别鸣谢</b><br>{ack}</p>")

        msg = QMessageBox(self)
        msg.setWindowTitle("关于 MD Stats")
        msg.setText("".join(lines))
        msg.setWindowIcon(self.windowIcon())
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.button(QMessageBox.StandardButton.Ok).setText("确定")
        # 启用超链接点击
        for label in msg.findChildren(QLabel):
            label.setOpenExternalLinks(True)
            label.setTextFormat(Qt.TextFormat.RichText)
        msg.exec()

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
        self._show_status("已复制统计表格到剪贴板")

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
            self._show_status(f"无法打开配置文件: {config_path}")

    def _on_reload_config(self) -> None:
        """重新加载 config.toml，包括主题、检测参数等所有配置。

        主题切换即时生效（QSS + viewport 背景 + 表格颜色全部重设）。
        如果 Worker 正在运行则用新配置重启。
        """
        old_theme_name = self._config.get("appearance", {}).get("theme", "dark")
        self._config = load_config()  # type: ignore[reportUnknownMemberType]
        new_theme_name = self._config.get("appearance", {}).get("theme", "dark")
        init_active_csv_from_config()  # type: ignore[reportUnknownMemberType]
        self._update_info_label()

        # 主题变化时重新加载主题文件并应用
        if old_theme_name != new_theme_name:
            theme = load_theme(new_theme_name)
            self._colors = theme.colors
            self._titlebar_cfg = theme.titlebar
            self._assets_dir = theme.assets_dir
            self.setStyleSheet(theme.qss)
            self._apply_theme_pixmaps(theme.pixmaps)
            self._wrap_layouts_in_frames(self._content)
            self._apply_table_viewport_palette()
            self._apply_static_button_palette()
            self._refresh_stats_table()
            self._refresh_record_table()
            self._update_manual_buttons()
            # 更新启动按钮样式（有局部 stylesheet，全局 QSS 无法覆盖）
            colors = self._theme_colors()
            self._btn_start.setStyleSheet(
                self._btn_style(colors["start_bg"], padding="6px 20px")
            )
            # 更新标题栏外观
            self._title_bar.set_title("MD Stats")
            self._title_bar.reload_style(self._titlebar_cfg)

        # 如果 Worker 正在运行，停止后用新配置重启
        worker_was_running = self._worker is not None
        if worker_was_running:
            self._worker.stop()   # type: ignore[reportUnknownMemberType]
            self._worker.wait(2000)  # type: ignore[reportUnknownMemberType]
            self._start_worker()

        self._show_status(
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

    # 列宽默认值（首次运行使用，像素），最后一列由 stretchLastSection 管理
    _DEFAULT_COLUMN_WIDTHS = {
        "stats":    [70, 40, 25, 25, 50, 75, 75, 70, 70, 60, 60, 50, 50, 70],
        "record":   [ 0, 78, 65, 64, 62, 50, 47, 39],
    }

    def showEvent(self, event) -> None:
        """窗口首次显示后，恢复列宽并应用背景图片。"""
        super().showEvent(event)
        if not self._cols_restored:
            self._cols_restored = True
            QTimer.singleShot(0, self._restore_column_widths)
            QTimer.singleShot(100, self._do_apply_pixmaps)

    def _restore_column_widths(self) -> None:
        """从 .column_widths.json 恢复列宽（跳过最后一列）。"""
        try:
            with open(_COLUMN_WIDTHS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            saved = {}

        for table, key, defaults in [
            (self._stats_table, "stats", self._DEFAULT_COLUMN_WIDTHS["stats"]),
            (self._record_table, "record", self._DEFAULT_COLUMN_WIDTHS["record"]),
        ]:
            widths = saved.get(key, [])
            for col in range(table.columnCount() - 1):
                if widths and col < len(widths):
                    table.setColumnWidth(col, max(20, widths[col]))
                elif col < len(defaults):
                    table.setColumnWidth(col, defaults[col])

    def _save_column_widths(self) -> None:
        """保存绝对列宽（跳过最后一列，由 stretchLastSection 管理）。"""
        data: dict[str, list[int]] = {}
        for table, key in [
            (self._stats_table, "stats"),
            (self._record_table, "record"),
        ]:
            data[key] = [
                table.columnWidth(c)
                for c in range(table.columnCount() - 1)
            ]
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
