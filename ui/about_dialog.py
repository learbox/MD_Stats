"""关于弹窗 — 显示版本、作者、协议等信息的独立窗口。

================================================================================
这个文件做什么？

程序主界面有一个"关于"按钮，点击后弹出本弹窗，展示：
    - 软件名称和版本号
    - 一句话描述
    - 作者、开源协议
    - 项目仓库链接（可点击跳转）
    - 特别鸣谢（支持 HTML 超链接）

和旧版 QMessageBox 的区别：
    旧版用的是 Qt 系统弹窗（有 Windows 原生标题栏，风格和程序不一致）。
    新版是无边框 + 自定义标题栏 + DWM 圆角，视觉效果和设置弹窗、主窗口统一。

================================================================================
为什么元数据也放在这里？

    打包成 EXE 时，PyInstaller 会把 .py 文件捆绑进 exe。
    如果版本号放在 config.toml 中，exe 运行时找不到外部文件就无法读取。
    放在 .py 文件中则始终可用，修改版本号只需改这里的 VERSION 常量。

    其他文件通过 import 导入这些常量：
        from ui.about_dialog import VERSION, AUTHOR, ...
"""

from pathlib import Path

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from src.config import get_project_root

# =============================================================================
# 程序元数据 — 修改版本号、作者等请改这里
# =============================================================================

VERSION = "1.5.0"       # 当前版本号，发版前更新
AUTHOR = "learbox"       # 作者名
LICENSE = "MIT"          # 开源协议
REPO_URL = "https://github.com/learbox/mdstats_py"  # 项目仓库，留空则不显示链接
DESCRIPTION = "基于 Python + OpenCV + PySide6\nMaster Duel 对局自动统计工具"
ACKNOWLEDGMENTS = (      # 特别鸣谢，支持 HTML <a> 标签
    '<a href="https://github.com/slimpigs">KleeKlee</a>'
    " 对马卡龙主题设计提供代码支持，以及无偿提供的美术资源\n"
    '<a href="https://github.com/ULeang">ULya_tooru</a>'
    " 提供原版设计思路（mdstats C++）"
)


# =============================================================================
# AboutDialog — 关于弹窗
# =============================================================================

class AboutDialog(QDialog):
    """关于弹窗，无边框 + 自定义标题栏 + DWM 圆角。

    QDialog 是 Qt 的"模态弹窗"基类——打开时阻断主窗口操作，
    关闭后主窗口恢复响应。用 .exec() 打开，用户点关闭或确定后返回。

    弹窗结构（从上到下）：
        ┌──────────────────────────────┐
        │  关于 MD Stats           [×] │  ← 自定义标题栏（可拖拽移动）
        ├──────────────────────────────┤
        │                              │
        │  MD Stats 1.4.0              │
        │  基于 Python + OpenCV ...    │  ← 内容区（HTML 格式 QLabel）
        │  作者: learbox | 协议: MIT   │
        │  仓库: github.com/...        │
        │  特别鸣谢: KleeKlee ...      │
        │                              │
        │                    [确定]    │  ← 底部按钮
        └──────────────────────────────┘
    """

    def __init__(self, close_hover: str = "#e74c3c",
                 assets_dir: Path | None = None,
                 bg_path: str | None = None,
                 parent: QWidget | None = None,
                 widget_bg: str = "#ffffff") -> None:
        """创建关于弹窗。

        参数:
            close_hover — 关闭按钮鼠标悬停时的背景色（从主题 titlebar 配置读取）
            assets_dir  — 主题 assets 目录路径，用于加载 title_close.png 图标
            bg_path     — 背景图片路径（主题的 settings_bg），不存在时用默认背景
            parent      — 父窗口（MainWindow），用于模态关联
        """
        super().__init__(parent)

        # ---- 背景图 ----
        # 从 MainWindow 传入的主题背景图路径。QPixmap 加载失败（文件不存在或
        # 损坏）时 isNull() 返回 True，此时 _bg_pixmap 保持 None，paintEvent 跳过绘制。
        self._bg_pixmap: QPixmap | None = None
        if bg_path:
            pm = QPixmap(bg_path)
            if not pm.isNull():
                self._bg_pixmap = pm

        # ---- 拖拽状态 ----
        self._dragging = False       # 是否正在拖拽窗口
        self._drag_start = QPoint()  # 拖拽起始位置（屏幕坐标）

        # ---- 弹窗基础设置 ----
        # FramelessWindowHint — 去掉 Windows 原生标题栏，改用自定义标题栏
        # Window + Dialog          — 既是独立窗口又是模态弹窗
        self.setWindowTitle("关于 MD Stats")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.Dialog
        )
        self.setFixedSize(420, 320)        # 固定大小，不需要 resize
        self.setObjectName("aboutDialog")
        r, g, b = int(widget_bg[1:3], 16), int(widget_bg[3:5], 16), int(widget_bg[5:7], 16)
        self.setStyleSheet(f"#aboutDialog {{ background: rgba({r},{g},{b},230); }}")
        self._apply_dwm()

        # ---- 整体布局 ----
        # 外层 QVBoxLayout 从上到下排列：标题栏 → 内容 → 按钮
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)  # 边距全为 0，标题栏贴边
        outer.setSpacing(0)

        # ---- 标题栏 ----
        # 结构：QLabel("  关于 MD Stats") <弹性空白> [_TitleBarButton(×)]
        # _TitleBarButton 是主标题栏的按钮控件，自带图标填充和 hover 遮罩
        bar = QWidget()
        bar.setFixedHeight(36)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 4, 0)
        bl.addWidget(QLabel("  关于 MD Stats"))
        bl.addStretch()  # 弹性空白，把关闭按钮推到最右边

        from ui.titlebar import _TitleBarButton
        ad = assets_dir or (get_project_root() / "resource")
        btn = _TitleBarButton("title_close", ad, bar)
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {close_hover}; "
            f"border-color: {close_hover}; }}"
        )
        btn.clicked.connect(self.accept)  # QDialog.accept() → 关闭弹窗，返回 Accepted
        bl.addWidget(btn)
        outer.addWidget(bar)

        # ---- 内容区 ----
        # 用 QLabel 显示 HTML 格式的富文本。
        # setOpenExternalLinks(True) 允许用户点击超链接在浏览器中打开。
        # setTextFormat(RichText) 告诉 Qt 按 HTML 渲染（而非纯文本）。
        import html as _html
        content = QLabel()
        content.setWordWrap(True)             # 文字超宽时自动换行
        content.setOpenExternalLinks(True)    # 点链接用浏览器打开
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
            ack = ACKNOWLEDGMENTS.replace("\n", "<br>")  # 换行符转 HTML
            lines.append(f"<p><b>特别鸣谢</b><br>{ack}</p>")
        content.setText("".join(lines))
        content.setStyleSheet(
            "padding: 16px; font-size: 13px;"
            f"background: rgba({r},{g},{b},180);"  # 跟随主题背景色 + 30% 透明
            "color: palette(text);"
        )
        outer.addWidget(content, 1)  # stretch=1，占据剩余空间

        # ---- 底部按钮 ----
        bw = QWidget()
        bwl = QHBoxLayout(bw)
        bwl.addStretch()
        bok = QPushButton("确定")
        bok.clicked.connect(self.accept)
        bok.setDefault(True)  # 按 Enter 键默认触发
        bwl.addWidget(bok)
        bwl.setContentsMargins(16, 0, 16, 12)
        outer.addWidget(bw)

    # =========================================================================
    # DWM 圆角（Windows 11 原生效果）
    # =========================================================================

    def _apply_dwm(self) -> None:
        """给无边框弹窗加 Win11 原生圆角。非 Windows 系统静默跳过。

        DWM（Desktop Window Manager）是 Windows 的桌面合成引擎。
        DwmSetWindowAttribute 的第 33 号属性是窗口圆角偏好，
        值为 2 表示"使用系统默认圆角"。

        这个 API 只在 Windows 11 上有效（Win10 忽略），不影响功能。
        """
        import ctypes, os
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())            # 获取窗口句柄（HWND）
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd, 33,                        # DWMWA_WINDOW_CORNER_PREFERENCE
                ctypes.byref(ctypes.c_int(2)),   # 2 = 圆角
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass  # DWM 不可用时静默跳过

    # =========================================================================
    # 背景绘制
    # =========================================================================

    def paintEvent(self, event) -> None:
        """手绘背景：有背景图时拉伸填充整个弹窗，无图时走默认 QDialog 背景。

        QPainter 是 Qt 的"画笔"，用来在控件上手动绘制图形/图片。
        这里用它把主题的 settings_bg.png 拉伸到弹窗尺寸并贴在底层。
        IgnoreAspectRatio — 不保持原图宽高比，拉伸填满。
        """
        if self._bg_pixmap is not None:
            painter = QPainter(self)
            pm = self._bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, pm)  # 从弹窗左上角 (0,0) 开始绘制
            painter.end()
        super().paintEvent(event)  # 让 QDialog 继续绘制子控件

    # =========================================================================
    # 拖拽逻辑 — 鼠标按住标题栏拖动整个弹窗
    #
    # 原理：mousePressEvent 记录起始屏幕坐标 → mouseMoveEvent 计算位移 →
    #       调用 move() 移动弹窗 → mouseReleaseEvent 停止拖拽
    # =========================================================================

    def mousePressEvent(self, event) -> None:
        """鼠标按下：记录起始位置，准备拖拽。只响应左键。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """鼠标移动：计算偏移量并移动弹窗。"""
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """鼠标松开：停止拖拽。"""
        self._dragging = False
        super().mouseReleaseEvent(event)
