"""段位快速编辑弹窗 — 双击单元格后弹出的按钮矩阵面板。

================================================================================
这个面板做了什么？

    替代原来双击段位单元格时弹出的普通文本框。
    用户可以通过按钮矩阵快速选择段位（两次点击完成），也可以自由输入自定义文字。

================================================================================
面板布局

    ┌──────────────────────────────────────────────────┐
    │  [新手] [青铜] [白银] [黄金] [铂金] [钻石] [大师] [巅峰] │  ← 第 1 行：大段按钮
    │           [Ⅰ]  [Ⅱ]  [Ⅲ]  [Ⅳ]  [Ⅴ]                │  ← 第 2 行：小段按钮
    │  自定义: [________________________] [确认]          │  ← 第 3 行：自定义输入
    │                       当前: 黄金 Ⅲ                  │  ← 第 4 行：实时预览
    └──────────────────────────────────────────────────┘

================================================================================
操作方式

    ┌──────────────────────┬──────────────────────────────────────┐
    │ 操作                 │ 结果                                 │
    ├──────────────────────┼──────────────────────────────────────┤
    │ 点大段 → 点小段      │ 自动提交 "黄金 Ⅲ"，面板关闭         │
    │ 点"巅峰"             │ 直接提交 "巅峰"（无等级），面板关闭  │
    │ 输入自定义文字 → 确认│ 提交自定义内容，面板关闭             │
    │ 点面板外面           │ 取消编辑，单元格恢复原值             │
    │ 按 Esc               │ 取消编辑，单元格恢复原值             │
    │ 切换到其他程序       │ 取消编辑，面板关闭                   │
    └──────────────────────┴──────────────────────────────────────┘

================================================================================
和 Qt Delegate 系统的关系

    QStyledItemDelegate 是 Qt 的"单元格自定义"机制：
    - 正常状态：delegate 的 paint() 负责画单元格（图标 + 文字）
    - 编辑状态：用户双击 → Qt 调用 createEditor() → 返回这个面板
               → 用户操作完毕 → setModelData() 把新值写回表格

    这个面板就是 createEditor() 返回的"编辑控件"。
    它本质上是一个独立的 Tool 窗口（不是真正嵌入在单元格里），
    因为面板内容比单元格大很多，嵌入的话会被裁剪。

================================================================================
窗口类型的选择：为什么用 Tool 而不是 Popup？

    最初用的是 Popup 窗口（Qt 标准做法），但发现 Windows 上 Popup 窗口
    不接收输入法（IME）事件，导致自定义文本框无法输入中文。
    换成 Tool 窗口后输入法正常工作，但失去了"点击外部自动关闭"的特性，
    所以手动实现了 eventFilter 来监听外部点击和应用失焦。

================================================================================
主题兼容

    面板通过构造函数的 colors 参数接收主题颜色字典（如 widget_bg、text_primary 等）。
    然后用 f-string 把这些颜色值拼成内联 QSS，不需要依赖外部 .qss 文件。
    切换皮肤时，main_window.py 的 _on_reload_config 会更新 delegate 的 _colors，
    下次打开面板时就会用新颜色。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from src.rank_icons import KNOWN_TIERS

# =============================================================================
# 常量
# =============================================================================

# 5 个小段位的显示文字（Unicode 罗马数字，看起来更美观）。
# 注意：CSV 数据和检测器输出的是 ASCII 字母（I, II, III, IV, V），
# 和这里不同。读取已有数据时需要两套都兼容，见下文 _UNICODE_TO_ASCII。
_MINOR_TIERS = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ"]

# 小段位的 Unicode → ASCII 对照表。
# 用途：当回读已有单元格数据时，CSV 里可能是 ASCII 的 "IV"，
# 但面板按钮上显示的是 Unicode 的 "Ⅳ"，两套都需要能匹配。
_UNICODE_TO_ASCII = {
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
}

# =============================================================================
# 默认主题颜色 — 当 main_window 没有传入 colors 时作为兜底
#
# 这些颜色值来自暗色主题（dark），确保即使在异常情况下面板也不会
# 变成白底白字（Qt 默认样式）。
# =============================================================================
_DEFAULT_COLORS: dict[str, str] = {
    # 背景层次
    "widget_bg": "#16213e",       # 面板主体背景（卡片色）
    "main_bg": "#1a1a2e",         # 更深一层背景（按钮默认色、输入框背景）
    # 文字颜色
    "text_primary": "#b8b8c8",     # 正文颜色（按钮文字、输入框文字）
    "text_secondary": "#8b8b9e",   # 辅助文字（"自定义:" 标签、预览标签）
    "text_disabled": "#555568",    # 禁用状态文字（小段按钮禁用时）
    # 边框
    "border": "#2a2a4a",           # 默认边框色
    "border_hover": "#3a3a5a",     # 鼠标悬停时边框变亮
    "border_focus": "#e2a03f",     # 选中/聚焦时的强调边框（金色）
    # 交互
    "selection_bg": "#1f3060",     # 选中状态背景色（比默认稍亮）
}


# =============================================================================
# RankEditPanel — 段位编辑弹出面板
# =============================================================================

class RankEditPanel(QFrame):
    """段位快速编辑弹出面板。

    继承 QFrame 而不是 QDialog，因为 QFrame 更轻量，
    没有默认的标题栏和按钮框，适合作为小型弹出面板。

    Signals:
        rank_selected(str): 用户确认了选择，携带段位字符串（如 "黄金 Ⅲ"）。
        cancelled():        用户取消了编辑（关闭面板但不提交数据）。
    """

    # ---- 信号定义 ----
    # Qt 信号是对象间通信的机制。这里定义了两个信号，
    # 外部（RankIconDelegate）连接它们来响应面板的操作。
    rank_selected = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        parent=None,
        colors: dict[str, str] | None = None,
    ) -> None:
        """创建段位编辑面板。

        Args:
            parent: 父控件。这里通常传 None，因为面板是独立 Tool 窗口。
            colors: 主题颜色字典。如果为 None，使用内置暗色主题兜底。
                    字典应包含 widget_bg、text_primary、border 等键。
        """
        super().__init__(parent)

        # ---- 合并主题颜色 ----
        # 用外部传入的颜色覆盖默认值。setdefault 确保即使传入的字典
        # 不完整（缺少某些键），也能用默认值补上，不会 KeyError。
        self._colors = colors or _DEFAULT_COLORS.copy()
        for k, v in _DEFAULT_COLORS.items():
            self._colors.setdefault(k, v)

        # ---- 内部状态 ----
        self._selected_major: str = ""   # 用户当前选中的大段（如 "黄金"）
        self._selected_minor: str = ""   # 用户当前选中的小段（如 "Ⅲ"）
        self._committed = False          # 是否已经提交（防止重复触发）
        self.committed_value: str = ""   # 提交时的最终值（供 delegate 读取）

        # 构建 UI（按钮、输入框、布局）
        self._setup_ui()
        # 设置窗口属性（Tool 窗口、无边框、焦点策略）
        self._setup_window_flags()

    # =========================================================================
    # 窗口属性设置
    # =========================================================================

    def _setup_window_flags(self) -> None:
        """配置窗口类型和属性。

        窗口类型选择 Tool 而非 Popup：
        - Popup 优点：点击外部自动关闭，不用自己写逻辑
        - Popup 缺点：Windows 上不接收输入法事件 → 无法输入中文 ✗
        - Tool 优点：支持输入法，可以输入中文 ✓
        - Tool 缺点：不会自动关闭 → 需要手动实现 eventFilter

        其他属性：
        - FramelessWindowHint：无边框（自己画圆角）
        - WA_ShowWithoutActivating：显示时不抢焦点（不干扰用户当前操作）
        - StrongFocus：可以接收键盘事件（Esc 关闭）
        """
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # =========================================================================
    # UI 构建 — 所有控件和布局在这里创建
    # =========================================================================

    def _setup_ui(self) -> None:
        """构建面板的完整 UI 布局。

        布局结构（从外到内）：
        RankEditPanel (QFrame)
        └── QVBoxLayout (垂直排列)
            ├── QHBoxLayout — 8 个大段按钮
            ├── QHBoxLayout — 5 个小段按钮
            ├── QHBoxLayout — "自定义:" 标签 + 输入框 + 确认按钮
            └── QLabel         — 实时预览当前选择
        """
        c = self._colors  # 颜色字典的短别名，让后面代码更简洁

        # ===== 面板整体样式 =====
        # setObjectName 给控件起个名字，QSS 可以用 #rankEditPanel 选择它
        self.setObjectName("rankEditPanel")
        # 直接用 Python f-string 把颜色值嵌入 QSS，不依赖外部 .qss 文件
        self.setStyleSheet(
            f"#rankEditPanel {{"
            f"  background: {c['widget_bg']};"      # 面板底色
            f"  border: 1px solid {c['border']};"   # 面板边框
            f"  border-radius: 6px;"                 # 圆角
            f"}}"
        )

        # 主布局：所有子控件垂直排列
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 6, 8, 6)   # 左右 8px，上下 6px
        main_layout.setSpacing(6)                     # 行间距 6px

        # ===== 第 1 行：大段按钮（新手 青铜 白银 黄金 铂金 钻石 大师 巅峰） =====
        self._major_btns: dict[str, QPushButton] = {}
        major_row = QHBoxLayout()
        major_row.setSpacing(3)  # 按钮之间的间距
        for rank_name in KNOWN_TIERS:
            # 创建按钮，is_major=True 表示这是大段按钮（比小段按钮稍大）
            btn = self._make_btn(rank_name, is_major=True)
            # 连接点击信号。lambda 中 r=rank_name 是 Python 闭包的标准写法，
            # 如果直接写 rank_name，循环结束后所有 lambda 都会引用最后一个值
            btn.clicked.connect(lambda checked, r=rank_name: self._on_major_click(r))
            self._major_btns[rank_name] = btn
            major_row.addWidget(btn)
        main_layout.addLayout(major_row)

        # ===== 第 2 行：小段按钮（Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ） =====
        self._minor_btns: dict[str, QPushButton] = {}
        minor_row = QHBoxLayout()
        minor_row.setSpacing(3)
        # 左侧留点空白，让这行按钮大致居中于大段按钮下方
        minor_row.addSpacing(22)
        for tier_name in _MINOR_TIERS:
            btn = self._make_btn(tier_name, is_major=False)
            btn.clicked.connect(lambda checked, t=tier_name: self._on_minor_click(t))
            self._minor_btns[tier_name] = btn
            minor_row.addWidget(btn)
        # 右侧用弹簧占满剩余空间，让按钮靠左
        minor_row.addStretch()
        main_layout.addLayout(minor_row)

        # ===== 第 3 行：自定义文本输入 =====
        custom_row = QHBoxLayout()
        custom_row.setSpacing(4)

        # "自定义:" 标签 — 灰色小字，提示用户可以在这里自由输入
        custom_label = QLabel("自定义:")
        custom_label.setStyleSheet(
            f"color: {c['text_secondary']};"
            f"font-size: 12px;"
            f"background: transparent;"   # 透明背景，继承面板底色
        )
        custom_row.addWidget(custom_label)

        # 文本框 — 显示当前单元格的值，也可以自由输入任何文字
        self._custom_edit = QLineEdit()
        self._custom_edit.setPlaceholderText("输入自定义段位…")
        # 按 Enter 等同于点确认按钮
        self._custom_edit.returnPressed.connect(self._on_custom_confirm)
        self._custom_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {c['main_bg']};"           # 输入框底色（比面板稍深）
            f"  color: {c['text_primary']};"            # 输入文字颜色
            f"  border: 1px solid {c['border']};"       # 边框
            f"  border-radius: 4px;"                    # 圆角
            f"  padding: 3px 6px;"                      # 内边距
            f"  font-size: 12px;"
            f"}}"
            f"QLineEdit:focus {{"                       # 获得焦点时
            f"  border-color: {c['border_focus']};"     # 边框变亮（提示用户正在输入）
            f"}}"
        )
        custom_row.addWidget(self._custom_edit, 1)  # stretch=1：输入框占满剩余空间

        # "确认" 按钮 — 点击后把输入框里的内容作为自定义段位提交
        self._btn_confirm = QPushButton("确认")
        self._btn_confirm.clicked.connect(self._on_custom_confirm)
        self._btn_confirm.setStyleSheet(
            f"QPushButton {{"
            f"  background: {c['border']};"
            f"  color: {c['text_primary']};"
            f"  border: none;"
            f"  border-radius: 4px;"
            f"  padding: 3px 10px;"
            f"  font-size: 12px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {c['border_hover']};"      # 鼠标悬停稍微变亮
            f"}}"
        )
        custom_row.addWidget(self._btn_confirm)
        main_layout.addLayout(custom_row)

        # ===== 第 4 行：实时预览 =====
        # 显示当前选中的段位，让用户确认后再做操作
        self._preview_label = QLabel("")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # 居中
        self._preview_label.setStyleSheet(
            f"color: {c['text_secondary']};"    # 次要文字颜色
            f"font-size: 11px;"
            f"background: transparent;"
            f"padding-top: 2px;"
        )
        main_layout.addWidget(self._preview_label)

        # ===== 初始状态 =====
        # 刚打开面板时还没选大段，小段按钮应该是灰色的（禁用状态）
        self._set_minor_enabled(False)
        self._update_preview()

        # 固定面板大小（不让用户拖拽改变尺寸）
        self.setFixedSize(self.sizeHint())

    def _make_btn(self, text: str, is_major: bool) -> QPushButton:
        """创建一个统一样式的按钮。

        Qt 的 QSS（Qt Style Sheets）语法和 CSS 类似，
        这里用 f-string 把主题颜色嵌入 QSS 模板。

        Args:
            text: 按钮上显示的文字（如 "黄金"、"Ⅲ"）。
            is_major: True = 大段按钮（宽一些），False = 小段按钮（窄一些）。

        Returns:
            配置好样式和尺寸的 QPushButton。
        """
        c = self._colors
        btn = QPushButton(text)

        # 大段按钮和小段按钮尺寸不同
        if is_major:
            btn.setFixedHeight(30)       # 固定高度 30px
            btn.setMinimumWidth(44)      # 最小宽度 44px（"新手""青铜"刚好）
            font_size = 12
        else:
            btn.setFixedHeight(28)
            btn.setFixedWidth(32)        # 正方形按钮
            font_size = 13               # 罗马数字稍大一点更好看

        # 设置按钮的三态样式：普通、鼠标悬停（hover）、按下（pressed）
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {c['main_bg']};"            # 默认背景
            f"  color: {c['text_primary']};"             # 文字颜色
            f"  border: 1px solid {c['border']};"        # 边框
            f"  border-radius: 4px;"                     # 圆角
            f"  font-size: {font_size}px;"
            f"  font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{"                      # 鼠标悬停
            f"  border-color: {c['border_hover']};"
            f"  background: {c['border_hover']};"
            f"}}"
            f"QPushButton:pressed {{"                    # 鼠标按下
            f"  background: {c['border_hover']};"
            f"}}"
        )
        return btn

    # =========================================================================
    # 按钮点击处理 — 核心交互逻辑
    # =========================================================================

    def _on_major_click(self, rank_name: str) -> None:
        """用户点击了大段按钮（如 "黄金"）。

        行为分两种情况：
        1. 点击 "巅峰" → 巅峰没有 I~V 等级，直接提交 "巅峰" 并关闭面板
        2. 点击其他大段 → 高亮该按钮，启用下方小段按钮行，等用户继续选择

        Args:
            rank_name: 被点击的大段名（"新手" ~ "巅峰"）。
        """
        self._selected_major = rank_name
        self._selected_minor = ""   # 换了新大段，之前选的小段作废

        # 更新大段按钮行的高亮状态：被选中的按钮变色，其他恢复默认
        for name, btn in self._major_btns.items():
            self._set_btn_selected(btn, name == rank_name)

        if rank_name == "巅峰":
            # 巅峰没有等级划分，直接提交
            # 注意要 return，否则会继续执行下面的 _set_minor_enabled(True)
            self._selected_minor = ""
            self._set_minor_enabled(False)
            self._commit(rank_name)
            return

        # 非巅峰：清除小段按钮的选中状态，启用它们等待用户点击
        for btn in self._minor_btns.values():
            self._set_btn_selected(btn, False)
        self._set_minor_enabled(True)
        self._update_preview()

    def _on_minor_click(self, tier_name: str) -> None:
        """用户点击了小段按钮（如 "Ⅲ"）。

        此时大段已经选好了，小段也选了 → 自动拼接 "黄金 Ⅲ" 并提交关闭。
        用户不需要再点"确认"，两步点击就完成。

        Args:
            tier_name: 被点击的小段名（"Ⅰ" ~ "Ⅴ"）。
        """
        # 防御性检查：如果没有选大段（理论上不会发生），忽略
        if not self._selected_major or self._selected_major == "巅峰":
            return

        self._selected_minor = tier_name

        # 高亮被选中的小段按钮
        for name, btn in self._minor_btns.items():
            self._set_btn_selected(btn, name == tier_name)

        # 拼接完整段位字符串并提交
        # 格式："大段 小段"，中间用空格分隔，如 "黄金 Ⅲ"
        result = f"{self._selected_major} {tier_name}"
        self._commit(result)

    def _on_custom_confirm(self) -> None:
        """用户点击"确认"按钮或按 Enter 键。

        提交输入框中的文字。允许空字符串——用户清空输入框点确认
        意味着"把段位清掉"，和选择大段+小段的行为一致。
        """
        text = self._custom_edit.text().strip()
        self._commit(text)

    def _commit(self, value: str) -> None:
        """提交段位值并关闭面板。

        这个方法是所有提交路径的终点：
        - 选大段 + 小段 → _on_minor_click → _commit("黄金 Ⅲ")
        - 选巅峰        → _on_major_click  → _commit("巅峰")
        - 自定义文本     → _on_custom_confirm → _commit("自定义文字")

        _committed 标志防止重复提交（极端情况下信号可能触发两次）。

        Args:
            value: 要写入单元格的段位字符串。
        """
        if self._committed:
            return
        self._committed = True

        # committed_value 供 delegate 的 setModelData() 读取
        self.committed_value = value
        # 发射信号通知 delegate "用户确认了选择"
        self.rank_selected.emit(value)
        # 关闭面板（Tool 窗口不会自动关闭，需要显式调用）
        self.close()

    # =========================================================================
    # UI 辅助方法 — 按钮样式切换、预览更新
    # =========================================================================

    def _set_btn_selected(self, btn: QPushButton, selected: bool) -> None:
        """切换按钮的选中 / 非选中样式。

        选中态：深色背景 + 金色边框（和主题的 border_focus 一致）。
        非选中态：恢复为默认的深色背景 + 暗色边框。

        注意：这里直接用 setStyleSheet 覆盖之前的样式，
        所以选中态的样式里没有写 hover/pressed 伪状态（选中时不需要 hover 效果）。

        Args:
            btn: 要改变样式的按钮。
            selected: True = 选中高亮，False = 恢复默认。
        """
        c = self._colors
        if selected:
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {c['selection_bg']};"       # 选中背景（比默认亮）
                f"  color: {c['text_primary']};"
                f"  border: 1px solid {c['border_focus']};" # 金色边框强调
                f"  border-radius: 4px;"
                # fontInfo().pixelSize() 读取按钮当前的字号，保持和原来一样
                f"  font-size: {btn.fontInfo().pixelSize()}px;"
                f"  font-weight: bold;"
                f"}}"
            )
        else:
            # 恢复默认样式（和 _make_btn 里的初始样式一样）
            is_major = btn.text() in KNOWN_TIERS
            font_size = 12 if is_major else 13
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {c['main_bg']};"
                f"  color: {c['text_primary']};"
                f"  border: 1px solid {c['border']};"
                f"  border-radius: 4px;"
                f"  font-size: {font_size}px;"
                f"  font-weight: bold;"
                f"}}"
                f"QPushButton:hover {{"
                f"  border-color: {c['border_hover']};"
                f"  background: {c['border_hover']};"
                f"}}"
            )

    def _set_minor_enabled(self, enabled: bool) -> None:
        """启用 / 禁用所有小段按钮。

        禁用时（enabled=False）按钮变成灰色半透明，提示用户"现在不能用"。
        这发生在两种情况下：
        1. 刚打开面板，还没选大段 → 小段灰色
        2. 选了"巅峰" → 巅峰无等级，小段灰色

        Qt 的 setEnabled(False) 会让按钮不响应点击，
        同时 QSS 可以用 QPushButton:disabled 伪状态来改变外观。
        """
        for btn in self._minor_btns.values():
            btn.setEnabled(enabled)
            if not enabled:
                # 禁用状态的按钮样式：透明背景 + 灰色文字
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: transparent;"
                    f"  color: {self._colors['text_disabled']};"
                    f"  border: 1px solid transparent;"
                    f"  border-radius: 4px;"
                    f"  font-size: 13px;"
                    f"  font-weight: bold;"
                    f"}}"
                )

    def _update_preview(self) -> None:
        """更新底部预览标签，显示当前已选择的内容。

        四种状态：
        - 没选任何东西         → ""
        - 只选了大段             → "当前: 黄金"
        - 选了大段 + 小段        → "当前: 黄金 Ⅲ"
        - 选了巅峰               → "当前: 巅峰"
        """
        if self._selected_major == "巅峰":
            self._preview_label.setText("当前: 巅峰")
        elif self._selected_major and self._selected_minor:
            self._preview_label.setText(
                f"当前: {self._selected_major} {self._selected_minor}"
            )
        elif self._selected_major:
            self._preview_label.setText(f"当前: {self._selected_major}")
        else:
            self._preview_label.setText("")

    # =========================================================================
    # 键盘事件
    # =========================================================================

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """处理键盘按键。

        目前只处理 Esc：取消编辑，恢复单元格原值。
        其他按键交给父类默认处理（比如输入框里的文字输入）。
        """
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()  # 通知 delegate "用户取消"
            self.close()
            return
        super().keyPressEvent(event)

    # =========================================================================
    # 点击外部 / 切换程序 → 自动关闭
    #
    # Tool 窗口不会像 Popup 那样自动在点击外部时关闭，所以需要手动实现。
    # 方法：向 QApplication 安装事件过滤器（eventFilter），
    #       监听全局的鼠标点击和应用失焦事件。
    # =========================================================================

    def showEvent(self, event) -> None:
        """面板显示时调用。

        在这里向 QApplication 安装事件过滤器。
        QApplication 是 Qt 程序的"总管"，所有事件都会经过它。
        安装过滤器后，eventFilter() 可以拦截全局事件。
        """
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event) -> None:
        """面板隐藏时调用。

        移除之前安装的事件过滤器，避免过滤器在面板关闭后继续运行。
        如果不移除，每次关闭面板都会残留一个无效的过滤器，造成内存泄漏。
        """
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:
        """全局事件过滤器 — 拦截并判断是否需要关闭面板。

        这个方法会收到程序中发生的所有事件（因为过滤器安装在 QApplication 上）。
        我们只关心两种事件：

        1. ApplicationDeactivate — 用户 Alt+Tab 切到其他程序了
           → 关闭面板，不提交数据

        2. MouseButtonPress — 用户在面板外部点击了鼠标
           → 关闭面板，不提交数据

        判断"外部"的方法：获取鼠标点击位置对应的控件，
        检查它是不是面板本身、或者是面板的子控件（如按钮、输入框）。
        如果不是，就是"外部"。

        Returns:
            False = 不消费事件，让事件继续传递给原本的目标控件。
            如果返回 True，事件会被吞掉，可能导致表格收不到点击。
        """
        # ----- 情况 1：切换到其他程序 -----
        if event.type() == QEvent.Type.ApplicationDeactivate:
            self.cancelled.emit()
            self.close()
            return False

        # ----- 情况 2：面板外的鼠标点击 -----
        if event.type() == QEvent.Type.MouseButtonPress:
            # QApplication.widgetAt(globalPos) 返回鼠标所在位置的控件
            clicked_widget = QApplication.widgetAt(event.globalPos())

            if clicked_widget is not None:
                # 判断点击位置是否在面板内部：
                # - clicked_widget is self：点的是面板本身
                # - self.isAncestorOf(clicked_widget)：点的是面板的子控件
                inside = (
                    clicked_widget is self
                    or self.isAncestorOf(clicked_widget)
                )
            else:
                # 点击位置没有任何 Qt 控件（比如点了桌面空白区域）
                inside = False

            if not inside:
                # 点击在面板外部 → 取消编辑
                self.cancelled.emit()
                self.close()
                return False

        # 不是我们关心的事件类型 → 交给默认处理
        return super().eventFilter(obj, event)

    # =========================================================================
    # 初始化当前值 — 由 delegate 在 setEditorData 中调用
    # =========================================================================

    def set_current_value(self, rank_text: str) -> None:
        """根据单元格当前的段位值，初始化面板状态。

        这个方法在面板刚弹出时被调用，把已有的段位值填入面板：
        - 输入框显示当前值
        - 大段按钮高亮对应的大段
        - 小段按钮高亮对应的小段（如果有的话）
        - 预览标签显示当前值

        支持三种输入格式：
        - "钻石 IV"  — CSV / 检测器输出的 ASCII 格式（最常见的来源）
        - "钻石 Ⅳ"  — 本面板编辑后写入的 Unicode 格式
        - "巅峰"    — 无等级后缀的段位
        - ""        — 空值（新记录的段位列可能为空）

        Args:
            rank_text: 单元格中当前的段位文本。
        """
        rank_text = rank_text.strip()

        # 无论能不能匹配到已知段位，都先把原始文本填入输入框
        self._custom_edit.setText(rank_text)

        # ---- 空值 → 清空所有选中状态 ----
        if not rank_text:
            self._selected_major = ""
            self._selected_minor = ""
            self._set_minor_enabled(False)
            self._update_preview()
            return

        # ---- 尝试匹配已知大段 ----
        # 遍历 8 个大段名，看文本以哪个开头
        for tier_name in KNOWN_TIERS:
            if rank_text.startswith(tier_name):
                self._selected_major = tier_name

                # 高亮匹配到的大段按钮
                for name, btn in self._major_btns.items():
                    self._set_btn_selected(btn, name == tier_name)

                if tier_name == "巅峰":
                    # 巅峰没有等级，禁用小段按钮
                    self._selected_minor = ""
                    self._set_minor_enabled(False)
                else:
                    # 尝试从剩余文本中提取小段
                    # 例如 "钻石 IV" → rest = "IV"
                    rest = rank_text[len(tier_name):].strip()
                    for minor in _MINOR_TIERS:
                        # 同时匹配 Unicode（"Ⅳ"）和 ASCII（"IV"）两种格式
                        if rest == minor or rest == _UNICODE_TO_ASCII.get(minor, ""):
                            self._selected_minor = minor
                            # 高亮匹配到的小段按钮
                            for mn, btn in self._minor_btns.items():
                                self._set_btn_selected(btn, mn == minor)
                            break
                    self._set_minor_enabled(True)

                self._update_preview()
                return

        # ---- 未匹配任何已知段位（自定义文字） ----
        # 不选中任何按钮，让用户自由操作
        self._selected_major = ""
        self._selected_minor = ""
        for btn in self._major_btns.values():
            self._set_btn_selected(btn, False)
        for btn in self._minor_btns.values():
            self._set_btn_selected(btn, False)
        self._set_minor_enabled(False)
        self._update_preview()
