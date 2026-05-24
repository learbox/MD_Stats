"""关于弹窗 — 显示版本、作者、协议等信息。

元数据（版本号、作者等）也定义在此模块中，打包 exe 时 .py 会被捆绑，不会丢失。
"""

from pathlib import Path

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from src.config import get_project_root

# =============================================================================
# 元数据 — 打包 exe 时 .py 会被捆绑，不会丢失
# =============================================================================

VERSION = "1.4.0"
AUTHOR = "learbox"
LICENSE = "MIT"
REPO_URL = "https://github.com/learbox/mdstats_py"
DESCRIPTION = "基于 Python + OpenCV + PySide6\nMaster Duel 对局自动统计工具"
ACKNOWLEDGMENTS = (
    '<a href="https://github.com/slimpigs">KleeKlee</a>'
    " 对马卡龙主题设计提供代码支持，以及无偿提供的美术资源\n"
    '<a href="https://github.com/ULeang">ULya_tooru</a>'
    " 提供原版设计思路（mdstats C++）"
)


class AboutDialog(QDialog):
    """关于弹窗：风格与设置弹窗、主窗口一致。"""

    def __init__(self, close_hover: str = "#e74c3c",
                 assets_dir: Path | None = None,
                 bg_path: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg_pixmap: QPixmap | None = None
        if bg_path:
            pm = QPixmap(bg_path)
            if not pm.isNull():
                self._bg_pixmap = pm
        self._dragging = False
        self._drag_start = QPoint()

        self.setWindowTitle("关于 MD Stats")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.Dialog
        )
        self.setFixedSize(420, 320)
        self.setObjectName("aboutDialog")
        self._apply_dwm()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 标题栏
        bar = QWidget()
        bar.setFixedHeight(36)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 4, 0)
        bl.addWidget(QLabel("  关于 MD Stats"))
        bl.addStretch()
        from ui.titlebar import _TitleBarButton
        ad = assets_dir or (get_project_root() / "resource")
        btn = _TitleBarButton("title_close", ad, bar)
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {close_hover}; "
            f"border-color: {close_hover}; }}"
        )
        btn.clicked.connect(self.accept)
        bl.addWidget(btn)
        outer.addWidget(bar)

        # 内容 — 直接使用模块级常量
        import html as _html
        content = QLabel()
        content.setWordWrap(True)
        content.setOpenExternalLinks(True)
        content.setTextFormat(Qt.TextFormat.RichText)
        lines = [
            f"<h3>MD Stats  {_html.escape(VERSION)}</h3>",
            f"<p>{_html.escape(DESCRIPTION)}</p>",
            f"<p>作者: {_html.escape(AUTHOR)} | "
            f"协议: {_html.escape(LICENSE)}</p>",
        ]
        if REPO_URL:
            lines.append(
                f'<p><a href="{_html.escape(REPO_URL)}">'
                f'{_html.escape(REPO_URL)}</a></p>'
            )
        if ACKNOWLEDGMENTS:
            ack = ACKNOWLEDGMENTS.replace("\n", "<br>")
            lines.append(f"<p><b>特别鸣谢</b><br>{ack}</p>")
        content.setText("".join(lines))
        content.setStyleSheet(
            "padding: 16px; font-size: 13px; background: transparent;"
            "color: palette(text);"
        )
        outer.addWidget(content, 1)

        # 按钮
        bw = QWidget()
        bwl = QHBoxLayout(bw)
        bwl.addStretch()
        bok = QPushButton("确定")
        bok.clicked.connect(self.accept)
        bok.setDefault(True)
        bwl.addWidget(bok)
        bwl.setContentsMargins(16, 0, 16, 12)
        outer.addWidget(bw)

    def _apply_dwm(self) -> None:
        import ctypes, os
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(ctypes.c_int(2)),
                ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    # ---- 背景绘制 ----
    def paintEvent(self, event) -> None:
        if self._bg_pixmap is not None:
            painter = QPainter(self)
            pm = self._bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, pm)
            painter.end()
        super().paintEvent(event)

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
