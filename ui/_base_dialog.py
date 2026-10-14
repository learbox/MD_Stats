"""无边框弹窗基类 — ConfigDialog / RankStatsDialog / MessageDialog 的共享代码。

提取以下公共逻辑：
    - 背景图加载与 paintEvent
    - DWM 窗口圆角
    - 鼠标拖拽移动
    - 主题化标题栏（标题 + 关闭按钮）
    - 主题化底色计算（背景图半透明 / 纯色偏移）
"""

import ctypes

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QWidget

from src.config import get_project_root


class _BaseFramelessDialog(QDialog):
    """无边框 + 可拖拽 + 背景图支持的弹窗基类。

    子类需在 __init__ 中：
        1. 调用 self._init_background(bg_path)  加载背景图
        2. 调用 self._init_drag()               初始化拖拽状态
        3. 设置 self.setWindowFlags(FramelessWindowHint | Window | Dialog)
        4. 设置 self.setAttribute(WA_StyledBackground, True)
        5. 调用 self._apply_dwm_round_corners() 启用 Win11 圆角

    另提供两个主题化构建件（供子类搭标题栏与底色）：
        - self._make_titlebar(标题, 对象名)    标题 + 主题化关闭按钮
        - self._themed_background_colors(...)  对话框底色 + 内容区背景
    """

    # 类型注解声明（实值在 _init_background / _init_drag 中赋值）
    _bg_pixmap: QPixmap | None
    _dragging: bool
    _drag_start: QPoint

    def _init_background(self, bg_path: str | None) -> None:
        """加载主题背景图，如果路径无效或文件不存在则 _bg_pixmap 为 None。"""
        self._bg_pixmap: QPixmap | None = None
        if bg_path:
            pm = QPixmap(bg_path)
            if not pm.isNull():
                self._bg_pixmap = pm

    def _init_drag(self) -> None:
        """初始化鼠标拖拽状态。"""
        self._dragging = False
        self._drag_start = QPoint()

    # =========================================================================
    # 背景绘制
    # =========================================================================

    def paintEvent(self, event) -> None:
        """有背景图则贴图填充，无图走 QSS 纯色背景。"""
        painter = QPainter(self)
        bg = self._bg_pixmap
        if bg is not None:
            scaled = bg.scaled(
                self.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
        painter.end()
        super().paintEvent(event)

    # =========================================================================
    # DWM 圆角（Windows 11）
    # =========================================================================

    def _apply_dwm_round_corners(self) -> None:
        """给无边框窗口加上 Win11 原生圆角（DWM API）。"""
        try:
            hwnd = int(self.winId())
            dwmwa = 33                         # DWMWA_WINDOW_CORNER_PREFERENCE
            dwmwcp_round = 2                   # 圆角模式
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, dwmwa,
                ctypes.byref(ctypes.c_int(dwmwcp_round)),
                ctypes.sizeof(ctypes.c_int),
            )
        except (OSError, AttributeError):
            pass

    # =========================================================================
    # 拖拽
    # =========================================================================

    def mousePressEvent(self, event) -> None:
        """左键按下时记录窗口内相对位置，进入拖拽模式。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """拖拽时保持鼠标与窗口的相对位置不变。"""
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """释放鼠标退出拖拽模式。"""
        self._dragging = False
        super().mouseReleaseEvent(event)

    # =========================================================================
    # 主题化构建件（各弹窗共用，保证外观一致）
    # =========================================================================

    def _make_titlebar(self, title_text: str, object_name: str) -> QWidget:
        """创建顶部自定义标题栏：标题文字 + 主题化关闭按钮。

        与 ConfigDialog / RankStatsDialog 的标题栏结构一致：
            - 背景透明，让下方内容区的背景透出
            - 关闭按钮复用主窗口标题栏的 _TitleBarButton（自带 hover 图标）
            - 关闭按钮 hover 色取 self._colors 的 btn_close_hover，缺省红色

        点击关闭按钮 → reject()（子类如用 accept/reject 语义可自行覆盖）。
        """
        bar = QWidget()
        bar.setObjectName(object_name)
        bar.setFixedHeight(36)  # 固定高度，与主窗口标题栏观感一致
        bar.setStyleSheet(f"#{object_name} {{ background: transparent; }}")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 4, 0)

        title = QLabel(title_text)
        title.setStyleSheet("font-size: 13px; font-weight: bold; "
                            "background: transparent; border: none;")
        layout.addWidget(title)
        layout.addStretch()  # 标题靠左，关闭按钮推到右侧

        from ui.titlebar import _TitleBarButton
        assets = get_project_root() / "resource"
        btn_close = _TitleBarButton("title_close", assets, bar)
        close_hover = getattr(self, "_colors", {}).get("btn_close_hover", "#e74c3c")
        # 默认透明，hover 变主题红
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {close_hover}; "
            f"border-color: {close_hover}; }}"
        )
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)
        return bar

    def _themed_background_colors(self, widget_bg: str, main_bg: str) -> tuple[str, str]:
        """计算主题化底色，返回 (对话框底色, 内容区背景)。

        与 RankStatsDialog 的原有规则逐字一致：
            - 有背景图主题：内容区用 widget_bg 的半透明色（alpha 180/255），
              透出底层背景图；对话框底色用 widget_bg
            - 纯色主题：对话框底色按 main_bg 深浅偏移 5 档（浅色变暗、
              深色变亮），让对话框与主窗口产生深度辨识度；内容区实色

        需在 self._init_background() 之后调用（依赖 self._bg_pixmap）。
        """
        r, g, b = int(widget_bg[1:3], 16), int(widget_bg[3:5], 16), int(widget_bg[5:7], 16)
        bg_semi = f"rgba({r},{g},{b},180)"

        if self._bg_pixmap is not None:
            return widget_bg, bg_semi

        mr, mg, mb = int(main_bg[1:3], 16), int(main_bg[3:5], 16), int(main_bg[5:7], 16)
        shift = 5
        dr = mr + shift if mr <= 128 else mr - shift
        dg = mg + shift if mg <= 128 else mg - shift
        db = mb + shift if mb <= 128 else mb - shift
        return f"#{dr:02x}{dg:02x}{db:02x}", widget_bg
