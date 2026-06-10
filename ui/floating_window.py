"""悬浮统计窗 — 无边框、半透明、可拖拽、始终置顶。

支持动态行配置和主题背景图。
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

# 行名 → (统计键元组)，长度 1=单值，2=合并显示 "v1 / v2"
_ROW_KEY_MAP: dict[str, tuple[str, ...]] = {
    "卡组":       ("卡组",),
    "对局数":     ("对局数",),
    "胜/负":      ("胜", "负"),
    "赢/输硬币":  ("赢硬币次数", "输硬币次数"),
    "综合胜率":   ("胜率",),
    "赢硬币概率": ("赢硬币概率",),
    "赢硬币胜率": ("赢硬币胜率",),
    "输硬币胜率": ("输硬币胜率",),
    "先攻次数":   ("先攻次数",),
    "后攻次数":   ("后攻次数",),
    "先攻胜":     ("先攻胜",),
    "后攻胜":     ("后攻胜",),
    "先攻胜率":   ("先攻胜率",),
    "后攻胜率":   ("后攻胜率",),
    "升段/降段":  ("升段次数", "降段次数"),
    "升段胜率":   ("升段胜率",),
    "降段胜率":   ("降段胜率",),
}

_DEFAULT_ROWS = ("卡组", "对局数", "胜/负", "赢/输硬币",
                 "赢硬币概率", "赢硬币胜率", "输硬币胜率", "综合胜率")


class FloatingWindow(QWidget):
    """对局统计悬浮窗，动态行数 + 纯色/图片背景。"""

    _DEFAULT_W = 250
    _DEFAULT_H = 330

    def __init__(self, parent: QWidget | None = None,
                 rows: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MD Stats 悬浮窗")
        self._dragging = False
        self._drag_start = QPoint()
        self._bg_color = QColor(152, 212, 187, 128)
        self._bg_pixmap: QPixmap | None = None
        self._text_color = "#000000"
        self._font_size = 20
        self._font_family = ""
        self._rows: tuple[str, ...] = tuple(rows) if rows else _DEFAULT_ROWS

        # 根据 obs_mode 决定窗口类型：Window（OBS 可捕获，有任务栏图标）
        #                         或 Tool（无任务栏图标，OBS 需用显示器捕获）
        from src.config import load_config
        obs = load_config().get("notification", {}).get("obs_mode", False)
        self.setWindowFlags(
            (Qt.WindowType.Window if obs else Qt.WindowType.Tool)
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # OBS 模式下的任务栏图标
        if obs:
            from PySide6.QtGui import QIcon
            from src.config import get_project_root
            icon_path = get_project_root() / "resource" / "icons" / "floating_window_icon.png"
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self._DEFAULT_W,
                          40 + len(self._rows) * 26)

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(20, 20, 20, 20)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(6)

        self._labels: list[QLabel] = []
        self._values: list[QLabel] = []
        for r, text in enumerate(self._rows):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(lbl, r, 0)
            self._labels.append(lbl)

            val = QLabel("-")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(val, r, 1)
            self._values.append(val)

        self._apply_style()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        """手绘圆角背景：纯色打底 + 可选图片叠加。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        margin = 8
        path.addRoundedRect(margin, margin,
                            self.width() - margin * 2,
                            self.height() - margin * 2, 10, 10)

        # 先涂纯色打底
        painter.fillPath(path, self._bg_color)

        if self._bg_pixmap is not None:
            # 有背景图：在圆角区域上叠加图片
            painter.setClipPath(path)
            scaled = self._bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
            painter.setClipping(False)

        painter.end()

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------

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

    def update_style(self, cfg: dict,
                     float_bg_path: str | None = None) -> None:
        """按 config.toml [floating_window] 段更新外观。

        float_bg_path: theme.toml float_bg 图片绝对路径（可选）。
                       图片不存在或为空时回退纯色。
        """
        w = cfg.get("width", self._DEFAULT_W)
        h = cfg.get("height", 40 + len(self._rows) * 26)
        self.setFixedSize(w, max(h, 40 + len(self._rows) * 26))

        bg = cfg.get("bg_color", "#98d4bb")
        opacity_pct = cfg.get("opacity", 50)
        self._font_size = cfg.get("font_size", 14)
        self._text_color = cfg.get("text_color", "#000000")
        self._font_family = cfg.get("font_family", "")

        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        alpha = int(opacity_pct / 100 * 255)
        self._bg_color = QColor(r, g, b, alpha)

        # 背景图处理
        if float_bg_path:
            pm = QPixmap(float_bg_path)
            self._bg_pixmap = pm if not pm.isNull() else None
        else:
            self._bg_pixmap = None

        self._apply_style()
        self.update()

    # ------------------------------------------------------------------
    # 行管理
    # ------------------------------------------------------------------

    def set_rows(self, rows: list[str]) -> None:
        """动态替换显示行，清空旧标签后重建。"""
        new_rows = tuple(rows) if rows else _DEFAULT_ROWS
        if new_rows == self._rows:
            return
        self._rows = new_rows

        for lbl in self._labels + self._values:
            self._grid.removeWidget(lbl)
            lbl.deleteLater()
        self._labels.clear()
        self._values.clear()

        for r, text in enumerate(self._rows):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(lbl, r, 0)
            self._labels.append(lbl)

            val = QLabel("-")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(val, r, 1)
            self._values.append(val)

        self._apply_style()
        h = 40 + len(self._rows) * 26
        self.setFixedSize(self.width(), h)

    # ------------------------------------------------------------------
    # 内容刷新
    # ------------------------------------------------------------------

    def update_content(self, deck_name: str, stats: dict | None) -> None:
        """用统计数据和卡组名刷新悬浮窗内容。"""
        if stats is None:
            for v in self._values:
                v.setText("-")
            return

        for i, row_name in enumerate(self._rows):
            keys = _ROW_KEY_MAP.get(row_name)
            if keys is None:
                self._values[i].setText("-")
                continue

            if len(keys) == 1:
                key = keys[0]
                if key == "卡组":
                    self._values[i].setText(deck_name or "(未指定)")
                else:
                    self._values[i].setText(str(stats.get(key, "-")))
            else:
                v1 = stats.get(keys[0], 0)
                v2 = stats.get(keys[1], 0)
                self._values[i].setText(f"{v1} / {v2}")

    # ------------------------------------------------------------------
    # 拖拽
    # ------------------------------------------------------------------

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
