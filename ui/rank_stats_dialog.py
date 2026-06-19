"""详细统计信息弹窗 — 按卡组 + 段位筛选，展示 17 项统计指标。

================================================================================
架构

    RankStatsDialog(QDialog)           ← 无边框弹窗，可拖拽
      ├── 自定义标题栏                  ← 可拖拽 + 关闭按钮
      └── 内容区 (QFrame)              ← 半透明/纯色双模式背景
            ├── 筛选栏                 ← 卡组下拉 + 己方段位下拉
            ├── 统计指标网格 (2×9)     ← 17 项统计指标
            ├── 底部按钮               ← [复制统计] [关闭]
            └── 联动刷新               ← 下拉框变化自动刷新数据

样式参考 ConfigDialog：自定义标题栏 + 半透明背景 + 无边框窗口。

背景双模式:
    - 带背景图的主题（如 macaron）：paintEvent 贴背景图，内容区 QFrame 用
      rgba() 半透明背景透出底图。
    - 纯色主题（如 light / dark）：内容区用 widget_bg 实色背景，对话框用
      main_bg 偏移色形成深度对比。

段位下拉框动态化:
    不再写死 RANK_TIERS 列表，而是从 CSV 数据中提取实际出现过的段位大段。
    未知段位（如未来新出的"黑铁"）统一归到 "无段位/其他" 分类。
"""

import ctypes

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from src.config import get_project_root
from src.recorder import (
    compute_filtered_stats, get_available_rank_tiers, load_records,
)


class RankStatsDialog(QDialog):
    """详细统计信息弹窗。

    主窗口点击"详细统计"按钮时打开。用户筛选卡组和己方段位，
    查看该条件下的 17 项统计指标（对局数、胜率、硬币概率等）。
    支持拖拽移动、背景图主题半透明效果、一键复制统计数据。
    """

    def __init__(self, parent, config: dict, theme_colors: dict,
                 bg_path: str = "", widget_bg: str = "#ffffff",
                 main_bg: str = "#f0f0f0"):
        super().__init__(parent)
        self._config = config          # 主窗口的配置字典（备用）
        self._colors = theme_colors    # 当前主题配色表（取 btn_close_hover 等）
        self._widget_bg = widget_bg    # 内容区背景色（如 "#ffffff"）
        self._main_bg = main_bg        # 主窗口背景色（如 "#f0f0f0"）

        # ===== 背景图 =====
        # bg_path 来自主窗口的 _tm.pixmap_paths["__settings_bg__"]
        # 如果主题提供了背景图片，_bg_pixmap 就是该图片的 QPixmap
        # 否则为 None（纯色主题，不走 paintEvent 贴图逻辑）
        self._bg_pixmap: QPixmap | None = None
        if bg_path:
            pm = QPixmap(bg_path)
            if not pm.isNull():
                self._bg_pixmap = pm

        # ===== 拖拽状态 =====
        # 弹窗无系统标题栏，用户按住任意位置拖拽移动窗口
        self._dragging = False          # 是否正在拖拽
        self._drag_start = QPoint()     # 拖拽起始坐标

        # ===== 窗口基本属性 =====
        self.setWindowTitle("详细统计")
        # 无边框 + 独立窗口 + 模态对话框风格（但 exec 由调用方决定）
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint   # 去掉系统标题栏
            | Qt.WindowType.Window              # 作为独立窗口显示
            | Qt.WindowType.Dialog              # 对话框行为（置顶于父窗口）
        )
        # WA_StyledBackground：告诉 Qt 用样式表绘制背景（而非系统默认）
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(410, 390)   # 用户不能缩小到比这更小
        self.resize(450, 430)           # 打开时的默认尺寸
        self.setObjectName("rankStatsDialog")  # QSS 选择器用的 ID

        # ===== 对话框背景色（双模式） =====
        # 把十六进制颜色 "#ffffff" 拆成 R、G、B 三个整数
        r, g, b = int(widget_bg[1:3], 16), int(widget_bg[3:5], 16), int(widget_bg[5:7], 16)
        # 半透明色：用于内容区，alpha≈70%（180/255），透出底下的背景图
        bg_semi = f"rgba({r},{g},{b},180)"
        # 对话框底色：有背景图就用 widget_bg，纯色主题用 main_bg 偏移色
        dialog_bg = widget_bg
        if self._bg_pixmap is None:
            # 纯色主题 — 双向偏移 5 档，让对话框与主窗口产生深度辨识度
            #   · 浅色主题（mr > 128）→ 变暗（-5）
            #   · 深色主题（mr ≤ 128）→ 变亮（+5）
            mr, mg, mb = int(main_bg[1:3], 16), int(main_bg[3:5], 16), int(main_bg[5:7], 16)
            shift = 5
            dr = mr + shift if mr <= 128 else mr - shift
            dg = mg + shift if mg <= 128 else mg - shift
            db = mb + shift if mb <= 128 else mb - shift
            dialog_bg = f"#{dr:02x}{dg:02x}{db:02x}"
        self.setStyleSheet(f"#rankStatsDialog {{ background: {dialog_bg}; }}")
        self._apply_dwm_round_corners()

        # ===== 主布局：标题栏 + 内容区 =====
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)  # 无边距，内容撑满整个弹窗
        outer.setSpacing(0)                    # 标题栏和内容区之间无间隙
        outer.addWidget(self._make_titlebar()) # 顶部：自定义标题栏

        # 内容区：用 QFrame 而非 QWidget。
        # 为什么是 QFrame？纯 QWidget 对样式表 rgba() 解析不稳定（会报
        # "Could not parse stylesheet"），QFrame 的渲染管线和 QTabWidget::pane
        # 一致，能正确处理带 alpha 的颜色。
        content = QFrame()
        content.setFrameShape(QFrame.Shape.NoFrame)  # 不画边框，只做容器
        content.setObjectName("rankStatsContent")     # QSS 选择器用的 ID
        if self._bg_pixmap is not None:
            # 背景图主题：半透明背景，透出底层背景图
            content.setStyleSheet(
                f"#rankStatsContent {{ background: {bg_semi}; border: none; }}"
            )
        else:
            # 纯色主题：实色背景
            content.setStyleSheet(
                f"#rankStatsContent {{ background: {widget_bg}; border: none; }}"
            )
        outer.addWidget(content)

        # 内容区内部布局
        inner = QVBoxLayout(content)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(10)

        # ===== 筛选栏 =====
        # 水平排列：卡组下拉 + 己方段位下拉
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("卡组:"))
        self._deck_combo = QComboBox()     # 卡组选择（全部 / 具体卡组名）
        self._deck_combo.setMinimumWidth(120)
        filter_row.addWidget(self._deck_combo)
        filter_row.addWidget(QLabel("己方段位:"))
        self._rank_combo = QComboBox()     # 己方段位选择（全部 / 黄金 / … / 无段位/其他）
        self._rank_combo.setMinimumWidth(80)
        filter_row.addWidget(self._rank_combo)
        filter_row.addStretch()             # 把筛选控件推到左侧
        inner.addLayout(filter_row)

        # ===== 17 项统计指标 (2 列 × 9 行网格) =====
        # 用 QGridLayout 把 17 个指标排列为 9 行 2 列
        # 每个格子 = 标签名（灰色小字） + 数值（粗体大字）
        self._stat_labels: dict[str, QLabel] = {}  # 指标名 → 数值 QLabel
        grid = QGridLayout()
        grid.setSpacing(4)  # 格子之间的间距
        # 每行两个指标，(行1 列0, 列1), (行2 列0, 列1), ...
        items = [
            ("对局数", "胜"), ("负", "胜率"),
            ("赢硬币次数", "输硬币次数"), ("赢硬币概率", "赢硬币胜率"),
            ("输硬币胜率", "先攻次数"), ("后攻次数", "先攻胜"),
            ("后攻胜", "先攻胜率"), ("后攻胜率", "升段次数"),
            ("降段次数", "升段胜率"), ("降段胜率", ""),
        ]
        for row, (k1, k2) in enumerate(items):
            for col, key in enumerate([k1, k2]):
                if not key:       # 最后一行第 2 列是空字符串，跳过
                    continue
                # 指标名标签（如 "对局数:"）— 灰色小字
                lbl_key = QLabel(f"{key}:")
                lbl_key.setStyleSheet("color: #888; font-size: 16px; background: transparent;")
                # 数值标签（如 "42"）— 粗体大字，初始显示 "—"
                lbl_val = QLabel("—")
                lbl_val.setStyleSheet("font-weight: bold; font-size: 16px; background: transparent;")
                self._stat_labels[key] = lbl_val  # 存起来，_refresh 时更新
                # 水平排列：标签 + 数值
                pair = QHBoxLayout()
                pair.setSpacing(4)
                pair.addWidget(lbl_key)
                pair.addWidget(lbl_val)
                pair.addStretch()
                grid.addLayout(pair, row, col)
        inner.addLayout(grid)
        inner.addStretch()  # 把统计网格往上推，底部按钮沉底

        # ===== 底部按钮栏 =====
        btn_row = QHBoxLayout()
        btn_row.addStretch()  # 把按钮推到右侧
        self._btn_copy = QPushButton("复制统计")
        self._btn_copy.clicked.connect(self._copy_stats)  # 点击 → 复制到剪贴板
        btn_row.addWidget(self._btn_copy)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.reject)  # reject() 关闭弹窗
        btn_row.addWidget(btn_close)
        inner.addLayout(btn_row)

        # ===== 联动 =====
        # 卡组或段位下拉框切换时，自动刷新统计数据
        self._deck_combo.currentTextChanged.connect(self._refresh)
        self._rank_combo.currentTextChanged.connect(self._refresh)

        # 首屏加载：填充下拉框 + 显示统计数据
        self._populate_decks()
        self._refresh()

    # =========================================================================
    # 标题栏
    # =========================================================================

    def _make_titlebar(self) -> QWidget:
        """创建顶部自定义标题栏：标题文字 + 关闭按钮，支持拖拽移动窗口。

        与 ConfigDialog._make_titlebar 结构一致：
            - 背景透明，让下方内容区的背景透出
            - 关闭按钮复用 TitleBar 的 _TitleBarButton（自带 hover 图标切换）
            - 关闭按钮 hover 色从主题配色表读取
        """
        bar = QWidget()
        bar.setObjectName("rankStatsTitle")         # QSS 选择器 ID
        bar.setFixedHeight(36)                      # 固定 36px 高度
        bar.setStyleSheet("#rankStatsTitle { background: transparent; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 4, 0)      # 左 10px 右 4px

        title = QLabel("  详细统计信息")
        title.setStyleSheet("font-size: 13px; font-weight: bold; "
                            "background: transparent; border: none;")
        layout.addWidget(title)
        layout.addStretch()  # 把标题顶到左边，关闭按钮推到右边

        # 关闭按钮：复用主窗口标题栏的按钮组件
        from ui.titlebar import _TitleBarButton
        assets = get_project_root() / "resource"
        btn_close = _TitleBarButton("title_close", assets, bar)
        close_hover = self._colors.get("btn_close_hover", "#e74c3c")
        # 默认透明，hover 变红
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {close_hover}; "
            f"border-color: {close_hover}; }}"
        )
        btn_close.clicked.connect(self.reject)  # reject() = 关闭弹窗
        layout.addWidget(btn_close)
        return bar

    # =========================================================================
    # 拖拽 — 无边框窗口用鼠标按住任意位置拖动
    # =========================================================================

    def mousePressEvent(self, event):
        """鼠标按下：记录起始位置，进入拖拽模式。

        只响应左键。event.globalPosition() 返回鼠标在屏幕上的全局坐标，
        frameGeometry().topLeft() 是窗口左上角的屏幕坐标，
        两者相减得到鼠标在窗口内的相对位置（拖拽时保持这个相对位置不变）。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动：如果在拖拽模式，计算新窗口位置并移动。

        新位置 = 当前鼠标全局坐标 - 窗口内相对偏移。
        这样窗口跟随鼠标移动，且不会"跳动"（保持按下的那一点相对窗口不变）。
        """
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放：退出拖拽模式。"""
        self._dragging = False
        super().mouseReleaseEvent(event)

    # =========================================================================
    # 数据加载与下拉框填充
    # =========================================================================

    def _populate_decks(self) -> None:
        """从 CSV 加载卡组列表和段位列表，填充两个下拉框。

        卡组下拉：
            - 从 CSV 的"使用卡组"列提取所有不重复的卡组名
            - 排序后填充，第一项固定为"全部"
            - 如果 CSV 中有最近一局的卡组，自动选中它

        段位下拉（动态版本）：
            - 不再写死列表，而是从 CSV 的"己方段位"列提取
            - 只显示数据中真正出现过的已知大段（如黄金、钻石）
            - 末尾固定加"无段位/其他"（空白段位 + 未知段位）
        """
        records = load_records()  # 从 CSV 加载全部对局记录

        # ---- 卡组下拉 ----
        # 用集合推导式去重 → sorted 排序 → 依次添加到下拉框
        decks = sorted({r.get("使用卡组", "(未指定)") or "(未指定)"
                        for r in records})
        self._deck_combo.addItem("全部")
        for d in decks:
            self._deck_combo.addItem(d)
        # 如果 CSV 有数据，自动选中最后一局使用的卡组
        if records:
            last_deck = records[-1].get("使用卡组", "") or "全部"
            idx = self._deck_combo.findText(last_deck)
            if idx >= 0:
                self._deck_combo.setCurrentIndex(idx)

        # ---- 段位下拉（动态） ----
        self._rank_combo.addItem("全部")
        # get_available_rank_tiers 从 CSV 中提取实际出现过的已知段位
        for tier in get_available_rank_tiers(records):
            self._rank_combo.addItem(tier)
        self._rank_combo.addItem("无段位/其他")  # 末尾：空白段位 + 未知段位

    def _apply_dwm_round_corners(self) -> None:
        """给无边框窗口加上 Windows 11 原生圆角。

        调用 Windows DWM API（桌面窗口管理器），设置 DWM_WINDOW_CORNER_PREFERENCE
        属性为 DWMWCP_ROUND（圆角模式）。

        DWM 常量值:
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
        """
        try:
            hwnd = int(self.winId())             # Qt 窗口 → Windows 句柄
            dwmwa = 33                            # 属性 ID：窗口圆角偏好
            dwmwcp_round = 2                      # 值：圆角
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd, dwmwa,
                ctypes.byref(ctypes.c_int(dwmwcp_round)),
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass  # 非 Windows 系统或 DWM 不可用时静默跳过

    # =========================================================================
    # 背景绘制 — paintEvent
    # =========================================================================

    def paintEvent(self, event) -> None:
        """手绘弹窗背景，兼容两种主题模式。

        调用时机：Qt 需要重绘窗口时自动调用（窗口首次显示、尺寸变化、
        被其他窗口遮挡后恢复等）。

        逻辑：
            - 有背景图（_bg_pixmap 不为 None）：先用 QPainter 把背景图
              缩放并贴满整个窗口，再调用 super().paintEvent() 让 Qt 绘制
              子控件。子控件（内容区）的半透明背景就会透出底图。
            - 无背景图（纯色主题）：直接走 super().paintEvent()，
              由样式表 background-color 提供纯色背景。
        """
        painter = QPainter(self)
        if self._bg_pixmap is not None:
            # 把背景图缩放至窗口大小，拉伸填充（不保持比例）
            scaled = self._bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,          # 不保持原图比例
                Qt.TransformationMode.SmoothTransformation,    # 平滑缩放（抗锯齿）
            )
            painter.drawPixmap(0, 0, scaled)  # 在窗口 (0,0) 位置绘制
        painter.end()  # 结束 QPainter 绘画，释放绘图资源
        super().paintEvent(event)  # 让 Qt 继续绘制子控件和样式表背景

    # =========================================================================
    # 统计刷新
    # =========================================================================

    def _refresh(self) -> None:
        """根据当前筛选条件（卡组 + 段位），重新计算并显示统计数据。

        触发时机：
            - 弹窗首次打开（__init__ 末尾）
            - 用户切换卡组下拉框
            - 用户切换己方段位下拉框

        流程：
            1. 读取下拉框的当前值
            2. "全部" → 空字符串（compute_filtered_stats 里空字符串 = 不过滤）
            3. 重新从 CSV 加载数据
            4. 调用 compute_filtered_stats 做筛选 + 统计
            5. 把返回的 17 项指标逐个填入对应的 QLabel
        """
        deck = self._deck_combo.currentText()
        if deck == "全部":
            deck = ""      # 空字符串 → 不按卡组过滤
        rank = self._rank_combo.currentText()
        if rank == "全部":
            rank = ""      # 空字符串 → 不按段位过滤

        records = load_records()  # 每次都重新加载（数据可能已被其他操作更新）
        stats = compute_filtered_stats(records, deck, rank)

        # 遍历 17 项统计指标，更新对应 QLabel 的显示文字
        for key, lbl in self._stat_labels.items():
            val = stats.get(key, "—")  # 没数据时显示 "—"
            lbl.setText(str(val))

    # =========================================================================
    # 复制到剪贴板
    # =========================================================================

    def _copy_stats(self) -> None:
        """将当前显示的统计信息拼成多行文本，复制到系统剪贴板。

        复制格式示例:
            卡组: 炎兽  己方段位: 黄金
            （空行）
            对局数: 42
            胜: 28
            负: 14
            胜率: 66.7%
            ...

        用户体验细节：
            - 点击按钮后文字临时变为"已复制 ✓"
            - 1.5 秒后自动恢复为"复制统计"
            - QTimer.singleShot 是单次定时器，只触发一次
        """
        deck = self._deck_combo.currentText()
        rank = self._rank_combo.currentText()
        # 第一行：当前筛选条件
        lines = [f"卡组: {deck}  己方段位: {rank}", ""]
        # 逐行添加统计指标
        for key, lbl in self._stat_labels.items():
            lines.append(f"{key}: {lbl.text()}")
        text = "\n".join(lines)
        # QApplication.clipboard() 返回系统剪贴板对象，setText 写入文本
        QApplication.clipboard().setText(text)
        self._btn_copy.setText("已复制 ✓")
        # 1.5 秒后恢复按钮文字（lambda 延迟执行）
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self._btn_copy.setText("复制统计"))
