"""悬浮统计窗 — 无边框、半透明、可拖拽、始终置顶。"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget


class FloatingWindow(QWidget):
    """对局统计悬浮窗，7 行 × 2 列表格布局。"""

    _DEFAULT_W = 300
    _DEFAULT_H = 300

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dragging = False
        self._drag_start = QPoint()
        self._bg_color = QColor(152, 212, 187, 128)
        self._text_color = "#000000"
        self._font_size = 14
        self._font_family = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self._DEFAULT_W, self._DEFAULT_H)

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(20, 20, 20, 20)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(6)

        rows = ("卡组", "对局数", "赢 / 输硬币", "赢币概率",
                "赢币胜率", "输币胜率", "综合胜率")
        self._labels: list[QLabel] = []
        self._values: list[QLabel] = []
        for r, text in enumerate(rows):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(lbl, r, 0)
            self._labels.append(lbl)

            val = QLabel("-")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(val, r, 1)
            self._values.append(val)

        self._apply_style()

    def paintEvent(self, event) -> None:
        """手绘圆角半透明背景。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(8, 8, self.width() - 16, self.height() - 16, 10, 10)
        painter.fillPath(path, self._bg_color)
        painter.end()

    def _style_sheet(self) -> str:
        css = (
            f"color: {self._text_color}; font-size: {self._font_size}px;"
            f"font-weight: bold; background: transparent; border: none;"
        )
        if self._font_family:
            css += f" font-family: {self._font_family};"
        return css

    def _apply_style(self) -> None:
        ss = self._style_sheet()
        for lbl in self._labels:
            lbl.setStyleSheet(ss)
        for val in self._values:
            val.setStyleSheet(ss)

    def update_style(self, cfg: dict) -> None:
        """按 config.toml [floating_window] 段更新外观。"""
        w = cfg.get("width", self._DEFAULT_W)
        h = cfg.get("height", self._DEFAULT_H)
        self.setFixedSize(w, h)

        bg = cfg.get("bg_color", "#98d4bb")
        opacity_pct = cfg.get("opacity", 50)  # 0-100
        self._font_size = cfg.get("font_size", 14)
        self._text_color = cfg.get("text_color", "#000000")
        self._font_family = cfg.get("font_family", "")

        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        alpha = int(opacity_pct / 100 * 255)
        self._bg_color = QColor(r, g, b, alpha)
        self._apply_style()
        self.update()

    def update_content(self, deck_name: str, stats: dict | None) -> None:
        """刷新悬浮窗 7 行 × 2 列数据。"""
        if stats is None:
            for v in self._values:
                v.setText("-")
            return

        self._values[0].setText(deck_name or "(未指定)")
        self._values[1].setText(str(stats.get("对局数", 0)))
        self._values[2].setText(
            f"{stats.get('赢硬币次数', 0)} / {stats.get('输硬币次数', 0)}"
        )
        self._values[3].setText(str(stats.get("赢硬币概率", "-")))
        self._values[4].setText(str(stats.get("赢硬币胜率", "-")))
        self._values[5].setText(str(stats.get("输硬币胜率", "-")))
        self._values[6].setText(str(stats.get("胜率", "-")))

    # ---- 拖拽 ----
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
