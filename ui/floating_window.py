"""悬浮统计窗 — 无边框、半透明、可拖拽、始终置顶。

================================================================================
概述
================================================================================

悬浮窗是一个小型置顶窗口，实时显示当前卡组的关键统计数据（对局数、胜率等）。
常用于游戏全屏时叠加在游戏画面上方，方便玩家不切窗口就能看到对局统计。

典型使用场景：
    - 游戏全屏时，悬浮窗在游戏画面角落显示数据
    - OBS 直播/录屏时，悬浮窗作为数据源被捕获
    - 多任务时，悬浮窗始终可见，无需切回主窗口

================================================================================
核心特性
================================================================================

1. **无边框 + 置顶**
   窗口没有标题栏和边框，使用 FramelessWindowHint + WindowStaysOnTopHint。
   两种模式可选：
   - Tool 模式（默认）：无任务栏图标，OBS 需用"显示器捕获"
   - Window 模式（OBS 模式）：有任务栏图标，OBS 可用"窗口捕获"

2. **半透明背景**
   通过 WA_TranslucentBackground 属性实现窗口背景透明，
   再在 paintEvent 中手绘圆角矩形作为可见背景。
   透明度由 config.toml [floating_window].opacity 控制（0-100）。

3. **可拖拽移动**
   鼠标左键按住窗口任意位置即可拖拽，位置自动保存到 .app_state.json。

4. **动态行配置**
   显示哪些统计行由 config.toml [floating_window].rows 控制。
   行名通过 _ROW_KEY_MAP 映射到 recorder.compute_stats() 输出的统计键。
   支持单值行（如"对局数"）和合并行（如"胜/负"显示为 "10 / 5"）。

5. **主题背景图**
   部分主题（如 macaron）提供 float_bg.png 背景图。
   开启 use_theme_bg 后，背景图叠加在纯色之上，圆角裁剪。

================================================================================
数据流
================================================================================

    MainWindow._refresh_float_window()
        → FloatingWindow.update_content(deck_name, stats_dict)
            → 遍历 _rows，通过 _ROW_KEY_MAP 查找统计键
            → 更新每个 QLabel 的文本

    MainWindow._on_reload_config()
        → FloatingWindow.update_style(cfg, float_bg_path)
            → 重新应用背景色/透明度/字号/字体/背景图
        → FloatingWindow.set_rows(new_rows)
            → 清空旧标签，重建新标签
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

# 行名 → 统计键元组的映射表
# 键 = 用户可见的行名（如"胜/负"），值 = compute_stats() 输出字典中的键
# 元组长度 1 = 单值直接显示（如"对局数"→ "15"）
# 元组长度 2 = 合并显示为 "v1 / v2"（如"胜/负"→ "10 / 5"）
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

# 默认显示的行（用户未配置 [floating_window].rows 时使用）
_DEFAULT_ROWS = ("卡组", "对局数", "胜/负", "赢/输硬币",
                 "赢硬币概率", "赢硬币胜率", "输硬币胜率", "综合胜率")


class FloatingWindow(QWidget):
    """对局统计悬浮窗 — 动态行数 + 纯色/图片背景 + 可拖拽。

    窗口布局为两列网格（QGridLayout）：
        左列 = 行名标签（QLabel，左对齐）
        右列 = 数值标签（QLabel，右对齐）
        可选底部状态行（跨两列，居中）

    外观由 update_style() 控制，内容由 update_content() 刷新，
    行配置由 set_rows() 动态替换。位置持久化由 MainWindow 管理。
    """

    _DEFAULT_W = 250
    _DEFAULT_H = 330

    def __init__(self, parent: QWidget | None = None,
                 rows: list[str] | None = None) -> None:
        """初始化悬浮窗。

        创建两列网格布局，左列为行名、右列为数值。
        窗口类型根据 obs_mode 配置决定（Tool 或 Window）。
        初始尺寸根据行数和默认字号计算。

        Args:
            parent: 父控件（通常为 None，悬浮窗是独立顶层窗口）。
            rows:   显示的统计行名称列表，如 ["卡组", "对局数", "胜/负"]。
                    传入 None 或空列表时使用 _DEFAULT_ROWS 默认行。
                    行名必须是 _ROW_KEY_MAP 中定义的键。
        """
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
            ico = get_project_root() / "resource" / "icons" / "floating_window_icon.png"
            if ico.exists():
                self.setWindowIcon(QIcon(str(ico)))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        w0, h0 = self._DEFAULT_W, 40 + len(self._rows) * 26
        self.setMinimumSize(w0, h0)
        self.setMaximumSize(w0 + 200, h0 + 200)
        self.resize(w0, h0)

        self._grid = QGridLayout(self)
        self._grid.setSizeConstraint(QGridLayout.SizeConstraint.SetNoConstraint)
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

        # 状态行（默认不加入布局，由 enable_status() 控制）
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.hide()
        self._show_status = False

        self._apply_style()

    # ------------------------------------------------------------------
    # 尺寸计算
    # ------------------------------------------------------------------

    def _content_height(self) -> int:
        """计算当前内容所需的最小高度（行 + 可选状态行 + margin）。

        考虑三个因素：
            1. 行数 × 行高（行高随 font_size 动态估算）
            2. show_status 时的额外 24px
            3. 上下 margin 40px
        返回值保证不低于 60px。
        """
        # font_size 越大行高越大；粗体 20px 字约需 28px 行高
        line_h = max(26, self._font_size + 8)
        spacing = 6
        n = len(self._rows)
        rows_h = n * line_h + max(n - 1, 0) * spacing
        extra = 24 if self._show_status else 0
        return max(40 + rows_h + extra, 60)

    def _update_size_constraints(self) -> None:
        """根据当前行数、font_size、show_status 同步更新窗口尺寸约束。

        minimumSize / maximumSize 只在 __init__ 中设置过一次，
        如果行数或 status 行发生变化而不同步更新，resize 时
        Windows 可能因约束不一致而发出 setGeometry 警告。
        """
        w0 = self._DEFAULT_W
        content_h = self._content_height()
        self.setMinimumSize(w0, content_h)
        self.setMaximumSize(w0 + 200, content_h + 200)

    # ------------------------------------------------------------------
    # 状态行
    # ------------------------------------------------------------------

    def enable_status(self, enabled: bool) -> None:
        """显示/隐藏底部状态行并调整窗口高度。

        状态行显示检测状态（如"已识别: 先攻 — 等待胜负…"），
        跨两列居中显示，字号自动缩放适应宽度。
        隐藏时从布局中移除并设最大尺寸为 0，防止占位。
        """
        self._show_status = enabled
        if enabled:
            self._grid.addWidget(self._status_label, len(self._rows), 0, 1, 2)
            self._status_label.setMaximumSize(16777215, 16777215)
            self._status_label.show()
        else:
            self._status_label.hide()
            self._grid.removeWidget(self._status_label)
            self._status_label.setMaximumSize(0, 0)  # sizeHint 归零
        self._update_size_constraints()
        h = self._content_height()
        self.resize(self._DEFAULT_W, h)

    def update_status(self, text: str) -> None:
        """更新底部状态行文字，字号自动缩放以适应行宽。

        从 16px 向下尝试直到文字宽度不超过可用宽度（窗口宽 - 50px margin），
        最低到 9px。这样长消息自动缩小、短消息保持清晰。

        Args:
            text: 要显示的状态消息（如"已识别: 赢硬币 — 等待先后攻…"）。
        """
        if not self._show_status:
            return
        self._status_label.setText(text)
        from PySide6.QtGui import QFontMetrics
        avail = self._DEFAULT_W - 50
        font = self._status_label.font()
        for sz in range(16, 8, -1):  # 上限 16px，不超出固定行高
            font.setPixelSize(sz)
            if QFontMetrics(font).horizontalAdvance(text) <= avail:
                break
        self._status_label.setFont(font)

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
        """生成行标签和数值标签的 QSS 样式字符串。

        包含文字颜色、字号、粗体、透明背景和无边框。
        字体族（font_family）仅在有值时追加。
        """
        css = (
            f"color: {self._text_color}; font-size: {self._font_size}px;"
            f"font-weight: bold; background: transparent; border: none;"
        )
        if self._font_family:
            css += f" font-family: {self._font_family};"
        return css

    def _apply_style(self) -> None:
        """将 _style_sheet() 生成的 QSS 应用到所有标签。

        状态行标签单独处理——只设颜色和粗体，字号由 update_status() 动态缩放。
        """
        ss = self._style_sheet()
        for lbl in self._labels:
            lbl.setStyleSheet(ss)
        for val in self._values:
            val.setStyleSheet(ss)
        # 状态行字号由 update_status 自动缩放，这里只设颜色
        self._status_label.setStyleSheet(
            f"color: {self._text_color}; font-weight: bold; background: transparent; border: none;")

    def update_style(self, cfg: dict,
                     float_bg_path: str | None = None) -> None:
        """按 config.toml [floating_window] 段更新外观。

        float_bg_path: theme.toml float_bg 图片绝对路径（可选）。
                       图片不存在或为空时回退纯色。
        """
        w = cfg.get("width", self._DEFAULT_W)
        # 先更新 font_size，再计算内容高度（_content_height 依赖 _font_size）
        self._font_size = cfg.get("font_size", 14)
        self._text_color = cfg.get("text_color", "#000000")
        self._font_family = cfg.get("font_family", "")
        content_h = self._content_height()
        h = cfg.get("height", content_h)
        # 确保配置高度不小于实际内容高度，避免 Windows setGeometry 警告
        self._update_size_constraints()
        self.resize(w, max(h, content_h))

        bg = cfg.get("bg_color", "#98d4bb")
        opacity_pct = cfg.get("opacity", 50)

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
        """动态替换显示行，清空旧标签后重建。

        用于用户在设置弹窗中修改悬浮窗行配置后，立即更新悬浮窗显示。
        旧标签用 deleteLater() 安全销毁，新标签重新添加到网格布局。

        Args:
            rows: 新的行名列表，如 ["卡组", "对局数", "综合胜率"]。
        """
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
        self._update_size_constraints()
        h = self._content_height()
        self.resize(self.width(), h)

    # ------------------------------------------------------------------
    # 内容刷新
    # ------------------------------------------------------------------

    def update_content(self, deck_name: str, stats: dict | None) -> None:
        """用统计数据和卡组名刷新悬浮窗内容。

        遍历当前 _rows 列表，通过 _ROW_KEY_MAP 找到每个行名对应的统计键，
        然后从 stats 字典中取值更新 QLabel。

        Args:
            deck_name: 当前输入框中的卡组名称（显示在"卡组"行）。
            stats:     compute_stats() 返回的统计字典，键为 STATS_COLUMNS 中的列名。
                       传入 None 时，所有数值显示为 "-"（通常在数据为空时）。
        """
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
        """鼠标按下 — 左键按下时记录起始位置，进入拖拽模式。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """鼠标移动 — 拖拽模式下移动窗口位置。"""
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """鼠标释放 — 退出拖拽模式。"""
        self._dragging = False
        super().mouseReleaseEvent(event)
