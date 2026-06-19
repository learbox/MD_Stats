"""详细统计信息弹窗 — 按卡组 + 段位筛选，展示 17 项统计指标。

样式参考 ConfigDialog：自定义标题栏 + 半透明背景 + 无边框窗口。"""

import ctypes

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
    QVBoxLayout, QWidget,
)

from src.config import get_project_root
from src.recorder import compute_filtered_stats, load_records

RANK_TIERS = ["全部", "新手", "青铜", "白银", "黄金", "铂金", "钻石", "大师", "巅峰"]


class RankStatsDialog(QDialog):
    """详细统计信息弹窗。"""

    def __init__(self, parent, config: dict, theme_colors: dict,
                 bg_path: str = "", widget_bg: str = "#ffffff",
                 main_bg: str = "#f0f0f0"):
        super().__init__(parent)
        self._config = config
        self._colors = theme_colors
        self._widget_bg = widget_bg
        self._main_bg = main_bg

        # 背景图
        self._bg_pixmap: QPixmap | None = None
        if bg_path:
            pm = QPixmap(bg_path)
            if not pm.isNull():
                self._bg_pixmap = pm

        # 拖拽
        self._dragging = False
        self._drag_start = QPoint()

        # 窗口属性
        self.setWindowTitle("详细统计")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(460, 440)
        self.resize(500, 480)
        self.setObjectName("rankStatsDialog")

        # 背景色
        dialog_bg = widget_bg
        if self._bg_pixmap is None:
            mr, mg, mb = int(main_bg[1:3], 16), int(main_bg[3:5], 16), int(main_bg[5:7], 16)
            shift = 5
            dr = mr + shift if mr <= 128 else mr - shift
            dg = mg + shift if mg <= 128 else mg - shift
            db = mb + shift if mb <= 128 else mb - shift
            dialog_bg = f"#{dr:02x}{dg:02x}{db:02x}"
        self.setStyleSheet(f"#rankStatsDialog {{ background: {dialog_bg}; }}")
        self._apply_dwm_round_corners()

        # 主布局：标题栏 + 半透明内容区
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 0, 8, 8)
        outer.setSpacing(0)
        outer.addWidget(self._make_titlebar())

        # 统计内容区，半透明底仅此区域透出背景图
        content = QWidget()
        content.setObjectName("rankStatsContent")
        # 用 theme_colors 的 widget_bg 计算半透明色，兼容 non-hex 值
        wbg = widget_bg
        if wbg and wbg.startswith("#") and len(wbg) == 7:
            r, g, b = int(wbg[1:3], 16), int(wbg[3:5], 16), int(wbg[5:7], 16)
            semi = f"rgba({r},{g},{b},180)"
        else:
            semi = "rgba(255,255,255,180)"
        content.setStyleSheet(
            f"#rankStatsContent {{ background: {semi}; border: none; "
            "border-radius: 8px; }}"
        )
        outer.addWidget(content)

        inner = QVBoxLayout(content)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(10)

        # ---- 筛选栏 ----
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("卡组:"))
        self._deck_combo = QComboBox()
        self._deck_combo.setMinimumWidth(120)
        filter_row.addWidget(self._deck_combo)
        filter_row.addWidget(QLabel("对方段位:"))
        self._rank_combo = QComboBox()
        self._rank_combo.addItems(RANK_TIERS)
        self._rank_combo.setMinimumWidth(80)
        filter_row.addWidget(self._rank_combo)
        filter_row.addStretch()
        inner.addLayout(filter_row)

        # ---- 17 项统计指标 (2 列网格) ----
        self._stat_labels: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setSpacing(4)
        items = [
            ("对局数", "胜"), ("负", "胜率"),
            ("赢硬币次数", "输硬币次数"), ("赢硬币概率", "赢硬币胜率"),
            ("输硬币胜率", "先攻次数"), ("后攻次数", "先攻胜"),
            ("后攻胜", "先攻胜率"), ("后攻胜率", "升段次数"),
            ("降段次数", "升段胜率"), ("降段胜率", ""),
        ]
        for row, (k1, k2) in enumerate(items):
            for col, key in enumerate([k1, k2]):
                if not key:
                    continue
                lbl_key = QLabel(f"{key}:")
                lbl_key.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
                lbl_val = QLabel("—")
                lbl_val.setStyleSheet("font-weight: bold; font-size: 14px; background: transparent;")
                self._stat_labels[key] = lbl_val
                pair = QHBoxLayout()
                pair.setSpacing(4)
                pair.addWidget(lbl_key)
                pair.addWidget(lbl_val)
                pair.addStretch()
                grid.addLayout(pair, row, col)
        inner.addLayout(grid)
        inner.addStretch()

        # ---- 联动 ----
        self._deck_combo.currentTextChanged.connect(self._refresh)
        self._rank_combo.currentTextChanged.connect(self._refresh)

        self._populate_decks()
        self._refresh()

    # =========================================================================
    # 标题栏
    # =========================================================================

    def _make_titlebar(self) -> QWidget:
        """创建顶部自定义标题栏（可拖拽 + 关闭按钮）。"""
        bar = QWidget()
        bar.setObjectName("rankStatsTitle")
        bar.setFixedHeight(36)
        bar.setStyleSheet("#rankStatsTitle { background: transparent; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 4, 0)

        title = QLabel("  详细统计信息")
        title.setStyleSheet("font-size: 13px; font-weight: bold; "
                            "background: transparent; border: none;")
        layout.addWidget(title)
        layout.addStretch()

        from ui.titlebar import _TitleBarButton
        assets = get_project_root() / "resource"
        btn_close = _TitleBarButton("title_close", assets, bar)
        close_hover = self._colors.get("btn_close_hover", "#e74c3c")
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent; "
            "border-radius: 4px; }"
            f"QPushButton:hover {{ background-color: {close_hover}; "
            f"border-color: {close_hover}; }}"
        )
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)
        return bar

    # =========================================================================
    # 拖拽
    # =========================================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    # =========================================================================
    # 数据
    # =========================================================================

    def _populate_decks(self) -> None:
        """从 CSV 加载卡组列表到下拉框。"""
        records = load_records()
        decks = sorted({r.get("使用卡组", "(未指定)") or "(未指定)"
                        for r in records})
        self._deck_combo.addItem("全部")
        for d in decks:
            self._deck_combo.addItem(d)
        if records:
            last_deck = records[-1].get("使用卡组", "") or "全部"
            idx = self._deck_combo.findText(last_deck)
            if idx >= 0:
                self._deck_combo.setCurrentIndex(idx)

    def _apply_dwm_round_corners(self) -> None:
        """启用 Windows DWM 窗口圆角（与 ConfigDialog 一致）。"""
        try:
            hwnd = int(self.winId())
            dwmwa = 33  # DWMWA_WINDOW_CORNER_PREFERENCE
            dwmwcp_round = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd, dwmwa,
                ctypes.byref(ctypes.c_int(dwmwcp_round)),
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass

    def _refresh(self) -> None:
        """根据筛选条件刷新统计显示。"""
        deck = self._deck_combo.currentText()
        if deck == "全部":
            deck = ""
        rank = self._rank_combo.currentText()
        if rank == "全部":
            rank = ""

        records = load_records()
        stats = compute_filtered_stats(records, deck, rank)

        for key, lbl in self._stat_labels.items():
            val = stats.get(key, "—")
            lbl.setText(str(val))
