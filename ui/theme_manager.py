"""主题管理器 — 从 main_window.py 抽离的主题状态和控件着色逻辑。

将颜色工具函数、QPalette 背景设置、表格/按钮着色、布局包裹等
集中管理，减少 MainWindow 的代码量。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QBoxLayout, QFrame, QHBoxLayout, QPushButton, QTableWidget, QWidget

from src.theme_loader import Theme, load_theme
from ui.titlebar import TitleBar


@dataclass
class ThemeWidgets:
    """MainWindow 中 ThemeManager 需要访问的控件引用集合。

    由 MainWindow 构建，传入 ThemeManager 的各个方法，
    避免 ThemeManager 直接访问 MainWindow 的 protected 成员。
    """
    stats_table: QTableWidget
    record_table: QTableWidget
    btn_start: QPushButton
    btn_stop: QPushButton
    btn_delete_last: QPushButton
    title_bar: TitleBar
    status_frame: QFrame
    content: QWidget
    refresh_stats_table: Callable[[], None]
    refresh_record_table: Callable[[], None]
    update_manual_buttons: Callable[[], None]


class ThemeManager:
    """主题状态和控件着色管理。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.colors: dict[str, str] = {}
        self.pixmap_paths: dict[str, str] = {}
        self.titlebar_cfg: dict[str, Any] = {}
        self.assets_dir: Path | None = None

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def load(self, theme_name: str) -> Theme:
        """加载主题并更新内部状态，返回 Theme 供 MainWindow 使用。"""
        theme = load_theme(theme_name)
        self.colors = theme.colors
        self.pixmap_paths = theme.pixmaps
        self.titlebar_cfg = theme.titlebar
        self.assets_dir = theme.assets_dir
        return theme

    # ------------------------------------------------------------------
    # 全局 QPalette（修复 QComboBox 弹出容器等 QSS 无法覆盖的区域）
    # ------------------------------------------------------------------

    def apply_app_palette(self) -> None:
        """根据当前主题颜色设置 QApplication 级别的 QPalette。

        QComboBox 的弹出容器（popup container）是独立顶层窗口，
        其背景色来自 QApplication 的 QPalette 而非 QSS。
        不设置全局 QPalette 的话，dark 主题下弹出列表上下会出现白条。
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return

        c = self.colors
        pal = QPalette()
        base = QColor(c.get("widget_bg", "#ffffff"))
        text = QColor(c.get("text_primary", "#000000"))
        window = QColor(c.get("main_bg", "#ffffff"))
        highlight = QColor(c.get("selection_bg", "#3080e0"))
        disabled_text = QColor(c.get("text_disabled", "#999999"))

        role_map: list[tuple[QPalette.ColorRole, QColor]] = [
            (QPalette.ColorRole.Window, window),
            (QPalette.ColorRole.Base, base),
            (QPalette.ColorRole.WindowText, text),
            (QPalette.ColorRole.Text, text),
            (QPalette.ColorRole.Button, base),
            (QPalette.ColorRole.ButtonText, text),
            (QPalette.ColorRole.Highlight, highlight),
            (QPalette.ColorRole.HighlightedText, text),
            (QPalette.ColorRole.ToolTipBase, base),
            (QPalette.ColorRole.ToolTipText, text),
        ]
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            for role, color in role_map:
                pal.setColor(group, role, color)

        for role in (QPalette.ColorRole.WindowText,
                     QPalette.ColorRole.Text,
                     QPalette.ColorRole.ButtonText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, disabled_text)

        app.setPalette(pal)

    # ------------------------------------------------------------------
    # 控件着色（接收 ThemeWidgets，从中取需要的控件引用）
    # ------------------------------------------------------------------

    def apply_to_widgets(self, w: ThemeWidgets) -> None:
        """将已加载的主题应用到所有控件（在 __init__ 和 reload 中复用）。"""
        self.wrap_layouts(w)
        self.apply_table_viewport_palette(w)
        self.apply_static_button_palette(w)
        w.refresh_stats_table()
        w.refresh_record_table()
        w.update_manual_buttons()
        w.btn_start.setStyleSheet(
            self.make_button_style(
                self.colors["start_bg"], padding="6px 20px"
            )
        )
        w.title_bar.set_title("MD Stats")
        w.title_bar.reload_style(self.titlebar_cfg)

    def do_apply_pixmaps(self, w: ThemeWidgets) -> None:
        """QPalette 设背景：关键控件先纯色，有图叠图。首次启动时 showEvent 调用。"""
        main_bg = self.colors.get("main_bg", "#f5f6fa")
        status_bg = self.colors.get("statusbar_bg", "#ecf0f1")

        self.set_palette_bg(w.status_frame, None, status_bg)
        self.set_palette_bg(w.content, None, main_bg)

        for selector, path in self.pixmap_paths.items():
            pm = QPixmap(path)
            if pm.isNull():
                continue
            if selector == "#contentWidget":
                self.set_palette_bg(w.content, pm, main_bg)
            elif selector == "#customStatusBar":
                self.set_palette_bg(w.status_frame, pm, status_bg)
            elif selector == "QTableWidget":
                for table in (w.stats_table, w.record_table):
                    table.viewport().setStyleSheet(
                        f"border-image: url({path}) 0 0 0 0 stretch stretch;"
                        f"background-color: transparent;"
                    )
            elif selector == "QHeaderView::section":
                pass  # 全局 QSS 的 border-image 处理拉伸
            elif selector == "QHeaderView::section:vertical":
                pass  # 全局 QSS 的 border-image 处理拉伸

    def apply_static_button_palette(self, w: ThemeWidgets) -> None:
        """给少数语义重要的按钮上色。"""
        c = self.colors
        if self.pixmap_paths and self.pixmap_paths.get("QPushButton"):
            w.btn_stop.setStyleSheet(
                self.make_button_style(c.get("lose", "#f0a5b5"))
            )
            w.btn_delete_last.setStyleSheet(
                self.make_button_style(c.get("lose", "#f0a5b5"))
            )
        else:
            w.btn_stop.setStyleSheet("")
            w.btn_delete_last.setStyleSheet("")

    def apply_table_viewport_palette(self, w: ThemeWidgets) -> None:
        """表格/表头 viewport 背景：清旧样式，有资源图用 QPalette 贴图，无图涂纯色。"""
        # 先清空旧主题遗留的 stylesheet 和 QPalette
        for table in (w.stats_table, w.record_table):
            for vw in (table.viewport(), table.verticalHeader(),
                       table.horizontalHeader()):
                vw.setStyleSheet("")
                vw.setAutoFillBackground(False)
                p = vw.palette()
                p.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
                p.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
                p.setBrush(QPalette.ColorRole.Window, QBrush())
                p.setBrush(QPalette.ColorRole.Base, QBrush())
                vw.setPalette(p)

        if self.pixmap_paths:
            table_path = self.pixmap_paths.get("QTableWidget")
            for table in (w.stats_table, w.record_table):
                if table_path:
                    table.viewport().setStyleSheet(
                        f"border-image: url({table_path}) 0 0 0 0 stretch stretch;"
                        f"background-color: transparent;"
                    )
                # 表头不设局 stylesheet，靠全局 QSS 的 border-image 拉伸
            return

        base = self.colors.get("widget_bg", "#ffffff")
        header_bg = self.colors.get("main_bg", "#f5f6fa")
        theme = self._config.get("appearance", {}).get("theme", "dark")
        if theme != "dark":
            header_bg = self.colors.get("statusbar_bg", header_bg)

        for table in (w.stats_table, w.record_table):
            vp = table.viewport()
            self.set_palette_bg(vp, None, base)
            vp.setStyleSheet(f"background-color: {base};")

            vh = table.verticalHeader()
            self.set_palette_bg(vh, None, header_bg)
            vh.setStyleSheet(f"background-color: {header_bg};")

            hh = table.horizontalHeader()
            self.set_palette_bg(hh, None, header_bg)
            hh.setStyleSheet(f"background-color: {header_bg};")

    def wrap_layouts(self, w: ThemeWidgets) -> None:
        """把 ctrlLayout 和 bottomLayout 包进 QFrame，便于 QSS 贴 panel_bg。"""
        if not self.pixmap_paths:
            return
        content = w.content
        root_layout = content.layout()
        if not isinstance(root_layout, QBoxLayout):
            return

        for layout_name, frame_name in (("ctrlLayout", "topPanel"),
                                         ("bottomLayout", "bottomPanel")):
            if content.findChild(QFrame, frame_name) is not None:
                continue
            layout = content.findChild(QHBoxLayout, layout_name)
            if layout is None:
                continue
            idx = -1
            for i in range(root_layout.count()):
                item = root_layout.itemAt(i)
                if item is not None and item.layout() is layout:
                    idx = i
                    break
            if idx < 0:
                continue
            root_layout.takeAt(idx)
            frame = QFrame(content)
            frame.setObjectName(frame_name)
            frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            frame.setLayout(layout)
            layout.setContentsMargins(14, 6, 14, 6)
            root_layout.insertWidget(idx, frame)

    # ------------------------------------------------------------------
    # 按钮样式生成器
    # ------------------------------------------------------------------

    def make_button_style(self, bg: str, *,
                          padding: str = "4px 14px") -> str:
        """生成带 hover/pressed/disabled 高亮效果的动态按钮 QSS。

        如果主题用了按钮纹理（macaron），用 bg 作为实色填充覆盖底层水彩纹理。
        """
        button_texture = (self.pixmap_paths.get("QPushButton")
                          if self.pixmap_paths else None)

        if button_texture:
            text_color = self.readable_text_color(bg)
            hover_bg = self.lighter_color(bg, 0.12)
            pressed_bg = self.darker_color(bg, 0.08)
            border_disabled = self.colors.get("border_disabled", "#f5eef4")
            text_disabled = self.colors.get("text_disabled", "#d5ccd8")
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
                f"background: {self.colors.get('button_disabled_bg', 'rgba(245,238,244,220)')}; "
                f"color: {text_disabled}; "
                f"border-color: {border_disabled}; "
                "}"
            )

        border = self.colors.get("border", "#dcdde1")
        hover_bg = self.lighter_color(bg)
        disabled_bg = self.colors.get("button_disabled_bg", "#9E9E9E")
        disabled_color = self.colors.get("text_disabled", "#e0e0e0")
        disabled_border = self.colors.get("border_disabled", "#888")
        return (
            f"QPushButton {{ background-color: {bg}; color: white; "
            f"font-weight: bold; padding: {padding}; border-radius: 6px; "
            f"border: 1px solid {border}; }}"
            f"QPushButton:hover {{ background-color: {hover_bg}; "
            f"border-color: {hover_bg}; }}"
            f"QPushButton:disabled {{ background-color: {disabled_bg}; "
            f"color: {disabled_color}; border-color: {disabled_border}; }}"
        )

    # ------------------------------------------------------------------
    # 静态颜色工具
    # ------------------------------------------------------------------

    @staticmethod
    def set_palette_bg(widget, pm, fallback_color: str) -> None:
        """给控件设 QPalette 背景：有图贴图，无图纯色。

        Window + Base 双角色均设置以保证 QAbstractScrollArea viewport 兼容。
        """
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

    @staticmethod
    def _parse_hex(hex_color: str) -> tuple[int, int, int]:
        """将 #RRGGBB 解析为 (r, g, b) 元组。"""
        return (
            int(hex_color[1:3], 16),
            int(hex_color[3:5], 16),
            int(hex_color[5:7], 16),
        )

    @classmethod
    def readable_text_color(cls, hex_color: str) -> str:
        """根据底色亮度返回易读的文字色：浅底用深紫灰，深底用白。"""
        r, g, b = cls._parse_hex(hex_color)
        luma = (0.299 * r + 0.587 * g + 0.114 * b)
        return "#4a3a52" if luma > 170 else "#ffffff"

    @classmethod
    def _adjust_color(cls, hex_color: str, factor: float, darken: bool) -> str:
        """将颜色向黑/白方向调整 factor*100%。"""
        r, g, b = cls._parse_hex(hex_color)
        if darken:
            r, g, b = max(0, int(r * (1 - factor))), max(0, int(g * (1 - factor))), max(0, int(b * (1 - factor)))
        else:
            r, g, b = min(255, int(r + (255 - r) * factor)), min(255, int(g + (255 - g) * factor)), min(255, int(b + (255 - b) * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    @classmethod
    def lighter_color(cls, hex_color: str, factor: float = 0.25) -> str:
        """将颜色向白色方向提亮 factor*100%。"""
        return cls._adjust_color(hex_color, factor, darken=False)

    @classmethod
    def darker_color(cls, hex_color: str, factor: float = 0.15) -> str:
        """将颜色向黑色方向加深 factor*100%。"""
        return cls._adjust_color(hex_color, factor, darken=True)
