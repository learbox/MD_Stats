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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout,
)

from ui._base_dialog import _BaseFramelessDialog
from src.recorder import (
    compute_filtered_stats, get_available_rank_tiers, load_records,
)


class RankStatsDialog(_BaseFramelessDialog):
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

        # 背景图 + 拖拽（基类 _BaseFramelessDialog 提供）
        self._init_background(bg_path)
        self._init_drag()

        # 窗口基本属性
        self.setWindowTitle("详细统计")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(410, 390)
        self.resize(450, 430)
        self.setObjectName("rankStatsDialog")

        # ===== 对话框背景色（双模式，规则见基类 _themed_background_colors） =====
        dialog_bg, content_bg = self._themed_background_colors(widget_bg, main_bg)
        self.setStyleSheet(f"#rankStatsDialog {{ background: {dialog_bg}; }}")
        self._apply_dwm_round_corners()

        # ===== 主布局：标题栏 + 内容区 =====
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)  # 无边距，内容撑满整个弹窗
        outer.setSpacing(0)                    # 标题栏和内容区之间无间隙
        outer.addWidget(self._make_titlebar("  详细统计信息", "rankStatsTitle"))

        # 内容区：用 QFrame 而非 QWidget。
        # 为什么是 QFrame？纯 QWidget 对样式表 rgba() 解析不稳定（会报
        # "Could not parse stylesheet"），QFrame 的渲染管线和 QTabWidget::pane
        # 一致，能正确处理带 alpha 的颜色。
        content = QFrame()
        content.setFrameShape(QFrame.Shape.NoFrame)  # 不画边框，只做容器
        content.setObjectName("rankStatsContent")     # QSS 选择器用的 ID
        # 内容区背景：背景图主题半透明 / 纯色主题实色（见 _themed_background_colors）
        content.setStyleSheet(
            f"#rankStatsContent {{ background: {content_bg}; border: none; }}"
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
            ("对局数", "胜"), ("负", "平"), ("胜率", ""),
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
