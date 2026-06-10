"""设置弹窗 — 图形化编辑 config.toml，代替手动编辑文本文件。

================================================================================
架构

    ConfigDialog(QDialog)
      ├── 自定义标题栏（拖拽 + 关闭按钮）
      ├── QTabWidget（5 个标签页）
      │   ├── 识别 — 截图间隔、匹配阈值
      │   ├── 外观 — 主题、窗口尺寸
      │   ├── 剪贴板 — 竖排、范围、列选择
      │   ├── 悬浮窗 — 尺寸/颜色/透明度/字体/行选择
      │   └── 数据 — 卡组预设、分文件
      ├── 预览区 — 悬浮窗小样
      └── 按钮栏 — [取消] [确定]

工作流程:
    1. 用户点击主窗口"设置" → _on_settings() → ConfigDialog(config).exec()
    2. 弹窗读取 config.toml → 填入各控件
    3. 用户修改 → 点"确定" → 写回 config.toml → 调用 _on_reload_config()
    4. 点"取消"或 × → 丢弃修改

使用的 Qt 概念速查:
    QDialog      — 模态弹窗（打开时阻断主窗口操作）
    QTabWidget   — 标签页容器，顶部显示页签切换
    QSpinBox     — 整数输入框（自带上下箭头）
    QDoubleSpinBox — 小数输入框
    QSlider      — 滑块控件
    QColorDialog — 系统取色器弹窗
    QFontComboBox — 系统字体下拉列表
    QListWidget  — 可滚动的列表控件
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QPoint, QTranslator, QLibraryInfo, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDoubleSpinBox, QFontComboBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QRadioButton, QSlider,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget, QButtonGroup,
)

from src.config import get_project_root
from ui.floating_window import _ROW_KEY_MAP, _DEFAULT_ROWS

# 加载 Qt 内置中文翻译（让取色器等系统弹窗显示中文，翻译文件缺失时静默跳过）
_qt_translator = QTranslator()
if _qt_translator.load(
    QLibraryInfo.location(QLibraryInfo.LibraryPath.TranslationsPath) + "/qt_zh_CN.qm"
):
    if _qapp := QApplication.instance():
        _qapp.installTranslator(_qt_translator)

_BUILTIN_THEME = "(内置亮色)"


# =============================================================================
# ColorButton — 色块按钮，点击弹出系统取色器
# =============================================================================

# =============================================================================
# ColorButton — 色块按钮
#
# 为什么不用 QLineEdit 让用户输入 #RRGGBB？
#   十六进制颜色码对普通用户极不友好——需要知道红绿蓝各两位、
#   大小写、要不要 # 号。色块按钮 + 取色器能做到"所见即所得"。
#
# 工作原理：
#   1. 按钮背景色 = 当前选中的颜色（用户一眼就知道现在是什么色）
#   2. 点击按钮 → 弹出系统取色器（QColorDialog）
#   3. 用户在取色器中选色 → 按钮背景色即时更新
# =============================================================================

class ColorButton(QPushButton):
    """色块按钮：显示当前颜色，点击弹出取色器。"""

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color                # 当前选中的颜色（QColor 对象）
        self.setFixedSize(48, 28)          # 固定尺寸：宽 48px，高 28px
        self.setCursor(Qt.CursorShape.PointingHandCursor)  # 手指光标提示可点击
        self._update_style()               # 涂上初始颜色
        self.clicked.connect(self._pick)    # 点击 → 弹出取色器

    def _update_style(self) -> None:
        """把按钮背景涂成当前颜色。"""
        c = self._color
        # name() 返回 #RRGGBB 格式的十六进制字符串
        self.setStyleSheet(
            f"QPushButton {{ background-color: {c.name()}; "
            f"border: 1px solid #888; border-radius: 4px; }}"
        )

    def _pick(self) -> None:
        """弹出 Qt 取色器弹窗，用户选色后更新按钮。"""
        # DontUseNativeDialog — 用 Qt 自己的取色器而不是 Windows 原生版本，
        #   因为 Qt 版本的 UI 可以被我们之前加载的中文翻译文件汉化
        dlg = QColorDialog(self._color, self)
        dlg.setWindowTitle("选择颜色")
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._color = dlg.currentColor()
            self._update_style()

    def color(self) -> QColor:
        """获取当前选中的颜色（供外部读取写入配置）。"""
        return self._color

    def set_color(self, color: QColor) -> None:
        """外部设置颜色（如初始化时从 config.toml 读入）。"""
        self._color = color
        self._update_style()


# =============================================================================
# DualListWidget — 双列选择 + 排序控件
# =============================================================================

# =============================================================================
# DualListWidget — 双列选择 + 排序控件
#
# 这个控件用于「剪贴板列选择」和「悬浮窗行选择」两个标签页。
# 界面类似：
#   ┌──────────┐     ┌──────────┐
#   │ 可选      │  →  │ 已选      │
#   │ 先攻次数  │     │ 卡组      │
#   │ 后攻次数  │  ←  │ 对局数    │
#   │ ...      │  ↑  │ 胜/负     │
#   └──────────┘  ↓  └──────────┘
# =============================================================================

class DualListWidget(QWidget):
    """双列选择列表：左边可选，右边已选，中间箭头按钮移动和排序。

    箭头按钮用 QPainter 绘制图标而非文字，避免 QSS 字体覆盖导致
    Unicode 箭头（→←↑↓）无法正常渲染。
    """

    @staticmethod
    def _make_arrow(direction: str) -> QIcon:
        """用 QPainter 绘制杆+箭头风格的图标（16×16 px），模仿 →←↑↓。"""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPen
        pix = QPixmap(16, 16)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(Qt.GlobalColor.black, 1)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if direction == "right":
            p.drawLine(QPointF(3, 8), QPointF(12, 8))        # 杆
            p.drawLine(QPointF(12, 8), QPointF(8.5, 4.5))     # 上箭头
            p.drawLine(QPointF(12, 8), QPointF(8.5, 11.5))    # 下箭头
        elif direction == "left":
            p.drawLine(QPointF(13, 8), QPointF(4, 8))
            p.drawLine(QPointF(4, 8), QPointF(7.5, 4.5))
            p.drawLine(QPointF(4, 8), QPointF(7.5, 11.5))
        elif direction == "up":
            p.drawLine(QPointF(8, 13), QPointF(8, 4))
            p.drawLine(QPointF(8, 4), QPointF(4.5, 7.5))
            p.drawLine(QPointF(8, 4), QPointF(11.5, 7.5))
        else:  # down
            p.drawLine(QPointF(8, 3), QPointF(8, 12))
            p.drawLine(QPointF(8, 12), QPointF(4.5, 8.5))
            p.drawLine(QPointF(8, 12), QPointF(11.5, 8.5))
        p.end()
        return QIcon(pix)

    def __init__(self, available: list[str], selected: list[str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 左边：可选列表
        left_v = QVBoxLayout()
        left_v.addWidget(QLabel("可选"))
        self._left = QListWidget()
        left_v.addWidget(self._left)
        layout.addLayout(left_v)

        # 中间：方向按钮（图标由 QPainter 绘制，不受 QSS 字体影响）
        mid = QVBoxLayout()
        mid.addStretch()
        self._btn_r = QPushButton()
        self._btn_r.setIcon(self._make_arrow("right"))
        self._btn_r.setFixedSize(36, 28)
        self._btn_r.setToolTip("添加到已选")
        self._btn_r.clicked.connect(self._move_right)
        mid.addWidget(self._btn_r)
        self._btn_l = QPushButton()
        self._btn_l.setIcon(self._make_arrow("left"))
        self._btn_l.setFixedSize(36, 28)
        self._btn_l.setToolTip("移回可选")
        self._btn_l.clicked.connect(self._move_left)
        mid.addWidget(self._btn_l)
        mid.addSpacing(12)
        self._btn_u = QPushButton()
        self._btn_u.setIcon(self._make_arrow("up"))
        self._btn_u.setFixedSize(36, 28)
        self._btn_u.setToolTip("上移")
        self._btn_u.clicked.connect(self._move_up)
        mid.addWidget(self._btn_u)
        self._btn_d = QPushButton()
        self._btn_d.setIcon(self._make_arrow("down"))
        self._btn_d.setFixedSize(36, 28)
        self._btn_d.setToolTip("下移")
        self._btn_d.clicked.connect(self._move_down)
        mid.addWidget(self._btn_d)
        mid.addStretch()
        layout.addLayout(mid)

        # 右边：已选列表
        right_v = QVBoxLayout()
        right_v.addWidget(QLabel("已选（可排序）"))
        self._right = QListWidget()
        self._right.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        right_v.addWidget(self._right)
        layout.addLayout(right_v)

        for item in available:
            if item not in selected:
                self._left.addItem(item)
        for item in selected:
            self._right.addItem(item)

    def _move_right(self) -> None:
        for item in self._left.selectedItems():
            self._right.addItem(item.text())
            self._left.takeItem(self._left.row(item))

    def _move_left(self) -> None:
        for item in self._right.selectedItems():
            self._left.addItem(item.text())
            self._right.takeItem(self._right.row(item))

    def _move_up(self) -> None:
        row = self._right.currentRow()
        if row > 0:
            item = self._right.takeItem(row)
            self._right.insertItem(row - 1, item)
            self._right.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self._right.currentRow()
        if row < self._right.count() - 1:
            item = self._right.takeItem(row)
            self._right.insertItem(row + 1, item)
            self._right.setCurrentRow(row + 1)

    def get_selected(self) -> list[str]:
        return [self._right.item(i).text()
                for i in range(self._right.count())]


# =============================================================================
# ConfigDialog
# =============================================================================

class ConfigDialog(QDialog):
    """设置弹窗，5 标签页 + 确定/取消。"""

    config_saved = Signal()

    _ALL_KEYS = list(_ROW_KEY_MAP.keys())

    def __init__(self, config: dict[str, Any],
                 parent: QWidget | None = None,
                 bg_path: str | None = None,
                 close_hover: str = "#e74c3c",
                 assets_dir: Path | None = None,
                 widget_bg: str = "#ffffff",
                 main_bg: str = "#f0f0f0") -> None:
        super().__init__(parent)
        self._config = config
        self._close_hover = close_hover
        self._assets_dir = assets_dir
        self._bg_pixmap: QPixmap | None = None
        if bg_path:
            pm = QPixmap(bg_path)
            if not pm.isNull():
                self._bg_pixmap = pm

        # 把 #RRGGBB 转成 rgba(r,g,b,0.7) 保留 30% 透明度
        r, g, b = int(widget_bg[1:3], 16), int(widget_bg[3:5], 16), int(widget_bg[5:7], 16)
        bg_semi = f"rgba({r},{g},{b},180)"  # alpha≈70%
        self._main_bg = main_bg

        self._dragging = False
        self._drag_start = QPoint()

        self.setWindowTitle("设置")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(660, 540)
        self.resize(680, 560)
        self.setObjectName("configDialog")
        # 对话框底色：有背景图用 widget_bg（图穿透面板），纯色用 main_bg 偏移版
        dialog_bg = widget_bg
        if self._bg_pixmap is None:
            # 双向偏移：浅色变暗、深色变亮，确保任意配色（含纯黑/纯白）都有对比
            mr, mg, mb = int(self._main_bg[1:3], 16), int(self._main_bg[3:5], 16), int(self._main_bg[5:7], 16)
            shift = 5
            dr = mr + shift if mr <= 128 else mr - shift
            dg = mg + shift if mg <= 128 else mg - shift
            db = mb + shift if mb <= 128 else mb - shift
            dialog_bg = f"#{dr:02x}{dg:02x}{db:02x}"
        self.setStyleSheet(
            f"#configDialog {{ background: {dialog_bg}; }}"
            "QGroupBox { background: transparent; border: 1px solid palette(mid);"
            "  border-radius: 6px; margin-top: 8px; padding-top: 16px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; }"
        )
        self._apply_dwm_round_corners()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._make_titlebar())

        self._tabs = QTabWidget()
        # 标签页样式：背景图主题用半透明（透出图片），纯色主题用实色+边框
        if self._bg_pixmap is not None:
            self._tabs.setStyleSheet(
                f"QTabWidget::pane {{ background: {bg_semi}; border: none; }}"
                "QTabBar::tab { background: transparent; padding: 6px 16px; }"
                f"QTabBar::tab:selected {{ background: {widget_bg}; }}"
            )
        else:
            # 纯色主题：对话框用 main_bg，面板用 widget_bg，卡片自然浮现
            self._tabs.setStyleSheet(
                f"QTabWidget::pane {{ background: {widget_bg}; border: none; }}"
                "QTabBar::tab { background: transparent; padding: 6px 16px; }"
                f"QTabBar::tab:selected {{ background: {widget_bg}; }}"
            )
        self._tabs.addTab(self._make_detection_tab(), "识别")
        self._tabs.addTab(self._make_appearance_tab(), "外观")
        self._tabs.addTab(self._make_clipboard_tab(), "剪贴板")
        self._tabs.addTab(self._make_float_tab(), "悬浮窗")
        self._tabs.addTab(self._make_data_tab(), "数据")
        self._tabs.addTab(self._make_notification_tab(), "系统")
        outer.addWidget(self._tabs, 1)
        outer.addWidget(self._make_button_bar())

        self._load_from_config()

    # =========================================================================
    # 标题栏
    # =========================================================================

    def _make_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("configDialogTitle")
        bar.setFixedHeight(36)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 4, 0)

        title = QLabel("  设置")
        title.setStyleSheet("font-size: 13px; font-weight: bold; "
                            "background: transparent; border: none;")
        layout.addWidget(title)
        layout.addStretch()

        # 关闭按钮：复用主标题栏 _TitleBarButton（自带 hover 遮罩和图标填充）
        from ui.titlebar import _TitleBarButton
        assets = self._assets_dir or (get_project_root() / "resource")
        btn_close = _TitleBarButton("title_close", assets, bar)
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {self._close_hover}; "
            f"border-color: {self._close_hover}; }}"
        )
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)
        return bar

    # =========================================================================
    # Tab 1: 识别
    # =========================================================================

    def _make_detection_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(12)

        r = QHBoxLayout()
        r.addWidget(QLabel("截图间隔:"))
        self._interval = QDoubleSpinBox()
        self._interval.setRange(0.1, 10.0)
        self._interval.setSingleStep(0.1)
        self._interval.setSuffix(" 秒")
        self._interval.setToolTip("每隔多久截取一次游戏画面进行识别。\n"
                                   "0.3 秒 = 每秒约 3 次截图，灵敏但 CPU 占用高。\n"
                                   "1.0 秒 = 每秒 1 次截图，省 CPU 但可能漏掉快速闪过的 UI。\n"
                                   "推荐 0.3 ~ 1.0 秒。")
        r.addWidget(self._interval)
        r.addStretch()
        lo.addLayout(r)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("匹配阈值:"))
        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.0, 1.0)
        self._threshold.setSingleStep(0.05)
        self._threshold.setDecimals(2)
        self._threshold.setToolTip("模板匹配置信度阈值 (0~1)。\n"
                                    "0.80 = 匹配度需达 80% 才判定识别成功。\n"
                                    "太高 → 可能频繁漏掉本该识别到的画面。\n"
                                    "太低 → 可能把无关画面误判为匹配。\n"
                                    "推荐 0.75 ~ 0.90。")
        r2.addWidget(self._threshold)
        r2.addStretch()
        lo.addLayout(r2)

        # ---- 保存检测截图 ----
        # 独立开关，与日志模式无关。开启后每次检测到硬币/先后攻/胜负时
        # 自动保存截图到 screenshots/ 目录。下一局开始时自动清除。
        self._save_screenshots_cb = QCheckBox("保存检测截图")
        self._save_screenshots_cb.setToolTip(
            "开启后，每次检测到硬币输赢、先后攻、对局胜负时自动保存截图\n"
            "到 screenshots/ 目录。下一局开始时自动清除上一局的截图。"
        )
        lo.addWidget(self._save_screenshots_cb)

        lo.addStretch()
        return w

    # =========================================================================
    # Tab 2: 系统
    # =========================================================================

    def _make_notification_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(12)

        # ---- 日志模式 ----
        # 日志模式：写日志文件到 logs/，记录内容由下方三个子复选框控制
        log_row = QHBoxLayout()
        self._log_mode_cb = QCheckBox("日志模式")
        self._log_mode_cb.setToolTip("将程序运行信息写入 logs/ 目录。勾选后选择记录范围。")
        log_row.addWidget(self._log_mode_cb)
        self._btn_open_logs = QPushButton("查看日志")
        self._btn_open_logs.setFixedWidth(80)
        self._btn_open_logs.clicked.connect(self._open_logs_dir)
        self._btn_open_logs.setToolTip("在文件资源管理器中打开日志文件夹。")
        log_row.addWidget(self._btn_open_logs)
        log_row.addStretch()
        lo.addLayout(log_row)

        # 日志记录范围 — 三个子复选框，关闭日志模式时自动变灰
        indent = QVBoxLayout()
        indent.setContentsMargins(24, 0, 0, 0)
        self._log_scope_status = QCheckBox("状态栏消息")
        self._log_scope_status.setToolTip("记录所有左下角状态栏的文字内容。")
        indent.addWidget(self._log_scope_status)
        self._log_scope_screenshots = QCheckBox("截图事件")
        self._log_scope_screenshots.setToolTip("记录截图的保存、清除等操作。")
        indent.addWidget(self._log_scope_screenshots)
        self._log_scope_errors = QCheckBox("错误信息")
        self._log_scope_errors.setToolTip("记录所有未捕获的异常和错误。")
        indent.addWidget(self._log_scope_errors)
        lo.addLayout(indent)

        # 主开关切换时联动子复选框的启用/禁用状态
        self._log_mode_cb.toggled.connect(self._on_log_mode_toggled)

        # ---- 系统通知 ----
        self._notify_cb = QCheckBox("对局结束系统通知")
        self._notify_cb.setToolTip(
            "开启后，每局结束时弹出系统气泡通知，\n"
            "显示硬币输赢（含段位升降）、先后手和胜负结果。"
        )
        lo.addWidget(self._notify_cb)

        dur_row = QHBoxLayout()
        dur_row.setContentsMargins(24, 0, 0, 0)
        dur_row.addWidget(QLabel("显示时长:"))
        self._notify_duration = QSpinBox()
        self._notify_duration.setRange(1, 30)
        self._notify_duration.setSuffix(" 秒")
        self._notify_duration.setToolTip("气泡通知在屏幕上的停留时间。")
        dur_row.addWidget(self._notify_duration)
        dur_row.addStretch()
        lo.addLayout(dur_row)

        # ---- 托盘 ----
        self._tray_minimize_cb = QCheckBox("最小化到系统托盘")
        self._tray_minimize_cb.setToolTip(
            "开启后，最小化主窗口时隐藏到系统托盘（悬浮窗不受影响）。\n"
            "右键托盘图标可还原窗口或退出程序。"
        )
        lo.addWidget(self._tray_minimize_cb)

        lo.addStretch()
        return w

    # =========================================================================
    # Tab 3: 外观
    # =========================================================================

    def _make_appearance_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(12)

        # ---- 主题 ----
        r = QHBoxLayout()
        r.addWidget(QLabel("主题:"))
        self._theme_combo = QComboBox()
        self._theme_combo.setToolTip("切换界面配色和字体。\n主题文件在 themes/ 文件夹下。")
        themes_dir = get_project_root() / "themes"
        names = []
        if themes_dir.is_dir():
            for d in themes_dir.iterdir():
                if d.is_dir() and (d / "theme.toml").exists():
                    names.append(d.name)
        if names:
            self._theme_combo.addItems(names)
        else:
            self._theme_combo.addItem(_BUILTIN_THEME)
            self._theme_combo.setEnabled(False)
        r.addWidget(self._theme_combo)
        self._theme_combo.currentIndexChanged.connect(self._update_font_display)
        r.addStretch()
        lo.addLayout(r)

        # ---- 字体栈 ----
        g_font = QGroupBox("当前主题的字体")
        g_font.setToolTip(
            "字体栈是多个字体组成的优先级列表。\n"
            "Qt 从第一个开始尝试，如果系统没装就试下一个，直到找到可用的。\n"
            "因此同一个主题在 Windows 和 macOS 上可能显示不同字体——这是正常行为。"
        )
        from PySide6.QtWidgets import QScrollArea
        fl = QVBoxLayout(g_font)
        scroll = QScrollArea()
        scroll.setMaximumHeight(100)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._font_stack_label = QLabel()
        self._font_stack_label.setStyleSheet("font-size: 12px; background: transparent;")
        self._font_stack_label.setWordWrap(True)
        scroll.setWidget(self._font_stack_label)
        fl.addWidget(scroll)

        # 字体预览
        self._font_preview = QLabel("字体预览 ABC 123 中文示例 胜负 先攻 后攻")
        self._font_preview.setStyleSheet(
            "font-size: 16px; padding: 8px; background: transparent;"
            "border: 1px dashed #888; border-radius: 4px;"
        )
        fl.addWidget(self._font_preview)
        lo.addWidget(g_font)

        # ---- 字体选择器 ----
        fr = QHBoxLayout()
        fr.addWidget(QLabel("更换字体:"))
        self._font_picker = QComboBox()
        self._font_picker.setMinimumWidth(180)
        self._font_picker.setToolTip(
            "当前主题字体栈中已安装的字体。\n"
            "选择后点击 [应用] 将其设为栈顶主力字体。\n"
            "修改后自动写入主题文件并重载。"
        )
        fr.addWidget(self._font_picker)
        btn_apply_font = QPushButton("应用")
        btn_apply_font.setFixedWidth(60)
        btn_apply_font.clicked.connect(self._on_apply_font)
        btn_apply_font.setToolTip("将选中的字体写入当前主题的 font_family。")
        fr.addWidget(btn_apply_font)
        fr.addStretch()
        lo.addLayout(fr)

        # ---- 窗口尺寸 ----
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("窗口宽度:"))
        self._win_width = QSpinBox()
        self._win_width.setRange(400, 5000)
        self._win_width.setSuffix(" px")
        self._win_width.setToolTip("主窗口的宽度，修改后下次启动生效。")
        r2.addWidget(self._win_width)
        r2.addStretch()
        lo.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("窗口高度:"))
        self._win_height = QSpinBox()
        self._win_height.setRange(300, 5000)
        self._win_height.setSuffix(" px")
        r3.addWidget(self._win_height)
        r3.addStretch()
        lo.addLayout(r3)

        lo.addStretch()
        self._update_font_display()
        return w

    def _update_font_display(self) -> None:
        """读取当前主题的 font_family，显示字体栈可用性并更新预览。

        流程：
            1. 根据 theme_combo 的当前值找到主题文件夹
            2. 打开 theme.toml，解析出 font_family（如 '"Yozai", "DymonShouXieTi", ...'）
            3. 拆分逗号 → 去掉引号 → 得到 fonts_in_stack 列表
            4. 用 QFontDatabase().families() 获取系统已安装字体列表
            5. 逐个检查栈中字体是否已安装，用 ✓（绿色）/ ✗（灰色）标记
            6. 用栈顶字体渲染预览文字
            7. 同步字体下拉框：只列出已安装的字体供用户选择
        """
        import tomllib

        theme_name = self._theme_combo.currentText()
        if not theme_name or theme_name == _BUILTIN_THEME:
            self._font_stack_label.setText("(内置主题，使用系统默认字体)")
            return

        toml_path = get_project_root() / "themes" / theme_name / "theme.toml"
        if not toml_path.exists():
            return
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, ValueError):
            return
        assets = data.get("assets", {})
        font_family = assets.get("font_family", "")
        if not font_family:
            self._font_stack_label.setText("(未指定字体栈，使用系统默认)")
            return

        # 按逗号拆分字体栈，去掉引号
        fonts_in_stack = [
            f.strip().strip('"')
            for f in font_family.split(",")
        ]
        available = QFontDatabase().families()

        lines = ["字体栈（从高到低优先级）："]
        for f in fonts_in_stack:
            ok = f in available
            mark = "✓" if ok else "✗"
            color = "green" if ok else "gray"
            lines.append(
                f'  <span style="color:{color}">{mark} {f}</span>'
            )
        self._font_stack_label.setText("<br>".join(lines))

        # 预览实际渲染字体
        actual_font = QFont(fonts_in_stack[0] if fonts_in_stack else "")
        self._font_preview.setFont(actual_font)
        # 字体下拉框：只列出本主题字体栈中系统已安装的字体
        self._font_picker.clear()
        for f in fonts_in_stack:
            if f in available:
                self._font_picker.addItem(f)
        if self._font_picker.count() == 0:
            self._font_picker.addItem("(无可用字体)")
            self._font_picker.setEnabled(False)
        else:
            self._font_picker.setEnabled(True)

    def _on_apply_font(self) -> None:
        """把字体下拉框中选中的字体写入当前主题的 font_family 首位。

        操作流程：
            1. 读取当前主题的 theme.toml
            2. 取出 font_family 行（如 '"Yozai", "DymonShouXieTi", "Microsoft YaHei"'）
            3. 把用户选的新字体放到栈顶，保留剩余的字体作为回退栈
            4. 用文本替换的方式写回 theme.toml（不破坏文件其余内容）

        为什么只改第一个字体？
            font_family 是优先级列表——Qt 从第一个开始尝试，找不到就试下一个。
            只替换第一个意味着：如果用户选的字体在他的系统上存在，就用新字体；
            如果不存在（比如换到另一台电脑），自动回退到原来的栈中字体。
        """
        import tomllib

        theme_name = self._theme_combo.currentText()
        if not theme_name or theme_name == _BUILTIN_THEME:
            return

        toml_path = get_project_root() / "themes" / theme_name / "theme.toml"
        if not toml_path.exists():
            return

        new_font = self._font_picker.currentText()
        if not new_font:
            return

        # 读取原主题文件内容
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, ValueError):
            return

        assets = data.get("assets", {})
        old_stack = assets.get("font_family", "")
        if old_stack:
            # 拆出所有字体，去掉引号
            fonts = [f.strip().strip('"') for f in old_stack.split(",")]
            # 去重：移除 new_font 的旧位置（如果有），然后放到栈顶
            rest = [f for f in fonts if f != new_font]
            new_stack = ", ".join(f'"{f}"' for f in [new_font] + rest)
        else:
            new_stack = f'"{new_font}"'

        # 写回 — 简单替换 font_family 行
        text = toml_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("font_family"):
                indent = line[:len(line) - len(line.lstrip())]
                # TOML 值必须是字符串，外层用单引号包裹（内部双引号不需要转义）
                lines[i] = f"{indent}font_family = '{new_stack}'"
                break
        toml_path.write_text("\n".join(lines), encoding="utf-8")

        # 字体改的是 theme.toml，不属于 config.toml，_on_reload_config 检测不到
        # 变化。这里直接通知主窗口重载整个主题，使字体立即生效。
        self.config_saved.emit()
        self._update_font_display()

    # =========================================================================
    # Tab 3: 剪贴板
    # =========================================================================

    def _make_clipboard_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(8)

        g1 = QGroupBox("复制格式")
        g1l = QVBoxLayout(g1)
        self._cb_tsv = QRadioButton("横排 TSV")
        self._cb_vert = QRadioButton("竖排 key: value")
        bg = QButtonGroup(self)
        bg.addButton(self._cb_tsv, 0)
        bg.addButton(self._cb_vert, 1)
        g1l.addWidget(self._cb_tsv)
        g1l.addWidget(self._cb_vert)
        lo.addWidget(g1)

        g2 = QGroupBox("复制范围")
        g2l = QVBoxLayout(g2)
        self._cb_all = QRadioButton("全部卡组")
        self._cb_curr = QRadioButton("仅当前卡组")
        bg2 = QButtonGroup(self)
        bg2.addButton(self._cb_all, 0)
        bg2.addButton(self._cb_curr, 1)
        g2l.addWidget(self._cb_all)
        g2l.addWidget(self._cb_curr)
        lo.addWidget(g2)

        g3 = QGroupBox("要复制的列")
        g3l = QVBoxLayout(g3)
        hint_cb = QLabel("> 添加  < 移除  ^ 上移  v 下移  |  清空已选 = 使用默认项")
        hint_cb.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        g3l.addWidget(hint_cb)
        self._cb_dual = DualListWidget(self._ALL_KEYS, list(_DEFAULT_ROWS))
        g3l.addWidget(self._cb_dual)
        lo.addWidget(g3)

        return w

    # =========================================================================
    # Tab 4: 悬浮窗
    # =========================================================================

    def _make_float_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(8)

        sr = QHBoxLayout()
        sr.addWidget(QLabel("宽度:"))
        self._fw_w = QSpinBox()
        self._fw_w.setRange(100, 1000)
        self._fw_w.setSuffix(" px")
        sr.addWidget(self._fw_w)
        sr.addWidget(QLabel("高度:"))
        self._fw_h = QSpinBox()
        self._fw_h.setRange(100, 1000)
        self._fw_h.setSuffix(" px")
        sr.addWidget(self._fw_h)
        sr.addStretch()
        lo.addLayout(sr)

        br = QHBoxLayout()
        br.addWidget(QLabel("背景色:"))
        self._fw_bg = ColorButton(QColor("#98d4bb"))
        br.addWidget(self._fw_bg)
        br.addWidget(QLabel("透明度:"))
        self._fw_op = QSlider(Qt.Orientation.Horizontal)
        self._fw_op.setRange(0, 100)
        self._fw_op.setFixedWidth(150)
        br.addWidget(self._fw_op)
        self._fw_opl = QLabel("50%")
        self._fw_op.valueChanged.connect(lambda v: self._fw_opl.setText(f"{v}%"))
        br.addWidget(self._fw_opl)
        br.addStretch()
        lo.addLayout(br)

        tr = QHBoxLayout()
        tr.addWidget(QLabel("文字颜色:"))
        self._fw_tc = ColorButton(QColor("#000000"))
        tr.addWidget(self._fw_tc)
        tr.addWidget(QLabel("字号:"))
        self._fw_fs = QSpinBox()
        self._fw_fs.setRange(8, 72)
        tr.addWidget(self._fw_fs)
        tr.addWidget(QLabel("字体:"))
        self._fw_ff = QFontComboBox()
        self._fw_ff.setMinimumWidth(160)
        tr.addWidget(self._fw_ff)
        tr.addStretch()
        lo.addLayout(tr)

        g = QGroupBox("显示的数据行")
        gl = QVBoxLayout(g)
        hint_fw = QLabel("> 添加  < 移除  ^ 上移  v 下移  |  清空已选 = 使用默认项")
        hint_fw.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        gl.addWidget(hint_fw)
        self._fw_dual = DualListWidget(self._ALL_KEYS, list(_DEFAULT_ROWS))
        gl.addWidget(self._fw_dual)
        lo.addWidget(g)

        self._use_theme_bg = QCheckBox("使用主题背景图")
        self._use_theme_bg.setToolTip(
            "勾选后优先使用主题文件夹中的 float_bg 图片。\n"
            "图片不存在时自动回退到下方设置的纯色。"
        )
        lo.addWidget(self._use_theme_bg)

        self._obs_mode_cb = QCheckBox("OBS 捕获模式（悬浮窗显示任务栏图标）")
        self._obs_mode_cb.setToolTip(
            "开启后悬浮窗显示任务栏图标，OBS 窗口捕获可以正常识别。\n"
            "关闭后无任务栏图标，OBS 需用显示器捕获替代。"
        )
        lo.addWidget(self._obs_mode_cb)

        return w

    # =========================================================================
    # Tab 5: 数据
    # =========================================================================

    def _make_data_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(8)

        g = QGroupBox("对方卡组预设")
        gl = QVBoxLayout(g)
        self._preset_list = QListWidget()
        gl.addWidget(self._preset_list)

        ar = QHBoxLayout()
        self._preset_input = QLineEdit()
        self._preset_input.setPlaceholderText("输入新卡组名…")
        ar.addWidget(self._preset_input)
        ba = QPushButton("添加")
        ba.clicked.connect(self._add_preset)
        ar.addWidget(ba)
        bd = QPushButton("删除选中")
        bd.clicked.connect(self._del_preset)
        ar.addWidget(bd)
        ar.addStretch()
        gl.addLayout(ar)
        lo.addWidget(g)

        # 统计表格显示列选择
        from src.recorder import STATS_COLUMNS
        g_stats = QGroupBox("统计表格显示的列")
        gl_stats = QVBoxLayout(g_stats)
        hint = QLabel("> 添加  < 移除  ^ 上移  v 下移  |  清空已选 = 显示全部")
        hint.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        gl_stats.addWidget(hint)
        self._stats_dual = DualListWidget(list(STATS_COLUMNS), list(STATS_COLUMNS))
        gl_stats.addWidget(self._stats_dual)
        lo.addWidget(g_stats)

        self._daily_files = QCheckBox("按日期分文件存储 CSV")
        lo.addWidget(self._daily_files)
        self._remember_deck = QCheckBox("启动时自动填入上次使用的卡组")
        lo.addWidget(self._remember_deck)
        lo.addStretch()
        return w

    # =========================================================================
    # 按钮栏
    # =========================================================================

    def _make_button_bar(self) -> QWidget:
        bar = QWidget()
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(16, 8, 16, 8)
        lo.addStretch()
        bo = QPushButton("确定")
        bo.clicked.connect(self._on_save)
        bo.setDefault(True)
        lo.addWidget(bo)
        bc = QPushButton("取消")
        bc.clicked.connect(self.reject)
        lo.addWidget(bc)
        return bar

    # =========================================================================
    # 数据加载
    # =========================================================================

    def _load_from_config(self) -> None:
        c = self._config

        d = c.get("detection", {})
        self._interval.setValue(d.get("interval", 0.3))
        self._threshold.setValue(d.get("confidence_threshold", 0.8))

        # ---- debug 段：调试与实验功能 ----
        # 包含三个配置项：
        #   save_screenshots (bool) — 保存检测截图
        #   log_mode (bool)          — 日志模式主开关
        #   log_scope (list[str])    — 日志记录范围
        dbg = c.get("debug", {})
        self._save_screenshots_cb.setChecked(dbg.get("save_screenshots", False))
        self._log_mode_cb.setChecked(dbg.get("log_mode", False))
        # log_scope 是 TOML 数组，转成集合后分别设置三个子复选框
        scopes = set(dbg.get("log_scope", ["status", "screenshots", "errors"]))
        self._log_scope_status.setChecked("status" in scopes)
        self._log_scope_screenshots.setChecked("screenshots" in scopes)
        self._log_scope_errors.setChecked("errors" in scopes)
        # 根据日志模式的初始状态设置子复选框的启用/禁用
        self._on_log_mode_toggled(dbg.get("log_mode", False))

        self._notify_cb.setChecked(c.get("notification", {}).get("enabled", False))
        self._notify_duration.setValue(c.get("notification", {}).get("duration", 5))
        n = c.get("notification", {})
        self._tray_minimize_cb.setChecked(n.get("minimize_to_tray", False))
        self._obs_mode_cb.setChecked(n.get("obs_mode", False))

        theme = c.get("appearance", {}).get("theme", "")
        idx = self._theme_combo.findText(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        wd = c.get("window", {})
        self._win_width.setValue(wd.get("width", 1300))
        self._win_height.setValue(wd.get("height", 700))

        cb = c.get("clipboard", {})
        if cb.get("vertical_layout", False):
            self._cb_vert.setChecked(True)
        else:
            self._cb_tsv.setChecked(True)
        if cb.get("scope", "all") == "current":
            self._cb_curr.setChecked(True)
        else:
            self._cb_all.setChecked(True)
        saved_cols = cb.get("columns")
        if saved_cols:
            old = self._cb_dual
            self._cb_dual = DualListWidget(self._ALL_KEYS, list(saved_cols))
            self._replace_in_layout(self._tabs.widget(2), old, self._cb_dual)

        fw = c.get("floating_window", {})
        self._fw_w.setValue(fw.get("width", 250))
        self._fw_h.setValue(fw.get("height", 300))
        bg = fw.get("bg_color", "#98d4bb")
        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        self._fw_bg.set_color(QColor(r, g, b))
        self._fw_op.setValue(fw.get("opacity", 50))
        tc = fw.get("text_color", "#000000")
        r2, g2, b2 = int(tc[1:3], 16), int(tc[3:5], 16), int(tc[5:7], 16)
        self._fw_tc.set_color(QColor(r2, g2, b2))
        self._fw_fs.setValue(fw.get("font_size", 20))
        ff = fw.get("font_family", "")
        if ff:
            idx = self._fw_ff.findText(ff)
            if idx >= 0:
                self._fw_ff.setCurrentIndex(idx)
        saved_rows = fw.get("rows")
        if saved_rows:
            old = self._fw_dual
            self._fw_dual = DualListWidget(self._ALL_KEYS, list(saved_rows))
            self._replace_in_layout(self._tabs.widget(3), old, self._fw_dual)

        self._use_theme_bg.setChecked(fw.get("use_theme_bg", False))

        presets = c.get("opponent_decks", {}).get("presets", [])
        self._preset_list.clear()
        for p in presets:
            if p.strip():
                self._preset_list.addItem(p.strip())
        self._daily_files.setChecked(
            c.get("recorder", {}).get("daily_files", False)
        )
        self._remember_deck.setChecked(
            c.get("recorder", {}).get("remember_last_deck", False)
        )

        # 统计表格列选择
        saved_stats = c.get("stats", {}).get("columns")
        if saved_stats:
            from src.recorder import STATS_COLUMNS
            old = self._stats_dual
            self._stats_dual = DualListWidget(list(STATS_COLUMNS), list(saved_stats))
            self._replace_in_layout(self._tabs.widget(4), old, self._stats_dual)

    @staticmethod
    def _replace_in_layout(parent: QWidget | None, old: QWidget, new: QWidget) -> None:
        """把布局中的旧控件替换为新控件。

        支持两级搜索 — DualListWidget 通常嵌套在 QGroupBox → QVBoxLayout 中，
        顶层布局只能看到 QGroupBox，看不到里面的 DualListWidget。
        setParent(None) 立即解绑旧控件，避免 deleteLater 延迟导致两个控件并存。
        """
        if parent is None:
            return
        lo = parent.layout()
        if lo is None:
            return
        for i in range(lo.count()):
            item = lo.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            # 直接匹配：控件在顶层布局中
            if w is old:
                lo.replaceWidget(old, new)
                old.setParent(None)
                return
            # 间接匹配：控件包裹在子容器（如 QGroupBox）的布局中
            if w is not None:
                sub = w.layout()
                if sub is not None:
                    for j in range(sub.count()):
                        sw = sub.itemAt(j).widget()
                        if sw is old:
                            sub.replaceWidget(old, new)
                            old.setParent(None)
                            return

    # =========================================================================
    # 保存
    # =========================================================================

    def _on_save(self) -> None:
        """用户点击「确定」→ 从各控件取值 → 写回 config.toml → 通知主窗口重载。

        为什么不能直接改 self._config（MainWindow 的引用）？
            MainWindow._on_reload_config 的第一步是读取旧主题名：
                old_theme_name = self._config.get("appearance", {}).get("theme", "dark")
            如果这里先把 self._config["appearance"]["theme"] 改成了新值，
            那 old_theme_name 就等于新值，新旧相同 → 主题切换检测失效。

        解决方案：构建一个全新的 data 字典（独立于 self._config），
        写入文件后，由 _on_reload_config 自己从文件中读出新旧差异。
        """
        presets = [self._preset_list.item(i).text().strip()
                   for i in range(self._preset_list.count())]

        data: dict[str, Any] = {
            "detection": {
                "interval": round(self._interval.value(), 1),
                "confidence_threshold": round(self._threshold.value(), 2),
            },
            "debug": {
                "save_screenshots": self._save_screenshots_cb.isChecked(),
                "log_mode": self._log_mode_cb.isChecked(),
                "log_scope": self._get_log_scope(),
            },
            "appearance": {
                "theme": self._theme_combo.currentText(),
            },
            "window": {
                "width": self._win_width.value(),
                "height": self._win_height.value(),
            },
            "clipboard": {
                "vertical_layout": self._cb_vert.isChecked(),
                "scope": "current" if self._cb_curr.isChecked() else "all",
                "columns": self._cb_dual.get_selected(),
            },
            "floating_window": {
                "use_theme_bg": self._use_theme_bg.isChecked(),
                "width": self._fw_w.value(),
                "height": self._fw_h.value(),
                "bg_color": self._fw_bg.color().name(),
                "opacity": self._fw_op.value(),
                "text_color": self._fw_tc.color().name(),
                "font_size": self._fw_fs.value(),
                "font_family": self._fw_ff.currentFont().family(),
                "rows": self._fw_dual.get_selected(),
            },
            "opponent_decks": {
                "presets": [p for p in presets if p],
            },
            "recorder": {
                "daily_files": self._daily_files.isChecked(),
                "remember_last_deck": self._remember_deck.isChecked(),
            },
            "stats": {
                "columns": self._stats_dual.get_selected(),
            },
            "notification": {
                "enabled": self._notify_cb.isChecked(),
                "duration": self._notify_duration.value(),
                "minimize_to_tray": self._tray_minimize_cb.isChecked(),
                "obs_mode": self._obs_mode_cb.isChecked(),
            },
        }

        self._write_toml(data)
        self.config_saved.emit()
        self.accept()

    @staticmethod
    def _write_toml(data: dict) -> None:
        """把配置字典写成带注释的 config.toml 文件。"""
        path = get_project_root() / "config.toml"

        def _kv(key: str, value: Any, comment: str = "") -> None:
            """写入 key = value 行，前面可选注释。"""
            if comment:
                lines.append(f"# {comment}")
            if isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            elif isinstance(value, list):
                if not value:
                    lines.append(f"{key} = []")
                else:
                    items = ", ".join(f'"{x}"' for x in value)
                    lines.append(f"{key} = [{items}]")

        # 先提取所有段的值
        d = data.get("detection", {})
        w = data.get("window", {})
        a = data.get("appearance", {})
        od = data.get("opponent_decks", {})
        r = data.get("recorder", {})
        st = data.get("stats", {})
        cb = data.get("clipboard", {})
        fw = data.get("floating_window", {})
        dbg = data.get("debug", {})
        ntfy = data.get("notification", {})

        lines: list[str] = [
            "# MD Stats 配置文件（由设置 GUI 生成，也可手动编辑）",
            "# 修改后点击主窗口的「设置 → 确定」即时生效。",
            "# 所有时间单位为秒，所有颜色使用十六进制格式。",
            "",
            "# 图像识别相关配置",
            "[detection]",
        ]
        _kv("interval", d.get("interval", 0.3),
            "截图间隔（秒），推荐 0.3 ~ 1.0")
        _kv("confidence_threshold", d.get("confidence_threshold", 0.8),
            "匹配置信度阈值 (0.0~1.0)，推荐 0.75~0.90")

        lines.extend(["", "# 调试与实验功能", "[debug]"])
        _kv("save_screenshots", dbg.get("save_screenshots", False),
            "检测到关键事件时保存截图到 screenshots/，下一局开始时自动清除")
        _kv("log_mode", dbg.get("log_mode", False),
            "开启日志模式：将运行信息写入 logs/ 目录")
        _kv("log_scope", dbg.get("log_scope", ["status", "screenshots", "errors"]),
            '日志记录范围："status"=状态栏消息, "screenshots"=截图事件, "errors"=错误信息')

        lines.extend(["", "[window]"])
        _kv("width", w.get("width", 1300), "主窗口宽度（像素）")
        _kv("height", w.get("height", 700), "主窗口高度（像素）")

        lines.extend(["", "# 界面外观", "[appearance]"])
        _kv("theme", a.get("theme", "dark"),
            '主题文件夹名（内置: "dark" / "light" / "macaron"）')

        lines.extend(["", "# 对方卡组预设", "[opponent_decks]"])
        _kv("presets", od.get("presets", []),
            "记录表格下拉菜单的预设选项")

        lines.extend(["", "# 数据存储", "[recorder]"])
        _kv("daily_files", r.get("daily_files", False),
            "是否按日期分文件存储 CSV")
        _kv("remember_last_deck", r.get("remember_last_deck", False),
            "启动时自动填入最近一次使用的卡组（从 CSV 读取）")

        lines.extend(["", "# 统计表格显示", "[stats]"])
        _kv("columns", st.get("columns", []),
            "统计表格显示的列名列表（空 = 全部显示）")

        lines.extend(["", "# 剪贴板复制行为", "[clipboard]"])
        _kv("vertical_layout", cb.get("vertical_layout", False),
            '竖排模式：true = 每行"key\\tvalue"，false = 横排 TSV')
        _kv("scope", cb.get("scope", "all"),
            '复制范围："current" = 当前卡组，"all" = 全部卡组')
        _kv("columns", cb.get("columns", []),
            "要复制的列名列表（空 = 默认 8 项）")

        lines.extend(["", "# 系统通知", "[notification]"])
        _kv("enabled", ntfy.get("enabled", False),
            "对局结束时弹出系统气泡通知")
        _kv("duration", ntfy.get("duration", 5),
            "通知显示持续时间（秒）")
        _kv("minimize_to_tray", ntfy.get("minimize_to_tray", False),
            "最小化时隐藏到系统托盘（而非任务栏）")
        _kv("obs_mode", ntfy.get("obs_mode", False),
            "OBS 捕获模式（悬浮窗显示任务栏图标以允许 OBS 捕获）")

        lines.extend(["", "# 悬浮统计窗", "[floating_window]"])
        _kv("use_theme_bg", fw.get("use_theme_bg", False),
            "是否使用主题背景图（false = 纯色，方便 OBS 颜色键捕捉）")
        _kv("width", fw.get("width", 250), "悬浮窗宽度（像素）")
        _kv("height", fw.get("height", 300), "悬浮窗高度（像素）")
        _kv("bg_color", fw.get("bg_color", "#BDEF0A"), "背景色")
        _kv("opacity", fw.get("opacity", 50), "不透明度 0-100")
        _kv("font_size", fw.get("font_size", 20), "文字字号（像素）")
        _kv("text_color", fw.get("text_color", "#000000"), "文字颜色")
        _kv("font_family", fw.get("font_family", "Microsoft YaHei, -apple-system, sans-serif"),
            "字体（Qt 从前往后找第一个可用的，含 macOS/Windows 回退）")
        _kv("rows", fw.get("rows", []),
            "显示数据行（空 = 默认 8 项）")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # =========================================================================
    # 卡组预设
    # =========================================================================

    def _add_preset(self) -> None:
        name = self._preset_input.text().strip()
        if not name:
            return
        for i in range(self._preset_list.count()):
            if self._preset_list.item(i).text() == name:
                return
        self._preset_list.addItem(name)
        self._preset_input.clear()

    def _del_preset(self) -> None:
        for item in self._preset_list.selectedItems():
            self._preset_list.takeItem(self._preset_list.row(item))

    # =========================================================================
    # 日志
    # =========================================================================

    def _get_log_scope(self) -> list[str]:
        """从三个子复选框构建 log_scope 列表，用于写入 config.toml。

        TOML 中的 log_scope 是一个字符串列表，如 ["status", "screenshots", "errors"]。
        这个方法把复选框状态转成对应的字符串列表。
        """
        scopes = []
        if self._log_scope_status.isChecked():
            scopes.append("status")
        if self._log_scope_screenshots.isChecked():
            scopes.append("screenshots")
        if self._log_scope_errors.isChecked():
            scopes.append("errors")
        return scopes

    def _on_log_mode_toggled(self, enabled: bool) -> None:
        """日志模式开关切换时，联动启用/禁用三个子复选框。

        为什么要禁用而不是隐藏？
            隐藏会导致界面布局跳动，用户体验不好。用 setEnabled(False)
            让复选框变灰但保持在原位，用户能清楚看到"这些选项在日志模式
            关闭时不生效"。
        """
        for cb in (self._log_scope_status, self._log_scope_screenshots, self._log_scope_errors):
            cb.setEnabled(enabled)

    def _open_logs_dir(self) -> None:
        """在 Windows 文件资源管理器中打开日志文件夹。

        如果日志文件夹不存在（从未开启过日志模式），先创建空文件夹再打开，
        避免 explorer 报错"路径不存在"。
        """
        import os
        import subprocess
        log_dir = get_project_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", os.fspath(log_dir)])

    # =========================================================================
    # 背景绘制
    # =========================================================================

    def paintEvent(self, event) -> None:
        """手绘背景：有图则贴图填充，无图走默认 QDialog 背景。"""
        painter = QPainter(self)
        if self._bg_pixmap is not None:
            scaled = self._bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
        painter.end()
        super().paintEvent(event)

    # =========================================================================
    # 拖拽
    # =========================================================================

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    # =========================================================================
    # DWM 圆角（Windows 11）
    # =========================================================================

    def _apply_dwm_round_corners(self) -> None:
        """给无边框弹窗加 Win11 原生圆角。"""
        import ctypes, os
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            dwmwa = 33  # DWMWA_WINDOW_CORNER_PREFERENCE
            dwmwcp_round = 2  # 圆角
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd, dwmwa,
                ctypes.byref(ctypes.c_int(dwmwcp_round)),
                ctypes.sizeof(ctypes.c_int),
            )
        except OSError:
            pass
