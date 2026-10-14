"""通用主题化消息弹窗 — 替代 QMessageBox 的原生外观。

为什么需要它：
    QMessageBox 是系统原生外观（标题栏、配色、字体都与主题脱节），
    在无边框 + 主题化的应用里很突兀。本模块提供与「详细统计」同款的
    弹窗：主题背景（背景图半透明 / 纯色偏移）、自定义标题栏与关闭按钮、
    可拖拽、Win11 圆角。

使用方式（推荐用便捷函数，自动从父窗口提取主题参数）:
    from ui.message_dialog import ask_yes_no, show_message

    show_message(self, "配置检查", detail_text)             # 单个「知道了」
    if ask_yes_no(self, "删除该记录", "确定要删除吗？"):      # 是/否，默认「否」
        ...

文本一律按纯文本渲染（配置值里可能出现 <b>、& 等字符，不能被当富文本）。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
)

from ui._base_dialog import _BaseFramelessDialog

# 图标 → 字形（不依赖图片资源，跟随主题文字颜色）
_ICON_GLYPHS = {"warning": "⚠", "info": "ℹ", "question": "❓"}


class MessageDialog(_BaseFramelessDialog):
    """主题化消息弹窗（警告 / 提示 / 确认）。

    外观与 RankStatsDialog 同套机制：标题栏 + 关闭按钮来自基类
    （_BaseFramelessDialog._make_titlebar），底色来自
    _themed_background_colors。正文按纯文本渲染、可滚动、可选中复制。

    按钮通过 (文本, 返回值) 列表配置；exec() 后用 result_value()
    取用户点击的按钮（Esc/关闭返回空字符串）。
    """

    def __init__(self, parent, title: str, text: str, *,
                 icon: str = "warning",
                 buttons: list[tuple[str, str]] | None = None,
                 default: str | None = None,
                 colors: dict | None = None,
                 bg_path: str = "",
                 widget_bg: str = "#ffffff",
                 main_bg: str = "#f0f0f0"):
        super().__init__(parent)
        self._colors = colors or {}     # 主题配色表（标题栏 hover 色等）
        self._result = ""               # 点击的按钮返回值
        if buttons is None:
            buttons = [("知道了", "ok")]

        # 背景图 + 拖拽（基类提供）
        self._init_background(bg_path)
        self._init_drag()

        # 窗口基本属性（与 RankStatsDialog / ConfigDialog 一致的无边框方案）
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("messageDialog")
        self.setMinimumWidth(400)
        self.setMaximumWidth(600)       # 限制宽度，促使长文本换行

        dialog_bg, content_bg = self._themed_background_colors(widget_bg, main_bg)
        self.setStyleSheet(f"#messageDialog {{ background: {dialog_bg}; }}")
        self._apply_dwm_round_corners()

        # ===== 主布局：标题栏 + 内容区 =====
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._make_titlebar(f"  {title}", "messageTitle"))

        # 内容区用 QFrame（纯 QWidget 对 rgba() 样式解析不稳定，见 RankStatsDialog）
        content = QFrame()
        content.setFrameShape(QFrame.Shape.NoFrame)
        content.setObjectName("messageContent")
        content.setStyleSheet(
            f"#messageContent {{ background: {content_bg}; border: none; }}"
        )
        outer.addWidget(content, 1)

        inner = QVBoxLayout(content)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(14)

        # ---- 正文行：图标 + 可滚动纯文本 ----
        body_row = QHBoxLayout()
        body_row.setSpacing(10)
        glyph = _ICON_GLYPHS.get(icon)
        if glyph:
            lbl_icon = QLabel(glyph)
            lbl_icon.setStyleSheet("font-size: 26px; background: transparent;")
            body_row.addWidget(lbl_icon, 0, Qt.AlignmentFlag.AlignTop)

        self._body_label = QLabel(text)
        self._body_label.setTextFormat(Qt.TextFormat.PlainText)  # 防富文本注入
        self._body_label.setWordWrap(True)
        self._body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)        # 可选中复制
        self._body_label.setStyleSheet("font-size: 13px; background: transparent;")

        # 正文超长时滚动（条目多/值超长的配置明细会用到）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(380)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        scroll.setWidget(self._body_label)
        body_row.addWidget(scroll, 1)
        inner.addLayout(body_row)

        # ---- 按钮行（右对齐；Enter 触发 default 指定的按钮）----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        for btn_text, key in buttons:
            btn = QPushButton(btn_text)
            btn.setMinimumWidth(84)
            btn.setAutoDefault(False)
            if key == default:
                btn.setDefault(True)
            btn.clicked.connect(lambda _=False, k=key: self._finish(k))
            btn_row.addWidget(btn)
        inner.addLayout(btn_row)

        self.adjustSize()

    def _finish(self, key: str) -> None:
        """记录用户点击的按钮并关闭弹窗。"""
        self._result = key
        self.accept()

    def result_value(self) -> str:
        """exec() 之后取用户点击的按钮返回值（Esc/关闭为空字符串）。"""
        return self._result


def _theme_params(parent) -> dict:
    """从父窗口的 ThemeManager 提取主题参数（不可得时退中性默认值）。

    与 MainWindow._open_rank_stats 传给 RankStatsDialog 的口径一致：
    bg_path 取主题的 __settings_bg__ 背景图，widget_bg / main_bg 取配色表。
    """
    tm = getattr(parent, "_tm", None)
    colors = dict(getattr(tm, "colors", None) or {})
    pixmaps = getattr(tm, "pixmap_paths", None) or {}
    return {
        "colors": colors,
        "bg_path": pixmaps.get("__settings_bg__", "") or "",
        "widget_bg": colors.get("widget_bg", "#ffffff"),
        "main_bg": colors.get("main_bg", "#f0f0f0"),
    }


def show_message(parent, title: str, text: str, *,
                 icon: str = "warning", ok_text: str = "知道了") -> None:
    """弹出一条主题化消息（模态），单个确认按钮。

    Args:
        parent: 父窗口（用于取主题与居中；通常是 MainWindow）。
        title: 标题栏文字。
        text: 正文，纯文本渲染、自动换行、超长可滚动。
        icon: "warning" / "info" / "question" / 其他（不显示图标）。
        ok_text: 确认按钮文字。
    """
    dlg = MessageDialog(parent, title, text, icon=icon,
                        buttons=[(ok_text, "ok")],
                        **_theme_params(parent))
    dlg.exec()


def ask_yes_no(parent, title: str, text: str) -> bool:
    """主题化「是/否」确认弹窗（模态），默认「否」防误操作。

    Returns:
        True = 用户点了「是」；False = 点了「否」/关闭/Esc。
    """
    dlg = MessageDialog(parent, title, text, icon="question",
                        buttons=[("是", "yes"), ("否", "no")], default="no",
                        **_theme_params(parent))
    dlg.exec()
    return dlg.result_value() == "yes"
