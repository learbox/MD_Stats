"""设置弹窗 — 图形化编辑 config.toml，代替手动编辑文本文件。

================================================================================
架构

    ConfigDialog(QDialog)
      ├── 自定义标题栏（拖拽 + 关闭按钮）
      ├── QTabWidget（5 个标签页）
      │   ├── 识别 — 截图间隔、匹配阈值
      │   ├── 外观 — 主题、窗口尺寸
      │   ├── 剪贴板 — 竖排、范围、列选择
      │   ├── 悬浮窗 — 尺寸/颜色/透明度/字体/行选择
      │   └── 数据 — 卡组预设、分文件
      ├── 预览区 — 悬浮窗小样
      └── 按钮栏 — [取消] [确定]

工作流程:
    1. 用户点击主窗口"设置" → _on_settings() → ConfigDialog(config).exec()
    2. 弹窗读取 config.toml → 填入各控件
    3. 用户修改 → 点"确定" → 写回 config.toml → 调用 _on_reload_config()
    4. 点"取消"或 × → 丢弃修改

使用的 Qt 概念速查:
    QDialog      — 模态弹窗（打开时阻断主窗口操作）
    QTabWidget   — 标签页容器，顶部显示页签切换
    QSpinBox     — 整数输入框（自带上下箭头）
    QDoubleSpinBox — 小数输入框
    QSlider      — 滑块控件
    QColorDialog — 系统取色器弹窗
    QFontComboBox — 系统字体下拉列表
    QListWidget  — 可滚动的列表控件
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox,
    QFontComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QRadioButton, QSlider, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget, QButtonGroup,
)

from src.config import get_project_root
from ui.floating_window import _ROW_KEY_MAP, _DEFAULT_ROWS

_BUILTIN_THEME = "(内置亮色)"


# =============================================================================
# ColorButton — 色块按钮，点击弹出系统取色器
# =============================================================================

class ColorButton(QPushButton):
    """显示当前颜色的小色块按钮。点击弹出系统取色器，避免手写 #RRGGBB。"""

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(48, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self.clicked.connect(self._pick)

    def _update_style(self) -> None:
        c = self._color
        self.setStyleSheet(
            f"QPushButton {{ background-color: {c.name()}; "
            f"border: 1px solid #888; border-radius: 4px; }}"
        )

    def _pick(self) -> None:
        # DontUseNativeDialog 让 Qt 使用自己的取色器（支持中文界面）
        dlg = QColorDialog(self._color, self)
        dlg.setWindowTitle("选择颜色")
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._color = dlg.currentColor()
            self._update_style()

    def color(self) -> QColor:
        return self._color

    def set_color(self, color: QColor) -> None:
        self._color = color
        self._update_style()


# =============================================================================
# DualListWidget — 双列选择 + 排序控件
# =============================================================================

class DualListWidget(QWidget):
    """双列列表：左边"可选"，右边"已选"，箭头按钮移动和排序。"""

    def __init__(self, available: list[str], selected: list[str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 左边：可选列表
        left_v = QVBoxLayout()
        left_v.addWidget(QLabel("可选"))
        self._left = QListWidget()
        left_v.addWidget(self._left)
        layout.addLayout(left_v)

        # 中间：方向按钮
        mid = QVBoxLayout()
        mid.addStretch()
        self._btn_r = QPushButton("→")
        self._btn_r.setFixedSize(36, 28)
        self._btn_r.clicked.connect(self._move_right)
        mid.addWidget(self._btn_r)
        self._btn_l = QPushButton("←")
        self._btn_l.setFixedSize(36, 28)
        self._btn_l.clicked.connect(self._move_left)
        mid.addWidget(self._btn_l)
        mid.addSpacing(12)
        self._btn_u = QPushButton("↑")
        self._btn_u.setFixedSize(36, 28)
        self._btn_u.clicked.connect(self._move_up)
        mid.addWidget(self._btn_u)
        self._btn_d = QPushButton("↓")
        self._btn_d.setFixedSize(36, 28)
        self._btn_d.clicked.connect(self._move_down)
        mid.addWidget(self._btn_d)
        mid.addStretch()
        layout.addLayout(mid)

        # 右边：已选列表
        right_v = QVBoxLayout()
        right_v.addWidget(QLabel("已选（可排序）"))
        self._right = QListWidget()
        self._right.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        right_v.addWidget(self._right)
        layout.addLayout(right_v)

        for item in available:
            if item not in selected:
                self._left.addItem(item)
        for item in selected:
            self._right.addItem(item)

    def _move_right(self) -> None:
        for item in self._left.selectedItems():
            self._right.addItem(item.text())
            self._left.takeItem(self._left.row(item))

    def _move_left(self) -> None:
        for item in self._right.selectedItems():
            self._left.addItem(item.text())
            self._right.takeItem(self._right.row(item))

    def _move_up(self) -> None:
        row = self._right.currentRow()
        if row > 0:
            item = self._right.takeItem(row)
            self._right.insertItem(row - 1, item)
            self._right.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self._right.currentRow()
        if row < self._right.count() - 1:
            item = self._right.takeItem(row)
            self._right.insertItem(row + 1, item)
            self._right.setCurrentRow(row + 1)

    def get_selected(self) -> list[str]:
        return [self._right.item(i).text()
                for i in range(self._right.count())]


# =============================================================================
# ConfigDialog
# =============================================================================

class ConfigDialog(QDialog):
    """设置弹窗，5 标签页 + 确定/取消。"""

    config_saved = Signal()

    _ALL_KEYS = list(_ROW_KEY_MAP.keys())

    def __init__(self, config: dict[str, Any],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._dragging = False
        self._drag_start = QPoint()

        self.setWindowTitle("设置")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.Dialog
        )
        self.setMinimumSize(660, 540)
        self.resize(680, 560)
        self.setObjectName("configDialog")
        self._apply_dwm_round_corners()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._make_titlebar())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_detection_tab(), "识别")
        self._tabs.addTab(self._make_appearance_tab(), "外观")
        self._tabs.addTab(self._make_clipboard_tab(), "剪贴板")
        self._tabs.addTab(self._make_float_tab(), "悬浮窗")
        self._tabs.addTab(self._make_data_tab(), "数据")
        outer.addWidget(self._tabs, 1)
        outer.addWidget(self._make_button_bar())

        self._load_from_config()

    # =========================================================================
    # 标题栏
    # =========================================================================

    def _make_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("configDialogTitle")
        bar.setFixedHeight(36)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 4, 0)

        title = QLabel("  设置")
        title.setStyleSheet("font-size: 13px; font-weight: bold; "
                            "background: transparent; border: none;")
        layout.addWidget(title)
        layout.addStretch()

        btn_close = QPushButton("×")
        btn_close.setFixedSize(36, 24)
        btn_close.setFlat(True)
        btn_close.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; "
            "background: transparent; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #e74c3c; color: white; }"
        )
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)
        return bar

    # =========================================================================
    # Tab 1: 识别
    # =========================================================================

    def _make_detection_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(12)

        r = QHBoxLayout()
        r.addWidget(QLabel("截图间隔:"))
        self._interval = QDoubleSpinBox()
        self._interval.setRange(0.1, 10.0)
        self._interval.setSingleStep(0.1)
        self._interval.setSuffix(" 秒")
        r.addWidget(self._interval)
        r.addStretch()
        lo.addLayout(r)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("匹配阈值:"))
        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.0, 1.0)
        self._threshold.setSingleStep(0.05)
        self._threshold.setDecimals(2)
        r2.addWidget(self._threshold)
        r2.addStretch()
        lo.addLayout(r2)

        tip = QLabel("阈值越高越不容易误识别，但可能漏识别。推荐 0.75 ~ 0.90")
        tip.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        lo.addWidget(tip)
        lo.addStretch()
        return w

    # =========================================================================
    # Tab 2: 外观
    # =========================================================================

    def _make_appearance_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(12)

        r = QHBoxLayout()
        r.addWidget(QLabel("主题:"))
        self._theme_combo = QComboBox()
        themes_dir = get_project_root() / "themes"
        names = []
        if themes_dir.is_dir():
            for d in themes_dir.iterdir():
                if d.is_dir() and (d / "theme.toml").exists():
                    names.append(d.name)
        if names:
            self._theme_combo.addItems(names)
        else:
            self._theme_combo.addItem(_BUILTIN_THEME)
            self._theme_combo.setEnabled(False)
        r.addWidget(self._theme_combo)
        r.addStretch()
        lo.addLayout(r)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("窗口宽度:"))
        self._win_width = QSpinBox()
        self._win_width.setRange(400, 5000)
        self._win_width.setSuffix(" px")
        r2.addWidget(self._win_width)
        r2.addStretch()
        lo.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("窗口高度:"))
        self._win_height = QSpinBox()
        self._win_height.setRange(300, 5000)
        self._win_height.setSuffix(" px")
        r3.addWidget(self._win_height)
        r3.addStretch()
        lo.addLayout(r3)

        r4 = QHBoxLayout()
        self._use_theme_bg = QCheckBox("悬浮窗使用主题背景图（不勾=始终纯色）")
        r4.addWidget(self._use_theme_bg)
        r4.addStretch()
        lo.addLayout(r4)

        lo.addStretch()
        return w

    # =========================================================================
    # Tab 3: 剪贴板
    # =========================================================================

    def _make_clipboard_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(8)

        g1 = QGroupBox("复制格式")
        g1l = QVBoxLayout(g1)
        self._cb_tsv = QRadioButton("横排 TSV")
        self._cb_vert = QRadioButton("竖排 key: value")
        bg = QButtonGroup(self)
        bg.addButton(self._cb_tsv, 0)
        bg.addButton(self._cb_vert, 1)
        g1l.addWidget(self._cb_tsv)
        g1l.addWidget(self._cb_vert)
        lo.addWidget(g1)

        g2 = QGroupBox("复制范围")
        g2l = QVBoxLayout(g2)
        self._cb_all = QRadioButton("全部卡组")
        self._cb_curr = QRadioButton("仅当前卡组")
        bg2 = QButtonGroup(self)
        bg2.addButton(self._cb_all, 0)
        bg2.addButton(self._cb_curr, 1)
        g2l.addWidget(self._cb_all)
        g2l.addWidget(self._cb_curr)
        lo.addWidget(g2)

        g3 = QGroupBox("要复制的列")
        g3l = QVBoxLayout(g3)
        self._cb_dual = DualListWidget(self._ALL_KEYS, list(_DEFAULT_ROWS))
        g3l.addWidget(self._cb_dual)
        lo.addWidget(g3)

        return w

    # =========================================================================
    # Tab 4: 悬浮窗
    # =========================================================================

    def _make_float_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(8)

        sr = QHBoxLayout()
        sr.addWidget(QLabel("宽度:"))
        self._fw_w = QSpinBox()
        self._fw_w.setRange(100, 1000)
        self._fw_w.setSuffix(" px")
        sr.addWidget(self._fw_w)
        sr.addWidget(QLabel("高度:"))
        self._fw_h = QSpinBox()
        self._fw_h.setRange(100, 1000)
        self._fw_h.setSuffix(" px")
        sr.addWidget(self._fw_h)
        sr.addStretch()
        lo.addLayout(sr)

        br = QHBoxLayout()
        br.addWidget(QLabel("背景色:"))
        self._fw_bg = ColorButton(QColor("#98d4bb"))
        br.addWidget(self._fw_bg)
        br.addWidget(QLabel("透明度:"))
        self._fw_op = QSlider(Qt.Orientation.Horizontal)
        self._fw_op.setRange(0, 100)
        self._fw_op.setFixedWidth(150)
        br.addWidget(self._fw_op)
        self._fw_opl = QLabel("50%")
        self._fw_op.valueChanged.connect(lambda v: self._fw_opl.setText(f"{v}%"))
        br.addWidget(self._fw_opl)
        br.addStretch()
        lo.addLayout(br)

        tr = QHBoxLayout()
        tr.addWidget(QLabel("文字颜色:"))
        self._fw_tc = ColorButton(QColor("#000000"))
        tr.addWidget(self._fw_tc)
        tr.addWidget(QLabel("字号:"))
        self._fw_fs = QSpinBox()
        self._fw_fs.setRange(8, 72)
        tr.addWidget(self._fw_fs)
        tr.addWidget(QLabel("字体:"))
        self._fw_ff = QFontComboBox()
        tr.addWidget(self._fw_ff)
        tr.addStretch()
        lo.addLayout(tr)

        g = QGroupBox("显示的数据行")
        gl = QVBoxLayout(g)
        self._fw_dual = DualListWidget(self._ALL_KEYS, list(_DEFAULT_ROWS))
        gl.addWidget(self._fw_dual)
        lo.addWidget(g)

        return w

    # =========================================================================
    # Tab 5: 数据
    # =========================================================================

    def _make_data_tab(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setSpacing(8)

        g = QGroupBox("对方卡组预设")
        gl = QVBoxLayout(g)
        self._preset_list = QListWidget()
        gl.addWidget(self._preset_list)

        ar = QHBoxLayout()
        self._preset_input = QLineEdit()
        self._preset_input.setPlaceholderText("输入新卡组名…")
        ar.addWidget(self._preset_input)
        ba = QPushButton("添加")
        ba.clicked.connect(self._add_preset)
        ar.addWidget(ba)
        bd = QPushButton("删除选中")
        bd.clicked.connect(self._del_preset)
        ar.addWidget(bd)
        ar.addStretch()
        gl.addLayout(ar)
        lo.addWidget(g)

        self._daily_files = QCheckBox("按日期分文件存储 CSV")
        lo.addWidget(self._daily_files)
        lo.addStretch()
        return w

    # =========================================================================
    # 按钮栏
    # =========================================================================

    def _make_button_bar(self) -> QWidget:
        bar = QWidget()
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(16, 8, 16, 8)
        lo.addStretch()
        bo = QPushButton("确定")
        bo.clicked.connect(self._on_save)
        bo.setDefault(True)
        lo.addWidget(bo)
        bc = QPushButton("取消")
        bc.clicked.connect(self.reject)
        lo.addWidget(bc)
        return bar

    # =========================================================================
    # 数据加载
    # =========================================================================

    def _load_from_config(self) -> None:
        c = self._config

        d = c.get("detection", {})
        self._interval.setValue(d.get("interval", 0.3))
        self._threshold.setValue(d.get("confidence_threshold", 0.8))

        theme = c.get("appearance", {}).get("theme", "")
        idx = self._theme_combo.findText(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        wd = c.get("window", {})
        self._win_width.setValue(wd.get("width", 1300))
        self._win_height.setValue(wd.get("height", 700))

        cb = c.get("clipboard", {})
        if cb.get("vertical_layout", False):
            self._cb_vert.setChecked(True)
        else:
            self._cb_tsv.setChecked(True)
        if cb.get("scope", "all") == "current":
            self._cb_curr.setChecked(True)
        else:
            self._cb_all.setChecked(True)
        saved_cols = cb.get("columns")
        if saved_cols:
            old = self._cb_dual
            self._cb_dual = DualListWidget(self._ALL_KEYS, list(saved_cols))
            self._replace_in_layout(self._tabs.widget(2), old, self._cb_dual)

        fw = c.get("floating_window", {})
        self._fw_w.setValue(fw.get("width", 250))
        self._fw_h.setValue(fw.get("height", 300))
        bg = fw.get("bg_color", "#98d4bb")
        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        self._fw_bg.set_color(QColor(r, g, b))
        self._fw_op.setValue(fw.get("opacity", 50))
        tc = fw.get("text_color", "#000000")
        r2, g2, b2 = int(tc[1:3], 16), int(tc[3:5], 16), int(tc[5:7], 16)
        self._fw_tc.set_color(QColor(r2, g2, b2))
        self._fw_fs.setValue(fw.get("font_size", 20))
        ff = fw.get("font_family", "")
        if ff:
            idx = self._fw_ff.findText(ff)
            if idx >= 0:
                self._fw_ff.setCurrentIndex(idx)
        saved_rows = fw.get("rows")
        if saved_rows:
            old = self._fw_dual
            self._fw_dual = DualListWidget(self._ALL_KEYS, list(saved_rows))
            self._replace_in_layout(self._tabs.widget(3), old, self._fw_dual)

        self._use_theme_bg.setChecked(fw.get("use_theme_bg", False))

        presets = c.get("opponent_decks", {}).get("presets", [])
        self._preset_list.clear()
        for p in presets:
            if p.strip():
                self._preset_list.addItem(p.strip())
        self._daily_files.setChecked(
            c.get("recorder", {}).get("daily_files", False)
        )

    @staticmethod
    def _replace_in_layout(parent: QWidget, old: QWidget, new: QWidget) -> None:
        """把布局中的旧控件替换为新控件。"""
        lo = parent.layout()
        for i in range(lo.count()):
            item = lo.itemAt(i)
            if item and item.widget() == old:
                lo.removeWidget(old)
                old.deleteLater()
                lo.addWidget(new)
                return

    # =========================================================================
    # 保存
    # =========================================================================

    def _on_save(self) -> None:
        """从控件取值 → 写回 config.toml → 通知主窗口重载。"""
        config = self._config

        config.setdefault("detection", {})
        config["detection"]["interval"] = round(self._interval.value(), 1)
        config["detection"]["confidence_threshold"] = round(self._threshold.value(), 2)

        config.setdefault("appearance", {})
        config["appearance"]["theme"] = self._theme_combo.currentText()

        config.setdefault("window", {})
        config["window"]["width"] = self._win_width.value()
        config["window"]["height"] = self._win_height.value()

        config.setdefault("clipboard", {})
        config["clipboard"]["vertical_layout"] = self._cb_vert.isChecked()
        config["clipboard"]["scope"] = "current" if self._cb_curr.isChecked() else "all"
        config["clipboard"]["columns"] = self._cb_dual.get_selected()

        config.setdefault("floating_window", {})
        config["floating_window"]["width"] = self._fw_w.value()
        config["floating_window"]["height"] = self._fw_h.value()
        config["floating_window"]["bg_color"] = self._fw_bg.color().name()
        config["floating_window"]["opacity"] = self._fw_op.value()
        config["floating_window"]["text_color"] = self._fw_tc.color().name()
        config["floating_window"]["font_size"] = self._fw_fs.value()
        config["floating_window"]["font_family"] = self._fw_ff.currentFont().family()
        config["floating_window"]["rows"] = self._fw_dual.get_selected()
        config["floating_window"]["use_theme_bg"] = self._use_theme_bg.isChecked()

        config.setdefault("opponent_decks", {})
        presets = [self._preset_list.item(i).text().strip()
                   for i in range(self._preset_list.count())]
        config["opponent_decks"]["presets"] = [p for p in presets if p]

        config.setdefault("recorder", {})
        config["recorder"]["daily_files"] = self._daily_files.isChecked()

        self._write_toml(config)
        self.config_saved.emit()
        self.accept()

    @staticmethod
    def _write_toml(data: dict) -> None:
        """把配置字典写成 config.toml 文件。"""
        path = get_project_root() / "config.toml"
        lines: list[str] = [
            "# ==========================================================",
            "# MD Stats 配置文件（由设置 GUI 生成）",
            "# ==========================================================",
            "",
            "[detection]",
        ]

        def _k(key: str, value: Any, suffix: str = "") -> None:
            if isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}{suffix}")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"{suffix}')
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}{suffix}")
            elif isinstance(value, list):
                if not value:
                    lines.append(f"{key} = []{suffix}")
                else:
                    items = ", ".join(f'"{x}"' for x in value)
                    lines.append(f"{key} = [{items}]{suffix}")

        d = data.get("detection", {})
        _k("interval", d.get("interval", 0.3))
        _k("confidence_threshold", d.get("confidence_threshold", 0.8))

        lines.extend(["", "[window]"])
        w = data.get("window", {})
        _k("width", w.get("width", 1300))
        _k("height", w.get("height", 700))

        lines.extend(["", "[appearance]"])
        a = data.get("appearance", {})
        _k("theme", a.get("theme", "dark"))

        lines.extend(["", "[opponent_decks]"])
        od = data.get("opponent_decks", {})
        _k("presets", od.get("presets", []))

        lines.extend(["", "[recorder]"])
        r = data.get("recorder", {})
        _k("daily_files", r.get("daily_files", False))

        lines.extend(["", "[clipboard]"])
        cb = data.get("clipboard", {})
        _k("vertical_layout", cb.get("vertical_layout", False))
        _k("scope", cb.get("scope", "all"))
        _k("columns", cb.get("columns", []))

        lines.extend(["", "[floating_window]"])
        fw = data.get("floating_window", {})
        _k("use_theme_bg", fw.get("use_theme_bg", False))
        _k("width", fw.get("width", 250))
        _k("height", fw.get("height", 300))
        _k("bg_color", fw.get("bg_color", "#BDEF0A"))
        _k("opacity", fw.get("opacity", 50))
        _k("font_size", fw.get("font_size", 20))
        _k("text_color", fw.get("text_color", "#000000"))
        _k("font_family", fw.get("font_family", "Microsoft YaHei"))
        _k("rows", fw.get("rows", []))

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # =========================================================================
    # 卡组预设
    # =========================================================================

    def _add_preset(self) -> None:
        name = self._preset_input.text().strip()
        if not name:
            return
        for i in range(self._preset_list.count()):
            if self._preset_list.item(i).text() == name:
                return
        self._preset_list.addItem(name)
        self._preset_input.clear()

    def _del_preset(self) -> None:
        for item in self._preset_list.selectedItems():
            self._preset_list.takeItem(self._preset_list.row(item))

    # =========================================================================
    # 拖拽
    # =========================================================================

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

    # =========================================================================
    # DWM 圆角（Windows 11）
    # =========================================================================

    def _apply_dwm_round_corners(self) -> None:
        """给无边框弹窗加 Win11 原生圆角。"""
        import ctypes, os
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            dwmwa = 33  # DWMWA_WINDOW_CORNER_PREFERENCE
            dwmwcp_round = 2  # 圆角
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, dwmwa,
                ctypes.byref(ctypes.c_int(dwmwcp_round)),
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass
