"""自定义标题栏控件 — 配合无边框窗口使用。

================================================================================
结构
================================================================================

┌──────────────────────────────────────────────────────┐
│  [icon]  窗口标题                        [─]  [×]    │
└──────────────────────────────────────────────────────┘

按钮图标（title_min.png / title_close.png）从主题 assets/ 加载，
加载不到时自动用 QPainter 绘制矢量线条。

================================================================================
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QWidget


class _TitleBarButton(QPushButton):
    """标题栏按钮 — 优先图标文件，回退到矢量绘制。"""

    def __init__(
        self, icon_name: str, assets_dir: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_pixmap: QPixmap | None = None

        icon_path = assets_dir / f"{icon_name}.png"
        if icon_path.exists():
            self._icon_pixmap = QPixmap(str(icon_path))

        self.setFixedSize(40, 30)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        # 先让 QPushButton 绘制背景和边框（QSS 样式在此生效）
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        if self._icon_pixmap:
            pm = self._icon_pixmap.scaled(
                16, 16, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (rect.width() - pm.width()) // 2
            y = (rect.height() - pm.height()) // 2
            painter.drawPixmap(x, y, pm)
            return

        # 回退：矢量绘制
        color = self.palette().color(self.foregroundRole())
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        cx, cy = rect.width() // 2, rect.height() // 2
        if self._icon_name == "title_min":
            painter.drawLine(cx - 5, cy, cx + 5, cy)
        elif self._icon_name == "title_close":
            painter.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
            painter.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)

        painter.end()


class TitleBar(QWidget):
    """可拖拽的自定义标题栏。

    信号:
        minimize_clicked: 最小化按钮被点击
        close_clicked:    关闭按钮被点击
    """

    minimize_clicked = Signal()
    close_clicked = Signal()

    def __init__(
        self,
        title: str,
        config: dict,
        assets_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        height = config.get("height", 36)
        icon_size = config.get("icon_size", 20)
        self._dragging = False
        self._drag_start = QPoint()

        self.setFixedHeight(height)
        self.setObjectName("titleBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(4)

        # ---- 图标 ----
        self._icon_label = QLabel()
        icon_path = assets_dir / "app_icon.png"
        if icon_path.exists():
            pm = QPixmap(str(icon_path)).scaled(
                icon_size, icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._icon_label.setPixmap(pm)
        self._icon_label.setFixedSize(icon_size + 8, height)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        # ---- 标题文字 ----
        # text_font / text_shadow 是新加的可选字段，主题不提供时回到原始外观，
        # 不影响 dark / light 主题
        title_color = config.get("text_color", "#cccccc")
        title_size = config.get("text_size", 12)
        title_font_family = config.get("text_font", "")
        self._title_label = QLabel(title)
        if title_font_family:
            self._title_label.setStyleSheet(
                f"color: {title_color}; font-size: {title_size}px; "
                f"font-family: {title_font_family}; "
                "font-weight: 700; letter-spacing: 1px; "
                "background: transparent; border: none;"
            )
        else:
            self._title_label.setStyleSheet(
                f"color: {title_color}; font-size: {title_size}px; "
                "font-weight: 600; background: transparent; border: none;"
            )
        # 柔和粉色阴影 — 让标题文字带一点水彩晕染感（仅当主题指定 text_shadow 时启用）
        shadow_color = config.get("text_shadow", "")
        if shadow_color:
            effect = QGraphicsDropShadowEffect(self._title_label)
            effect.setColor(QColor(shadow_color))
            effect.setBlurRadius(8)
            effect.setOffset(0, 1)
            self._title_label.setGraphicsEffect(effect)
        layout.addWidget(self._title_label)
        layout.addStretch()

        # ---- 按钮 ----
        btn_hover = config.get("btn_hover_bg", "#3a3a5a")
        btn_close_hover = config.get("btn_close_hover", "#e74c3c")

        self._btn_min = _TitleBarButton("title_min", assets_dir, self)
        self._btn_min.setObjectName("titleMinBtn")
        self._btn_min.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {btn_hover}; "
            f"border-color: {btn_hover}; }}"
        )
        self._btn_min.clicked.connect(self.minimize_clicked.emit)
        layout.addWidget(self._btn_min)

        self._btn_close = _TitleBarButton("title_close", assets_dir, self)
        self._btn_close.setObjectName("titleCloseBtn")
        self._btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {btn_close_hover}; "
            f"border-color: {btn_close_hover}; }}"
        )
        self._btn_close.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self._btn_close)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def set_icon(self, pixmap: QPixmap) -> None:
        self._icon_label.setPixmap(pixmap)

    def reload_style(self, config: dict) -> None:
        """主题切换后重新应用标题栏样式。"""
        text_color = config.get("text_color", "#cccccc")
        text_size = config.get("text_size", 12)
        title_font_family = config.get("text_font", "")
        btn_hover_bg = config.get("btn_hover_bg", "#3a3a5a")
        btn_close_hover = config.get("btn_close_hover", "#e74c3c")

        if title_font_family:
            self._title_label.setStyleSheet(
                f"color: {text_color}; font-size: {text_size}px; "
                f"font-family: {title_font_family}; "
                "font-weight: 700; letter-spacing: 1px; "
                "background: transparent; border: none;"
            )
        else:
            self._title_label.setStyleSheet(
                f"color: {text_color}; font-size: {text_size}px; "
                "font-weight: 600; background: transparent; border: none;"
            )
        shadow_color = config.get("text_shadow", "")
        if shadow_color:
            effect = QGraphicsDropShadowEffect(self._title_label)
            effect.setColor(QColor(shadow_color))
            effect.setBlurRadius(8)
            effect.setOffset(0, 1)
            self._title_label.setGraphicsEffect(effect)
        else:
            self._title_label.setGraphicsEffect(None)
        self._btn_min.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {btn_hover_bg}; "
            f"border-color: {btn_hover_bg}; }}"
        )
        self._btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {btn_close_hover}; "
            f"border-color: {btn_close_hover}; }}"
        )

    # ---- 拖拽 ----
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            window = self.window()
            if window:
                window.move(window.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, _event) -> None:
        pass  # 不需要最大化，空实现
