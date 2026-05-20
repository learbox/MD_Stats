"""主题管理器 — 从 main_window.py 抽离的主题状态和控件着色逻辑。

将颜色工具函数、QPalette 背景设置、表格/按钮着色、布局包裹等
集中管理，减少 MainWindow 的代码量。

注意：本类方法接收 MainWindow 实例（mw）直接访问其 _ 前缀控件，
      这是代码拆分后的设计选择，PyCharm 中请在 Settings
      → Editor → Inspections → Python → Protected member 中关闭检查，
      或添加此文件到排除列表。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPalette, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout

from src.theme_loader import Theme, load_theme


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
    # 控件着色（接收 MainWindow 实例，从中取需要的控件引用）
    # ------------------------------------------------------------------

    def apply_to_widgets(self, mw) -> None:
        """将已加载的主题应用到所有控件（在 __init__ 和 reload 中复用）。"""
        self.wrap_layouts(mw)
        self.apply_table_viewport_palette(mw)
        self.apply_static_button_palette(mw)
        mw._refresh_stats_table()
        mw._refresh_record_table()
        mw._update_manual_buttons()
        mw._btn_start.setStyleSheet(
            self.make_button_style(
                self.colors["start_bg"], padding="6px 20px"
            )
        )
        mw._title_bar.set_title("MD Stats")
        mw._title_bar.reload_style(self.titlebar_cfg)

    def do_apply_pixmaps(self, mw) -> None:
        """QPalette 设背景：关键控件先纯色，有图叠图。首次启动时 showEvent 调用。"""
        main_bg = self.colors.get("main_bg", "#f5f6fa")
        status_bg = self.colors.get("statusbar_bg", "#ecf0f1")

        # 标题栏 QSS 是 background: transparent
        self.set_palette_bg(mw._status_frame, None, status_bg)
        self.set_palette_bg(mw._content, None, main_bg)

        for selector, path in self.pixmap_paths.items():
            pm = QPixmap(path)
            if pm.isNull():
                continue
            if selector == "#contentWidget":
                self.set_palette_bg(mw._content, pm, main_bg)
            elif selector == "#customStatusBar":
                self.set_palette_bg(mw._status_frame, pm, status_bg)
            elif selector == "QTableWidget":
                for table in (mw._stats_table, mw._record_table):
                    table.viewport().setStyleSheet(
                        f"border-image: url({path}) 0 0 0 0 stretch stretch;"
                        f"background-color: transparent;"
                    )
            elif selector == "QHeaderView::section":
                for table in (mw._stats_table, mw._record_table):
                    self.set_palette_bg(table.horizontalHeader(), pm, main_bg)
            elif selector == "QHeaderView::section:vertical":
                for table in (mw._stats_table, mw._record_table):
                    self.set_palette_bg(table.verticalHeader(), pm, main_bg)

    def apply_static_button_palette(self, mw) -> None:
        """给少数语义重要的按钮上色。"""
        c = self.colors
        if self.pixmap_paths and self.pixmap_paths.get("QPushButton"):
            mw._btn_stop.setStyleSheet(
                self.make_button_style(c.get("lose", "#f0a5b5"))
            )
            mw._btn_delete_last.setStyleSheet(
                self.make_button_style(c.get("lose", "#f0a5b5"))
            )
        else:
            mw._btn_stop.setStyleSheet("")
            mw._btn_delete_last.setStyleSheet("")

    def apply_table_viewport_palette(self, mw) -> None:
        """表格/表头 viewport 背景：清旧样式，有资源图用 QPalette 贴图，无图涂纯色。"""
        # 先清空旧主题遗留的 stylesheet 和 QPalette
        for table in (mw._stats_table, mw._record_table):
            for w in (table.viewport(), table.verticalHeader(),
                      table.horizontalHeader()):
                w.setStyleSheet("")
                w.setAutoFillBackground(False)
                p = w.palette()
                p.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
                p.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
                p.setBrush(QPalette.ColorRole.Window, QBrush())
                p.setBrush(QPalette.ColorRole.Base, QBrush())
                w.setPalette(p)

        if self.pixmap_paths:
            table_path = self.pixmap_paths.get("QTableWidget")
            header_path = self.pixmap_paths.get("QHeaderView::section")
            row_header_path = self.pixmap_paths.get("QHeaderView::section:vertical")
            header_pm = QPixmap(header_path) if header_path else None
            row_header_pm = QPixmap(row_header_path) if row_header_path else None
            for table in (mw._stats_table, mw._record_table):
                # viewport: 有图用 border-image 拉伸，无图跳过靠 QSS
                if table_path:
                    table.viewport().setStyleSheet(
                        f"border-image: url({table_path}) 0 0 0 0 stretch stretch;"
                        f"background-color: transparent;"
                    )
                if header_pm and not header_pm.isNull():
                    self.set_palette_bg(table.horizontalHeader(),
                                       header_pm, "")
                if row_header_pm and not row_header_pm.isNull():
                    self.set_palette_bg(table.verticalHeader(),
                                       row_header_pm, "")
            return

        base = self.colors.get("widget_bg", "#ffffff")
        header_bg = self.colors.get("main_bg", "#f5f6fa")
        theme = self._config.get("appearance", {}).get("theme", "dark")
        if theme != "dark":
            header_bg = self.colors.get("statusbar_bg", header_bg)

        for table in (mw._stats_table, mw._record_table):
            vp = table.viewport()
            self.set_palette_bg(vp, None, base)
            vp.setStyleSheet(f"background-color: {base};")

            vh = table.verticalHeader()
            self.set_palette_bg(vh, None, header_bg)
            vh.setStyleSheet(f"background-color: {header_bg};")

            hh = table.horizontalHeader()
            self.set_palette_bg(hh, None, header_bg)
            hh.setStyleSheet(f"background-color: {header_bg};")

    def wrap_layouts(self, mw) -> None:
        """把 ctrlLayout 和 bottomLayout 包进 QFrame，便于 QSS 贴 panel_bg。"""
        if not self.pixmap_paths:
            return
        content = mw._content
        root_layout = content.layout()
        if root_layout is None:
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
    def lighter_color(cls, hex_color: str, factor: float = 0.25) -> str:
        """将颜色向白色方向提亮 factor*100%。"""
        r, g, b = cls._parse_hex(hex_color)
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    @classmethod
    def darker_color(cls, hex_color: str, factor: float = 0.15) -> str:
        """将颜色向黑色方向加深 factor*100%。"""
        r, g, b = cls._parse_hex(hex_color)
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
