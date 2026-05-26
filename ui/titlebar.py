"""自定义标题栏控件 — 配合无边框窗口使用。

================================================================================
为什么需要自定义标题栏？
================================================================================

程序主窗口设置了无边框模式（FramelessWindowHint），这意味着 Windows
自带的标题栏（最小化/关闭按钮、拖拽移动）全部消失。为了用户能正常操作
窗口，我们需要自己画一个标题栏，实现三个功能：

    1. 显示程序图标和标题文字
    2. 提供最小化和关闭按钮（用图标文件或矢量绘制）
    3. 支持鼠标拖拽移动窗口位置

================================================================================
结构
================================================================================

┌──────────────────────────────────────────────────────┐
│  [icon]  窗口标题                        [─]  [×]    │
└──────────────────────────────────────────────────────┘

整个标题栏是一个 QWidget，内部用 QHBoxLayout（水平布局）从左到右排列：
  图标 → 标题文字 → 弹性空白 → 最小化按钮 → 关闭按钮

================================================================================
使用的 Qt 概念速查
================================================================================

QPainter   — Qt 的"画笔"，用来在控件上画线条、图形、文字
QPixmap    — Qt 的"图片对象"，从 .png 文件加载
QGraphicsDropShadowEffect — 文字阴影特效
Signal     — Qt 的信号机制：按钮被点击时发射信号，外部接收信号执行操作
QPoint     — Qt 的"坐标点"（x, y），用来记录鼠标位置
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QWidget


# =============================================================================
# _TitleBarButton — 标题栏上的最小化/关闭按钮
# =============================================================================

class _TitleBarButton(QPushButton):
    """标题栏按钮（最小化 ─ 或 关闭 ×）。

    继承自 QPushButton（Qt 的标准按钮），但重写了 paintEvent 方法，
    用自己的方式绘制按钮图标，而不是用 QPushButton 默认的文字。

    绘制优先级：
        1. 如果主题文件夹下有 icon.png 文件 → 加载图片绘制
        2. 如果没有图片 → 用 QPainter 画矢量线条作为回退
           （这样即使没有任何图片资源，按钮也能正常显示）
    """

    def __init__(
        self, icon_name: str, assets_dir: Path, parent: QWidget | None = None
    ) -> None:
        """创建标题栏按钮。

        参数:
            icon_name  — "title_min" 或 "title_close"，用于拼出文件名和判断画哪种图标
            assets_dir — 主题的 assets 文件夹路径，图片从这里加载
            parent     — 父控件（标题栏）
        """
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_pixmap: QPixmap | None = None  # 如果加载到图片，存在这里

        # 尝试从主题文件夹加载图标图片（文件名如 title_min.png / title_close.png）
        icon_path = assets_dir / f"{icon_name}.png"
        if icon_path.exists():
            self._icon_pixmap = QPixmap(str(icon_path))

        # 按钮外观设置
        self.setFixedSize(40, 30)       # 固定宽 40px、高 30px
        self.setFlat(True)               # 扁平化：去掉 QPushButton 默认的凸起边框
        self.setCursor(Qt.CursorShape.PointingHandCursor)  # 鼠标悬停时显示"手指"光标

    def paintEvent(self, event) -> None:
        """绘制按钮的内容（Qt 在需要刷新按钮外观时自动调用此方法）。

        执行流程：
            1. 先调用父类的 paintEvent，让 QSS 样式（如 hover 背景色）生效
            2. 然后在此之上绘制图标（图片或矢量线条）
        """
        # ---- 第1步：让 QPushButton 先画背景和边框（hover 等 QSS 样式在此生效） ----
        super().paintEvent(event)

        # ---- 第2步：在此之上画图标 ----
        painter = QPainter(self)                      # 创建画笔，绑定到当前按钮
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)  # 开启抗锯齿（让线条更平滑）
        rect = self.rect()                            # 获取按钮的矩形区域（宽 40px，高 30px）

        # 情况 A：有图片 → 填满按钮 + hover 半透明遮罩
        if self._icon_pixmap:
            # 图片填满整个按钮
            pm = self._icon_pixmap.scaled(
                rect.width(), rect.height(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, pm)
            # hover 状态下叠加半透明遮罩，关闭按钮用红色，其余用深色
            if self.underMouse():
                if self._icon_name == "title_close":
                    painter.fillRect(rect, QColor(220, 50, 50, 100))
                else:
                    painter.fillRect(rect, QColor(255, 255, 255, 100))
            return

        # 情况 B：没有图片 → 用矢量线条回退绘制
        # 从 QPalette（调色板）取文字颜色，确保按钮图标颜色跟随主题
        color = self.palette().color(self.foregroundRole())
        pen = QPen(color, 1.5)                         # 创建画笔：颜色 + 线宽 1.5px
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)        # 线条端点设为圆形
        painter.setPen(pen)

        cx, cy = rect.width() // 2, rect.height() // 2   # 按钮中心点坐标

        if self._icon_name == "title_min":
            # 画一条水平线（最小化图标：─）
            painter.drawLine(cx - 5, cy, cx + 5, cy)
        elif self._icon_name == "title_close":
            # 画两条交叉的斜线（关闭图标：×）
            painter.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
            painter.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)

        painter.end()  # 释放画笔资源


# =============================================================================
# TitleBar — 可拖拽的完整标题栏
# =============================================================================

class TitleBar(QWidget):
    """可拖拽的自定义标题栏控件。

    功能：
        - 显示程序图标（从资源目录加载 app_icon.png）
        - 显示标题文字（支持自定义颜色、字号、字体、阴影）
        - 提供最小化和关闭按钮
        - 鼠标按住标题栏拖拽可以移动窗口

    信号（Signal）：
        minimize_clicked — 用户点击了最小化按钮
        close_clicked    — 用户点击了关闭按钮

    外部使用方式：
        title_bar = TitleBar("MD Stats", theme_config, assets_dir)
        title_bar.minimize_clicked.connect(window.showMinimized)
        title_bar.close_clicked.connect(window.close)
    """

    # 定义信号（点击按钮时发射，由 MainWindow 连接处理）
    minimize_clicked = Signal()   # 最小化按钮点击信号
    close_clicked = Signal()      # 关闭按钮点击信号

    def __init__(
        self,
        title: str,          # 标题文字，如 "MD Stats"
        config: dict,        # 主题配置中的 [titlebar] 部分（颜色、字号、悬停色等）
        assets_dir: Path,    # 资源目录路径（图标图片从这个文件夹加载）
        parent: QWidget | None = None,
    ) -> None:
        """构建标题栏。

        布局结构（QHBoxLayout 从左到右）：
            [程序图标]  [标题文字]  <弹性空白>  [最小化按钮]  [关闭按钮]
        """
        super().__init__(parent)

        # ---- 从主题配置中读取外观参数 ----
        height = config.get("height", 36)           # 标题栏总高度
        icon_size = config.get("icon_size", 20)     # 图标显示尺寸
        self._assets_dir = assets_dir               # 保存 assets 路径，供 reload_style 用

        # ---- 拖拽状态变量 ----
        self._dragging = False       # 标志位：当前是否正在拖拽窗口
        self._drag_start = QPoint()  # 记录拖拽开始时鼠标的位置

        # ---- 设置标题栏自身外观 ----
        self.setFixedHeight(height)          # 固定高度，宽度由父窗口决定
        self.setObjectName("titleBar")       # 设置对象名，QSS 可通过 #titleBar 选择器定位

        # ---- 创建水平布局（所有子控件从左到右排列） ----
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)   # 内边距：左 10px，右 4px
        layout.setSpacing(4)                       # 控件间距 4px

        # =====================================================================
        # 第 1 部分：程序图标
        # =====================================================================
        self._icon_label = QLabel()                # 用 QLabel 显示图标图片
        icon_path = assets_dir / "app_icon.png"    # 图标文件路径
        if icon_path.exists():
            pm = QPixmap(str(icon_path)).scaled(
                icon_size, icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._icon_label.setPixmap(pm)         # 把缩放后的图标设置到 QLabel 上
        self._icon_label.setFixedSize(icon_size + 8, height)  # 图标占位大小
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 居中
        layout.addWidget(self._icon_label)         # 添加到标题栏布局

        # =====================================================================
        # 第 2 部分：标题文字
        # =====================================================================
        title_color = config.get("text_color", "#cccccc")
        title_size = config.get("text_size", 12)
        title_font_family = config.get("text_font", "")    # 自定义字体（空=用默认字体）
        self._title_label = QLabel(title)                  # 用 QLabel 显示标题

        # 根据是否有自定义字体，使用不同的 QSS 样式字符串
        # QSS = Qt Style Sheet，类似 CSS，用来设置控件外观
        if title_font_family:
            self._title_label.setStyleSheet(
                f"color: {title_color}; font-size: {title_size}px; "
                f"font-family: {title_font_family}; "
                "font-weight: 700; letter-spacing: 1px; "     # 粗体 + 字间距
                "background: transparent; border: none;"       # 透明背景、无边框
            )
        else:
            self._title_label.setStyleSheet(
                f"color: {title_color}; font-size: {title_size}px; "
                "font-weight: 600; background: transparent; border: none;"
            )

        # 文字阴影（可选特性，只有主题配置了 text_shadow 才启用）
        # QGraphicsDropShadowEffect 是 Qt 的阴影特效，可以给文字加发光/晕染效果
        shadow_color = config.get("text_shadow", "")
        if shadow_color:
            effect = QGraphicsDropShadowEffect(self._title_label)
            effect.setColor(QColor(shadow_color))   # 阴影颜色
            effect.setBlurRadius(8)                  # 模糊半径（越大越柔和）
            effect.setOffset(0, 1)                   # 阴影偏移（右 0px，下 1px）
            self._title_label.setGraphicsEffect(effect)

        layout.addWidget(self._title_label)          # 添加到标题栏布局
        layout.addStretch()                          # 弹性空白：把后面的按钮推到最右边

        # =====================================================================
        # 第 3 部分：最小化按钮
        # =====================================================================
        btn_hover = config.get("btn_hover_bg", "#3a3a5a")           # 鼠标悬停时的背景色
        btn_close_hover = config.get("btn_close_hover", "#e74c3c")  # 关闭按钮悬停色
        self._btn_min = _TitleBarButton("title_min", assets_dir, self)  # 创建最小化按钮
        self._btn_min.setObjectName("titleMinBtn")
        self._btn_min.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"               # 正常状态：透明背景
            f"QPushButton:hover {{ background-color: {btn_hover}; "
            f"border-color: {btn_hover}; }}"       # 鼠标悬停：显示背景色
        )
        self._btn_min.clicked.connect(self.minimize_clicked.emit)  # 连接点击 → 信号
        layout.addWidget(self._btn_min)

        # =====================================================================
        # 第 4 部分：关闭按钮
        # =====================================================================
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

    # -------------------------------------------------------------------------
    # 公开方法
    # -------------------------------------------------------------------------

    def set_title(self, title: str) -> None:
        """修改标题文字（如切换主题后刷新）。"""
        self._title_label.setText(title)

    def set_icon(self, pixmap: QPixmap) -> None:
        """更换程序图标。"""
        self._icon_label.setPixmap(pixmap)

    def reload_style(self, config: dict, assets_dir: Path | None = None) -> None:
        """主题切换后重新应用标题栏样式和图标。"""
        if assets_dir is not None:
            self._assets_dir = assets_dir
            # 重新加载按钮图标
            for btn, name in ((self._btn_min, "title_min"), (self._btn_close, "title_close")):
                icon_path = self._assets_dir / f"{name}.png"
                btn._icon_pixmap = QPixmap(str(icon_path)) if icon_path.exists() else None
        text_color = config.get("text_color", "#cccccc")
        text_size = config.get("text_size", 12)
        title_font_family = config.get("text_font", "")
        btn_hover_bg = config.get("btn_hover_bg", "#3a3a5a")
        btn_close_hover = config.get("btn_close_hover", "#e74c3c")

        # 更新标题文字样式
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

        # 更新文字阴影
        shadow_color = config.get("text_shadow", "")
        if shadow_color:
            effect = QGraphicsDropShadowEffect(self._title_label)
            effect.setColor(QColor(shadow_color))
            effect.setBlurRadius(8)
            effect.setOffset(0, 1)
            self._title_label.setGraphicsEffect(effect)
        else:
            # noinspection PyTypeChecker
            self._title_label.setGraphicsEffect(None)

        # 更新按钮悬停样式
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

    # =========================================================================
    # 拖拽逻辑 — 实现"鼠标按住标题栏拖动窗口"功能
    #
    # 原理：
    #   1. mousePressEvent  — 鼠标按下时，记录起始位置，设 _dragging = True
    #   2. mouseMoveEvent   — 鼠标移动时，计算位移 delta，用 window.move() 移动窗口
    #   3. mouseReleaseEvent — 鼠标松开时，设 _dragging = False，停止移动
    #
    # globalPosition() 返回鼠标在屏幕上的绝对坐标（不是相对于标题栏的坐标）
    # 每次移动时用"当前位置 - 上一次位置"算出偏移量，加到窗口位置
    # =========================================================================

    def mousePressEvent(self, event) -> None:
        """鼠标按下：记录拖拽起始位置，准备移动窗口。"""
        if event.button() == Qt.MouseButton.LeftButton:  # 只响应左键
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()  # 记录鼠标在屏幕上的绝对位置
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """鼠标移动：如果正在拖拽，计算偏移并移动窗口。"""
        if self._dragging:
            # 计算鼠标从上次位置移动了多少像素
            delta = event.globalPosition().toPoint() - self._drag_start
            window = self.window()  # 获取这个标题栏所属的顶层窗口（MainWindow）
            if window:
                window.move(window.pos() + delta)  # 把窗口移到新位置
            self._drag_start = event.globalPosition().toPoint()  # 更新起始位置
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """鼠标松开：停止拖拽。"""
        self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, _event) -> None:
        """双击标题栏：本程序不需要最大化，空实现即可。

        如果将来需要双击最大化功能，可以在这里添加 window.showMaximized()。
        """
        pass
