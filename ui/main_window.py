"""主窗口 GUI — 统计表格、记录表格、控制按钮的完整界面。

================================================================================
界面布局
================================================================================

┌──────────────────────────────────────────────────────────────┐
│  [icon] MD Stats                                     [─] [×] │  ← 自定义标题栏
├──────────────────────────────────────────────────────────────┤
│  [启动] [停止]   使用卡组: [________] [修改卡组] [赢硬币] [输硬币] [撤销] │  ← 控制栏
├──────────────────────────────────────────────────────────────┤
│  卡组 │ 对局数 │ 胜 │ 负 │ 胜率 │ 赢硬币次数 │ 输硬币次数 │ 硬币胜率... │  ← 统计表格
│  炎兽 │  15   │ 10 │  5 │66.7%│    8     │    7     │ 53.3% ... │    (上方)
│  合计 │  23   │ 14 │  9 │60.9%│   10     │   13     │ 43.5% ... │
├──────────────────────────────────────────────────────────────┤
│  日期 │ 时间 │ 使用卡组 │ ... │ 赢硬币 │ 先后攻 │ 结果 │ 备注 │  ← 记录表格
│  ...  │ ...  │  炎兽   │ ... │  是   │ 先攻  │ 胜  │     │   (下方)
├──────────────────────────────────────────────────────────────┤
│  [加载] [复制] [打开CSV] [编辑配置] [重载配置] [删除最后] [悬浮窗] [关于]  │  ← 底部按钮
├──────────────────────────────────────────────────────────────┤
│  就绪 — 请点击《启动》开始                    数据: data.csv | ... │  ← 状态栏
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
    [CSV目录]              →  _open_csv_dir()        → 打开文件资源管理器
    [编辑配置]               →  _on_edit_config()     → 用系统程序打开 config.toml
    [重载配置]            →  _on_reload_config()   → 重新加载配置并重启 Worker
    [删除最后]            →  _on_delete_last()     → 确认后删除最后一条记录
    [悬浮窗]               →  _on_toggle_float()     → 开关悬浮统计窗
    [关于]                  →  _on_about()            → 弹窗显示程序信息

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
import json
import os
import subprocess
from pathlib import Path
from typing import Any, TypeVar

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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
    QWidget,
    QTableWidgetItem,
)

from ui.about_dialog import VERSION, AUTHOR, LICENSE, DESCRIPTION, REPO_URL, ACKNOWLEDGMENTS
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
# capture / stats_worker 延迟导入（启动时才需要 OpenCV，避免程序启动等待 ~260ms）
from src.theme_loader import Theme, load_theme
from ui.floating_window import FloatingWindow, _ROW_KEY_MAP
from ui.theme_manager import ThemeManager, ThemeWidgets
from ui.titlebar import TitleBar

# config.toml 的绝对路径（开发模式: 项目根，打包模式: EXE 所在目录）
_CONFIG_PATH = get_project_root() / "config.toml"

# 列宽 / 悬浮窗位置等状态持久化文件
_APP_STATE_PATH = get_project_root() / ".app_state.json"
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

    def __init__(self, items: list[str], parent: QTableWidget | None = None) -> None:
        """初始化委托。

        参数:
            items  — 下拉选项列表，如 ["是", "否"]
            parent — 所属的 QTableWidget（用于生命周期管理）
        """
        super().__init__(parent)
        self._items = items

    def createEditor(self, parent_widget, _option, _index) -> QComboBox:
        """创建编辑器：一个非可编辑的 QComboBox。

        setMaxVisibleItems(len(items)) — 弹出列表只预留足够显示所有选项的高度，
                                         避免默认 maxVisibleItems=10 导致大量留白。
        activated 信号 — 仅在用户从弹出列表中选择时触发，不会在 setEditorData 中误触发。
        commitData + closeEditor — 选择后立即提交数据并关闭编辑器（无需额外点击）。
        """
        combo = QComboBox(parent_widget)
        combo.addItems(self._items)
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
        """更新状态栏消息（左下角的文字）。"""
        self._status_label.setText(msg)

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

    def mouseDoubleClickEvent(self, event) -> None:
        """双击边缘区域不处理（仅标题栏双击可自定义，当前为空实现）。"""
        if self._edge_at(event.globalPosition().toPoint()):
            return                         # 边缘双击 = 忽略
        super().mouseDoubleClickEvent(event)

    # =========================================================================
    # 颜色工具方法（用于手动按钮的动态变色）
    #
    # 手动按钮的颜色随对局阶段切换:
    #   阶段0（硬币）→ 橙色  阶段1（先后攻）→ 蓝色  阶段2（胜负）→ 绿/红
    #
    # _btn_style 生成完整的按钮 QSS（含 hover/pressed/disabled 状态），
    # 用于 setStyleSheet() 直接覆盖按钮外观。
    # =========================================================================

    @staticmethod
    def _parse_hex(hex_color: str) -> tuple[int, int, int]:
        """将 #RRGGBB 解析为 (r, g, b) 整数元组。"""
        return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))

    @classmethod
    def _lighter(cls, hex_color: str, factor: float = 0.25) -> str:
        """将颜色向白色方向提亮，用于 hover 状态。"""
        r, g, b = cls._parse_hex(hex_color)
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    @classmethod
    def _darker(cls, hex_color: str, factor: float = 0.15) -> str:
        """将颜色向黑色方向加深，用于 pressed 状态。"""
        r, g, b = cls._parse_hex(hex_color)
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        return f"#{r:02x}{g:02x}{b:02x}"

    @classmethod
    def _readable_on(cls, hex_color: str) -> str:
        """根据底色亮度自动选择易读的文字色: 浅底用深紫灰，深底用白。

        luma 公式: 0.299×R + 0.587×G + 0.114×B（人眼对绿色最敏感）
        luma > 170 → 亮底 → 深色文字
        luma ≤ 170 → 暗底 → 白色文字
        """
        r, g, b = cls._parse_hex(hex_color)
        luma = (0.299 * r + 0.587 * g + 0.114 * b)
        return "#4a3a52" if luma > 170 else "#ffffff"

    def _btn_style(self, bg: str, *, padding: str = "4px 14px") -> str:
        """生成手动按钮的完整 QSS 样式（含 hover/pressed/disabled 状态）。

        根据主题是否有按钮纹理，生成两种不同的 QSS:

        A) 有按钮纹理（macaron 主题）:
           问题: 全局 QSS 把 watercolor 纹理设为了按钮背景，手动按钮的语义色
                 （如绿色=胜）会被纹理覆盖，只露出边框一圈颜色。
           解决: 用 CSS 的 background 简写属性（不是 background-color），
                 一次性清除所有 background 子属性（包括 background-image），
                 彻底覆盖水彩纹理。
           border-radius: 12px — 和 macaron 的 QSS 一致

        B) 无按钮纹理（dark/light 主题）:
           直接用 background-color 设纯色即可。
           border-radius: 6px — 和 dark/light 的 QSS 一致
        """
        button_texture = self._tm.pixmap_paths.get("QPushButton") if self._tm.pixmap_paths else None

        if button_texture:
            # ---- 情况 A: macaron，用 background 简写覆盖水彩纹理 ----
            text_color = self._readable_on(bg)
            hover_bg = self._lighter(bg, 0.12)
            pressed_bg = self._darker(bg, 0.08)
            border_disabled = self._tm.colors.get("border_disabled", "#f5eef4")
            text_disabled = self._tm.colors.get("text_disabled", "#d5ccd8")
            return (
                "QPushButton { "
                f"background: {bg}; "          # 简写，清除纹理
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
                f"background: {self._tm.colors.get('button_disabled_bg', 'rgba(245,238,244,220)')}; "
                f"color: {text_disabled}; "
                f"border-color: {border_disabled}; "
                "}"
            )

        # ---- 情况 B: dark/light，用 background-color ----
        border = self._tm.colors.get("border", "#dcdde1")
        hover_bg = self._lighter(bg)
        disabled_bg = self._tm.colors.get("button_disabled_bg", "#9E9E9E")
        disabled_color = self._tm.colors.get("text_disabled", "#e0e0e0")
        disabled_border = self._tm.colors.get("border_disabled", "#888")
        return (
            f"QPushButton {{ background-color: {bg}; color: white; "
            f"font-weight: bold; padding: {padding}; border-radius: 6px; "
            f"border: 1px solid {border}; }}"
            f"QPushButton:hover {{ background-color: {hover_bg}; "
            f"border-color: {hover_bg}; }}"
            f"QPushButton:disabled {{ background-color: {disabled_bg}; "
            f"color: {disabled_color}; border-color: {disabled_border}; }}"
        )

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

        # ---- 2. 初始化主题管理器 ----
        self._tm = ThemeManager(self._config)

        # ---- 3. 初始化活跃 CSV 文件 ----
        init_active_csv_from_config()

        # ---- 4. 运行时状态变量 ----
        self._worker: Any = None              # 后台识别线程（StatsWorker）
        self._wait_timer: QTimer | None = None# 等待游戏启动的轮询定时器
        self._info_timer: QTimer | None = None# 右下角信息标签刷新定时器
        self._stage: int = 0                  # 统一阶段: 0=等硬币, 1=等先后攻, 2=等胜负
        self._coin_cache: str = ""            # 硬币结果缓存（"win"/"lose"）
        self._turn_cache: str = ""            # 先后攻结果缓存（"first"/"second"）
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
        self._stats_table      = _require_widget(content.findChild(QTableWidget, "stats_table"), "stats_table")
        self._record_table     = _require_widget(content.findChild(QTableWidget, "record_table"), "record_table")
        self._btn_reload       = _require_widget(content.findChild(QPushButton, "btn_reload"), "btn_reload")
        self._btn_copy         = _require_widget(content.findChild(QPushButton, "btn_copy"), "btn_copy")
        self._btn_delete_last  = _require_widget(content.findChild(QPushButton, "btn_delete_last"), "btn_delete_last")
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
        self._btn_copy.clicked.connect(self._copy_to_clipboard)
        self._btn_delete_last.clicked.connect(self._on_delete_last)
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
        # 列5: 赢硬币 (是/否)
        self._record_table.setItemDelegateForColumn(5, ComboDelegate(["是", "否"], self._record_table))
        # 列6: 先后攻 (先攻/后攻)
        self._record_table.setItemDelegateForColumn(6, ComboDelegate(["先攻", "后攻"], self._record_table))
        # 列7: 结果 (胜/负)
        self._record_table.setItemDelegateForColumn(7, ComboDelegate(["胜", "负"], self._record_table))
        # 列4: 对方卡组 (可编辑下拉 — 预设值来自 config.toml)
        opponent_presets: list[str] = self._config.get("opponent_decks", {}).get("presets", [])
        self._record_table.setItemDelegateForColumn(4, EditableComboDelegate(opponent_presets, self._record_table))

        # ---- 16. 记录表格编辑 → CSV 同步 ----
        self._record_table.cellChanged.connect(self._on_record_cell_changed)

        # QSplitter 拉伸比例（统计表格 2 : 记录表格 3）
        self._splitter.setStretchFactor(0, 2)
        self._splitter.setStretchFactor(1, 3)

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
            self._btn_style(self._theme_colors()["start_bg"], padding="6px 20px")
        )

        # ---- 20. 构建主题控件引用容器（传给 ThemeManager） ----
        self._theme_widgets = ThemeWidgets(
            stats_table=self._stats_table,
            record_table=self._record_table,
            btn_start=self._btn_start,
            btn_stop=self._btn_stop,
            btn_delete_last=self._btn_delete_last,
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

        # ---- 23. 延迟检查新版本（3 秒后静默检查） ----
        QTimer.singleShot(3000, self._check_update)

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

    def _on_load_data(self) -> None:
        """弹出文件对话框切换活跃 CSV 数据文件。

        运行时切换 CSV 需用户确认（避免当前对局记录写入错误文件）。
        选择后切换活跃文件并刷新所有表格。
        """
        if self._worker is not None:
            if not self._ask_yes_no(
                "切换数据文件",
                "识别正在运行，切换数据文件可能导致\n当前对局记录写入错误的文件。\n\n确定要切换吗？",
            ):
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
            self._btn_style(self._theme_colors()["warning_bg"], padding="6px 20px")
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
        self._btn_start.setStyleSheet(self._btn_style(colors["start_bg"], padding="6px 20px"))
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

        self._worker = StatsWorker()
        self._worker.status_update.connect(self._on_status)
        self._worker.coin_win_detected.connect(self._on_coin_win_detected)
        self._worker.turn_detected.connect(self._on_turn_detected)
        self._worker.result_detected.connect(self._on_result_detected)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))

        self._worker.start()                     # QThread.start() → 后台线程执行 run()

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
            self._worker.wait(500)

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
        self._show_status(msg)
        if msg.startswith("程序已关闭"):
            self._btn_start.setEnabled(True)
            self._btn_stop.setEnabled(False)
            self._unlock_deck()
            self._enable_bottom_buttons()

    def _on_coin_win_detected(self, coin_win: str) -> None:
        """自动识别到硬币结果 → 缓存并推进到阶段1。

        仅当手动尚未抢先选择时生效（_stage == 0 才处理）。
        手动按钮在自动识别后也需要更新（文字从"赢/输硬币"变成"先攻/后攻"）。
        """
        if self._stage != 0:
            return
        self._coin_cache = coin_win
        self._stage = 1
        self._update_manual_buttons()
        coin_text = "赢硬币" if coin_win == "win" else "输硬币"
        self._show_status(f"已识别: {coin_text} — 等待先后攻…")

    def _on_turn_detected(self, turn: str) -> None:
        """自动识别到先后攻 → 缓存并推进到阶段2。

        仅当手动尚未抢先选择时生效（_stage == 1 才处理）。
        注意: 此时卡组名直接从输入框读取（不缓存），因为用户可能在识别期间
               修改了卡组名，放在写入 CSV 时再读可以拿到最新值。
        """
        if self._stage != 1:
            return
        self._turn_cache = turn
        self._stage = 2
        self._update_manual_buttons()
        turn_text = "先攻" if turn == "first" else "后攻"
        self._show_status(f"已识别: {turn_text} — 等待胜负…")

    def _on_result_detected(self, result: str) -> None:
        """自动识别到胜负 → 取统一缓存写入 CSV，完成一局对局记录。

        仅当手动尚未抢先选择时生效（_stage == 2 才处理）。
        写入 CSV 后重置状态机回到阶段0，等待下一局。
        """
        if self._stage != 2:
            return
        add_record(coin_win=self._coin_cache, turn=self._turn_cache,
                   result=result, deck=self._deck_input.text().strip())
        self._reset_stage()
        self._reload_tables()
        result_text = "胜" if result == "win" else "负"
        self._show_status(f"已记录: {result_text} — 等待下一局…")

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
        if self._stage == 0:
            # 阶段0: 选择赢硬币/输硬币
            self._coin_cache = side
            self._stage = 1
            self._update_manual_buttons()
            self._sync_worker_stage()
            coin_text = "赢硬币" if side == "win" else "输硬币"
            self._show_status(f"手动: {coin_text} — 请选择先后攻")

        elif self._stage == 1:
            # 阶段1: 选择先攻/后攻
            turn = "first" if side == "win" else "second"
            self._turn_cache = turn
            self._stage = 2
            self._update_manual_buttons()
            self._sync_worker_stage()
            turn_text = "先攻" if turn == "first" else "后攻"
            self._show_status(f"手动: {turn_text} — 请选择胜负")

        elif self._stage == 2:
            # 阶段2: 选择胜/负 → 完成一局，写入 CSV
            add_record(coin_win=self._coin_cache, turn=self._turn_cache,
                       result=side, deck=self._deck_input.text().strip())
            self._reset_stage()
            self._sync_worker_stage()
            self._reload_tables()
            result_text = "胜" if side == "win" else "负"
            self._show_status(f"手动添加: {result_text} — 已写入 CSV")

    def _on_undo(self) -> None:
        """撤销上一阶段的选择，逐级回退并同步 worker。"""
        if self._stage == 1:
            self._coin_cache = ""                # 清除硬币缓存
            self._stage = 0                      # 回到阶段0
        elif self._stage == 2:
            self._turn_cache = ""                # 清除先后攻缓存
            self._stage = 1                      # 回到阶段1
        self._update_manual_buttons()
        self._sync_worker_stage()
        label = {0: "硬币", 1: "先后攻"}[self._stage]
        self._show_status(f"已撤销到: {label}")

    def _sync_worker_stage(self) -> None:
        """将当前 _stage 同步到后台工作线程的状态机。

        这是手动→自动联动的关键: 手动录入后，自动识别从新状态继续。
        例如手动选择了"赢硬币"→ worker 直接从 WAITING_TURN 状态开始检测先后攻。
        """
        if self._worker is not None:
            self._worker.jump_to(self._stage)

    def _reset_stage(self) -> None:
        """重置所有阶段到初始状态（一局完成后调用）。"""
        self._stage = 0
        self._coin_cache = ""
        self._turn_cache = ""
        self._update_manual_buttons()

    def _update_manual_buttons(self) -> None:
        """根据当前 _stage 更新手动按钮的文字、颜色及撤销按钮可见性。

        _stage==0: "赢硬币" / "输硬币" (橙色), 撤销按钮隐藏
        _stage==1: "先攻"   / "后攻"   (蓝色), 撤销按钮可见
        _stage==2: "胜"     / "负"     (绿/红), 撤销按钮可见
        """
        colors = self._theme_colors()
        if self._stage == 0:
            left_text, right_text = "赢硬币", "输硬币"
            left_color = right_color = colors["coin"]          # 橙色
            self._btn_undo.setVisible(False)                   # 阶段0无撤销对象
        elif self._stage == 1:
            left_text, right_text = "先攻", "后攻"
            left_color = right_color = colors["turn"]          # 蓝色
            self._btn_undo.setVisible(True)
        else:
            left_text, right_text = "胜", "负"
            left_color, right_color = colors["win"], colors["lose"]  # 绿/红
            self._btn_undo.setVisible(True)

        self._btn_manual_win.setText(left_text)
        self._btn_manual_win.setStyleSheet(self._btn_style(left_color))
        self._btn_manual_lose.setText(right_text)
        self._btn_manual_lose.setStyleSheet(self._btn_style(right_color))

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
        渲染: 所有单元格居中，"合计"行粗体。
        完成后同步刷新悬浮窗内容。
        """
        records = load_records()
        stats = compute_stats(records)

        self._stats_table.setRowCount(len(stats))
        for row_idx, row_data in enumerate(stats):
            for col_idx, col_name in enumerate(STATS_COLUMNS):
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
            save_records(records)            # 全量写回
            self._refresh_stats_table()      # 刷新统计

    # =========================================================================
    # 删除最后记录
    # =========================================================================

    def _on_delete_last(self) -> None:
        """删除最后一条对战记录，需用户确认。

        确认后加载 CSV → 删除最后一条 → 写回 → 刷新表格。
        记录为空时静默忽略。
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

        if not self._ask_yes_no("确认删除", f"确定要删除最后一条记录吗？\n\n{detail}"):
            return

        records.pop()
        save_records(records)
        self._reload_tables()
        self._show_status(f"已删除最后记录: {detail}")

    # =========================================================================
    # 悬浮窗管理
    #
    # 悬浮窗是一个独立的半透明顶层窗口，显示当前卡组的关键统计数据。
    # 用户可拖拽移动，位置会持久化到 .app_state.json。
    # =========================================================================

    def _on_toggle_float(self) -> None:
        """打开/关闭悬浮统计窗。"""
        if self._float_window is not None:
            # 关闭悬浮窗
            self._save_float_window_pos()
            self._float_window.close()
            self._float_window = None
            self._btn_float.setText("悬浮窗")
            return

        # 打开悬浮窗
        cfg = self._config.get("floating_window", {})
        rows = cfg.get("rows")  # 空列表或 None 都视为使用默认
        self._float_window = FloatingWindow(rows=rows if rows else None)
        float_bg = None
        if cfg.get("use_theme_bg", False) and self._tm.pixmap_paths:
            float_bg = self._tm.pixmap_paths.get("__float_bg__")
        self._float_window.update_style(cfg, float_bg_path=float_bg)
        self._refresh_float_window()                   # 填入当前统计数据
        self._restore_float_window_pos()               # 恢复上次位置
        self._float_window.show()
        self._btn_float.setText("关闭悬浮")

    def _save_float_window_pos(self) -> None:
        """将悬浮窗当前位置保存到 .app_state.json。"""
        if self._float_window is None:
            return
        try:
            with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            saved = {}
        pos = self._float_window.pos()
        saved["float_pos"] = [pos.x(), pos.y()]
        with open(_APP_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False, indent=2)

    def _restore_float_window_pos(self) -> None:
        """从 .app_state.json 恢复悬浮窗位置。

        恢复逻辑:
            1. 读取保存的位置 → 如果坐标合理（≥ -1000）则恢复
            2. 否则居中放置在主屏幕上
        """
        try:
            with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            pos = saved.get("float_pos")
            if pos and len(pos) == 2 and pos[0] >= -1000 and pos[1] >= -1000:
                self._float_window.move(pos[0], pos[1])
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        # 兜底: 主屏幕中央
        screen = QApplication.primaryScreen()
        if screen is not None and self._float_window is not None:
            geo = screen.availableGeometry()
            sz = self._float_window.size()
            self._float_window.move(
                geo.x() + (geo.width() - sz.width()) // 2,
                geo.y() + (geo.height() - sz.height()) // 2,
            )

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
    # 版本更新检查
    # =========================================================================

    def _check_update(self) -> None:
        """从 GitHub Releases API 获取最新版本号，与当前 VERSION 比较。

        工作原理：
            1. 请求 api.github.com/repos/learbox/mdstats_py/releases/latest
            2. GitHub 返回最新 Release 的 JSON，其中 tag_name 即版本号（如 "1.5.2"）
            3. 去掉 tag_name 前面的 "v" → 和本地的 VERSION 常量比
            4. 不同则状态栏提示"有新版本 vX.Y.Z"

        为什么用 urllib 不用 requests？
            urllib 是 Python 自带标准库，无需安装任何第三方包。
            请求量极小（启动一次），不需要 requests 的高级功能。

        异常处理：
            - 网络不通 → 静默跳过（用户离线也能正常使用程序）
            - API 超限 → GitHub 公开仓库不限次数，但加了 timeout=5 秒以防万一
            - JSON 解析失败 → 静默跳过
        """
        try:
            import urllib.request, json

            url = "https://api.github.com/repos/learbox/mdstats_py/releases/latest"
            req = urllib.request.Request(url)
            # GitHub API v3 要求设置 Accept 和 User-Agent 头
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "MDStats")

            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            latest = data.get("tag_name", "").lstrip("v")
            if latest and latest != VERSION:
                self._show_status(f"有新版本 v{latest}，请前往 GitHub 下载")
        except Exception:
            pass  # 网络不通或 API 限制，静默跳过

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
            is_single_deck = True
        else:
            is_single_deck = False

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

    def _on_settings(self) -> None:
        """打开图形化设置弹窗，确定后自动写配置 + 重载。"""
        from ui.config_dialog import ConfigDialog
        bg_path = None
        close_hover = "#e74c3c"
        if self._tm.pixmap_paths:
            bg_path = self._tm.pixmap_paths.get("__settings_bg__")
        if self._tm.titlebar_cfg:
            close_hover = self._tm.titlebar_cfg.get("btn_close_hover", close_hover)
        dialog = ConfigDialog(self._config, self,
                              bg_path=bg_path,
                              close_hover=close_hover,
                              assets_dir=self._tm.assets_dir,
                              widget_bg=self._tm.colors.get("widget_bg", "#ffffff"))
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
        old_theme_name = self._config.get("appearance", {}).get("theme", "dark")
        self._config = load_config()                       # 重新读取 config.toml
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
            if new_rows:
                self._float_window.set_rows(new_rows)
            float_bg = None
            if new_cfg.get("use_theme_bg", False) and self._tm.pixmap_paths:
                float_bg = self._tm.pixmap_paths.get("__float_bg__")
            self._float_window.update_style(new_cfg, float_bg_path=float_bg)
            self._refresh_float_window()

        # Worker 正在运行 → 停止后用新配置重启
        worker_was_running = self._worker is not None
        if worker_was_running:
            self._worker.stop()
            self._worker.wait(500)
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
    # 所有持久化数据存储在 .app_state.json 中，格式:
    #   {"stats": [列宽...], "record": [列宽...], "main_pos": [x, y], "float_pos": [x, y]}
    #
    # 保存时机: 窗口关闭（closeEvent）
    # 恢复时机: 窗口首次显示（showEvent）
    # =========================================================================

    # 列宽默认值（像素），首次运行在 .app_state.json 不存在时使用
    _DEFAULT_COLUMN_WIDTHS = {
        "stats":  [80, 60, 45, 45, 70, 75, 75, 75, 85, 85, 80, 75, 70, 70, 75, 75],
        "record": [ 0, 115, 90, 75, 80, 65, 70, 50],
    }

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
        """从 .app_state.json 恢复列宽。

        恢复策略:
            1. 读取保存的列宽数组
            2. 逐列应用，宽度的最小值 = 20px（防止太窄看不见）
            3. 如果保存数据不足（列数增加了），后面的用默认值
            4. 最后一列由 stretchLastSection 管理，不在此处理
        """
        try:
            with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            saved = {}

        for table, key, defaults in [
            (self._stats_table, "stats", self._DEFAULT_COLUMN_WIDTHS["stats"]),
            (self._record_table, "record", self._DEFAULT_COLUMN_WIDTHS["record"]),
        ]:
            widths = saved.get(key, [])
            for col in range(table.columnCount() - 1):  # 跳过最后一列
                if widths and col < len(widths):
                    table.setColumnWidth(col, max(20, widths[col]))
                elif col < len(defaults):
                    table.setColumnWidth(col, defaults[col])

    def _save_column_widths(self) -> None:
        """保存绝对列宽到 .app_state.json。

        跳过最后一列（由 stretchLastSection 自动管理宽度）。
        """
        try:
            with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        for table, key in [(self._stats_table, "stats"), (self._record_table, "record")]:
            data[key] = [table.columnWidth(c) for c in range(table.columnCount() - 1)]
        with open(_APP_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # =========================================================================
    # 窗口关闭事件
    # =========================================================================

    def closeEvent(self, event: Any) -> None:
        """窗口关闭时保存所有持久化状态，安全停止后台线程和定时器。

        合并读写：一次读 .app_state.json → 写入全部状态 → 一次写回，
        取代原来的三次独立 I/O。
        """
        # ---- 合并状态保存（一次读 + 一次写） ----
        try:
            with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        p = self.pos()
        data["main_pos"] = [p.x(), p.y()]
        if self._float_window is not None:
            fp = self._float_window.pos()
            data["float_pos"] = [fp.x(), fp.y()]
        data["stats"] = [self._stats_table.columnWidth(c)
                         for c in range(self._stats_table.columnCount() - 1)]
        data["record"] = [self._record_table.columnWidth(c)
                          for c in range(self._record_table.columnCount() - 1)]
        with open(_APP_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # ---- 停止所有定时器和工作线程 ----
        if self._info_timer is not None:
            self._info_timer.stop()
            self._info_timer = None
        if self._wait_timer is not None:
            self._wait_timer.stop()
            self._wait_timer = None
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(500)           # 线程在 interval 秒内退出（默认 0.3s），500ms 绰绰有余
        event.accept()

    def _restore_main_window_pos(self) -> None:
        """从 .app_state.json 恢复主窗口位置。

        坐标验证: x ≥ -100, y ≥ -100（越界或负太多说明是异常值，不恢复）。
        """
        try:
            with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            pos = data.get("main_pos")
            if pos and len(pos) == 2 and pos[0] >= -100 and pos[1] >= -100:
                self.move(pos[0], pos[1])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_main_window_pos(self) -> None:
        """保存主窗口位置到 .app_state.json。"""
        try:
            with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        p = self.pos()
        data["main_pos"] = [p.x(), p.y()]
        with open(_APP_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
