"""主题加载模块 — 从 themes/ 文件夹加载 QSS、颜色表、标题栏配置及资源。

================================================================================
加载优先级

    1. themes/{name}/   → 用户指定的主题（文件夹存在则直接用）
    2. 内置硬编码 fallback → 主题文件夹不存在时兜底（亮色，零外部依赖）

================================================================================
theme.toml 结构

    [meta]
    name = "暗色沉浸"

    [titlebar]
    height = 36
    icon_size = 20
    text_color = "#b8b8c8"
    text_size = 12
    btn_hover_bg = "#2a2a4a"
    btn_close_hover = "#e74c3c"

    [assets]
    font_family = "Microsoft YaHei"
    font_size   = 13

    [[assets.fonts]]
    file = "NotoSansSC-Regular.ttf"
    family = "Noto Sans SC"

    [assets.images]
    main_bg      = { file = "bg.png", mode = "stretch" }
    ...

    [colors]
    main_bg = "#1a1a2e"
    ...

================================================================================
使用方式

    from src.theme_loader import load_theme

    theme = load_theme("dark")
    window.setStyleSheet(theme.qss)
    titlebar = TitleBar("MD Stats", theme.titlebar, theme.assets_dir)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import get_project_root

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

# 字体加载
from PySide6.QtGui import QFontDatabase

# themes/ 文件夹路径（开发/打包兼容）
_THEMES_DIR = get_project_root() / "themes"

_DEFAULT_FONT = "Microsoft YaHei"


@dataclass
class Theme:
    """加载完成的主题数据包。"""
    qss: str                                    # 替换占位符后的 QSS 字符串
    colors: dict[str, str]                       # [colors] 颜色字典
    titlebar: dict[str, Any]                     # [titlebar] 配置
    assets_dir: Path                             # 主题 assets/ 目录的绝对路径
    pixmaps: dict[str, Any] = field(default_factory=dict)  # {selector: QPixmap}


# =============================================================================
# 最终兜底：硬编码亮色主题
# =============================================================================

_BUILTIN_COLORS: dict[str, str] = {
    # 背景层次
    "main_bg": "#f5f6fa", "widget_bg": "#ffffff", "alt_row_bg": "#f5f7fa",
    "statusbar_bg": "#ecf0f1",
    # 文字
    "text_primary": "#2c3e50", "text_secondary": "#7f8c8d",
    "text_disabled": "#bdc3c7", "table_text": "#2c3e50",
    # 边框
    "border": "#dcdde1", "border_hover": "#3498db", "border_focus": "#3498db",
    "border_disabled": "#ecf0f1",
    # 交互
    "hover_bg": "#e8f0fe", "pressed_bg": "#d5e4f7",
    "selection_bg": "#d5e4f7",
    # 语义色
    "win": "#27ae60", "lose": "#c0392b", "coin": "#e67e22", "turn": "#2980b9",
    "start_bg": "#27ae60", "warning_bg": "#e67e22", "muted_bg": "#95a5a6",
    # 分割器
    "splitter": "#dcdde1", "splitter_hover": "#3498db", "header_accent": "#3498db",
    # 下拉框
    "combo_bg": "#ffffff", "combo_border": "#dcdde1", "msgbox_bg": "#f5f6fa",
    # —— 细粒度控件配色（用于统一 QSS 模板） ——
    "button_bg": "#ffffff", "button_border": "#dcdde1",
    "button_hover_bg": "#e8f0fe", "button_pressed_bg": "#d5e4f7",
    "button_disabled_bg": "#ecf0f1",
    "input_bg": "#ffffff", "input_focus_bg": "#ffffff",
    "input_disabled_bg": "#ecf0f1",
    "table_grid": "#dcdde1", "table_alt_bg": "#f5f7fa",
    "table_item_bg": "transparent", "table_item_alt_bg": "transparent",
    "table_selection_bg": "#d5e4f7",
    "header_v_bg": "#ecf0f1", "header_v_border": "#dcdde1",
    "corner_bg": "#ecf0f1", "corner_border": "#dcdde1",
    "scrollbar_handle": "#7f8c8d", "scrollbar_handle_hover": "#3498db",
    "combo_body_bg": "#ffffff", "combo_list_bg": "#ffffff",
}

_BUILTIN_TITLEBAR: dict[str, Any] = {
    "height": 36, "icon_size": 20,
    "text_color": "#2c3e50", "text_size": 12,
    "text_font": "", "text_shadow": "",
    "btn_hover_bg": "#d5e4f7", "btn_close_hover": "#e74c3c",
}

_BUILTIN_ASSETS: dict[str, Any] = {
    "font_family": _DEFAULT_FONT, "font_size": 13,
    "header_font_size": 12, "row_header_font_size": 11,
    "table_font_size": 13,
    "fonts": [], "images": {},
}

_BUILTIN_QSS = """\
QMainWindow { background-color: %(main_bg)s; }
QWidget { color: %(text_primary)s; font-family: "%(font_family)s"; font-size: %(font_size)spx; }
QPushButton, QLineEdit, QLabel, QTableWidget, QHeaderView, QHeaderView::section,
QComboBox, QComboBox QAbstractItemView, QMessageBox, QToolTip {
    font-family: "%(font_family)s";
}
/* ---------- 主背景 ---------- */
#contentWidget { border-radius: 8px; background-color: %(main_bg)s; }
/* ---------- 面板 ---------- */
QFrame#topPanel, QFrame#bottomPanel { background: transparent; border: none; border-radius: 10px; padding: 4px; }
/* ---------- 标题栏 ---------- */
#titleBar { background: transparent; border-top-left-radius: 8px; border-top-right-radius: 8px; }
#titleMinBtn, #titleCloseBtn { background: transparent; border: none; border-radius: 4px; }
/* ---------- 状态栏 ---------- */
#customStatusBar { background-color: %(statusbar_bg)s; border: none; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; }
#statusMessage { color: %(text_secondary)s; background: transparent; border: none; font-size: 12px; }
/* ---------- 按钮 ---------- */
QPushButton { background-color: %(button_bg)s; color: %(text_primary)s; border: 1px solid %(button_border)s; border-radius: 12px; padding: 5px 14px; }
QPushButton:hover { background-color: %(button_hover_bg)s; border-color: %(border_hover)s; }
QPushButton:pressed { background-color: %(button_pressed_bg)s; border-color: %(border_hover)s; }
QPushButton:disabled { background-color: %(button_disabled_bg)s; color: %(text_disabled)s; border-color: %(border_disabled)s; }
/* ---------- 输入框 ---------- */
QLineEdit { background-color: %(input_bg)s; color: %(text_primary)s; border: 1px solid %(border)s; border-radius: 6px; padding: 4px 10px; }
QLineEdit:focus { border-color: %(border_focus)s; background-color: %(input_focus_bg)s; }
QLineEdit:disabled { background-color: %(input_disabled_bg)s; color: %(text_disabled)s; }
/* ---------- 标签 ---------- */
QLabel { background: transparent; border: none; }
/* ---------- 表格 ---------- */
QTableWidget { background-color: %(widget_bg)s; alternate-background-color: %(table_alt_bg)s; color: %(table_text)s; font-size: %(table_font_size)spx; border: none; gridline-color: %(table_grid)s; outline: none; selection-background-color: %(table_selection_bg)s; selection-color: %(table_text)s; }
QTableWidget::item { background-color: %(table_item_bg)s; padding: 2px 6px; }
QTableWidget::item:alternate { background-color: %(table_item_alt_bg)s; }
QTableWidget::item:selected { background-color: %(table_selection_bg)s; color: %(table_text)s; }
QHeaderView { background-color: transparent; border: none; }
QHeaderView::section { background-color: transparent; color: %(text_primary)s; border: none; border-bottom: 2px solid %(header_accent)s; padding: 5px 8px; font-weight: bold; font-size: %(header_font_size)spx; }
QHeaderView::section:vertical { background-color: %(header_v_bg)s; color: %(text_primary)s; border: none; border-right: 1px solid %(header_v_border)s; padding: 0px 4px; font-size: %(row_header_font_size)spx; }
QTableCornerButton::section { background-color: %(corner_bg)s; border: none; border-bottom: 2px solid %(header_accent)s; border-right: 1px solid %(corner_border)s; }
/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background-color: %(scrollbar_handle)s; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(scrollbar_handle_hover)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; }
QScrollBar::handle:horizontal { background-color: %(scrollbar_handle)s; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: %(scrollbar_handle_hover)s; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
/* ---------- 分割器 ---------- */
QSplitter::handle { background-color: %(splitter)s; }
QSplitter::handle:hover { background-color: %(splitter_hover)s; }
QSplitter::handle:vertical { height: 3px; }
/* ---------- 下拉框 ---------- */
QComboBox { background-color: %(combo_body_bg)s; color: %(text_primary)s; border: 1px solid %(combo_border)s; border-radius: 6px; padding: 3px 8px; }
QComboBox:hover { border-color: %(border_hover)s; }
QComboBox QAbstractItemView { background-color: %(combo_list_bg)s; color: %(text_primary)s; border: 1px solid %(combo_border)s; selection-background-color: %(selection_bg)s; outline: none; }
/* ---------- 消息框 ---------- */
QMessageBox { background-color: %(msgbox_bg)s; }
QMessageBox QLabel { color: %(text_primary)s; }
"""


# =============================================================================
# 公共 API
# =============================================================================

def load_theme(name: str) -> Theme:
    """加载指定主题，按优先级回退。"""
    if not name:
        name = "light"

    theme_dir = _THEMES_DIR / name
    if theme_dir.is_dir():
        return _build_theme(theme_dir)

    return _fallback_theme()


# =============================================================================
# 内部实现
# =============================================================================

def _build_theme(theme_dir: Path) -> Theme:
    """从指定主题文件夹构建 Theme 对象。"""
    assets_dir = theme_dir / "assets"

    # --- 加载 theme.toml ---
    toml_path = theme_dir / "theme.toml"
    data: dict[str, Any] = {}
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)  # type: ignore[assignment]

    colors_raw = data.get("colors")
    colors: dict[str, str] = (
        dict(colors_raw) if isinstance(colors_raw, dict) and colors_raw
        else dict(_BUILTIN_COLORS)
    )
    titlebar_raw = data.get("titlebar")
    titlebar: dict[str, Any] = (
        dict(titlebar_raw) if isinstance(titlebar_raw, dict) and titlebar_raw
        else dict(_BUILTIN_TITLEBAR)
    )
    assets_raw = data.get("assets")
    assets_cfg: dict[str, Any] = (
        dict(assets_raw) if isinstance(assets_raw, dict) and assets_raw
        else dict(_BUILTIN_ASSETS)
    )

    # --- 加载字体 ---
    _load_fonts(assets_cfg.get("fonts", []), assets_dir)

    font_family = assets_cfg.get("font_family", _DEFAULT_FONT)
    font_size = assets_cfg.get("font_size", 13)

    # --- 加载 QSS ---
    qss_path = theme_dir / "style.qss"
    if qss_path.exists():
        qss = qss_path.read_text(encoding="utf-8")
    else:
        qss = _BUILTIN_QSS

    # 替换 {{color.xxx}} 占位符
    for key, val in colors.items():
        qss = qss.replace("{{color." + key + "}}", val)

    # 替换 {{assets.xxx}} 占位符
    # font_family 既支持单个字体名（"Microsoft YaHei"，自动补引号），
    # 也支持完整的字体回退栈（'"Yuppy SC", "Comic Sans MS"'，按原样使用）。
    # 检测：如果已经含逗号或引号则视为已格式化好的 QSS 字体栈，避免双重加引号。
    ff_value = font_family if ("," in font_family or '"' in font_family) else f'"{font_family}"'
    qss = qss.replace("{{assets.font_family}}", ff_value)
    qss = qss.replace("{{assets.font_size}}", str(font_size))
    qss = qss.replace("{{assets.header_font_size}}",
                      str(assets_cfg.get("header_font_size", 12)))
    qss = qss.replace("{{assets.row_header_font_size}}",
                      str(assets_cfg.get("row_header_font_size", 11)))
    qss = qss.replace("{{assets.table_font_size}}",
                      str(assets_cfg.get("table_font_size", 13)))

    # 替换 {{asset.<image_key>}} 占位符 → 资源文件的绝对路径（POSIX，正斜杠）
    # QSS 中可以用 border-image: url({{asset.main_bg}}) ... 引用主题图片
    qss = _substitute_asset_paths(qss, assets_cfg.get("images", {}), assets_dir)

    # 清理残留的 {{asset.xxx}} 占位符（无图片资源的主题不会替换），
    # 用 none 替代使得 QSS 中 url(none) 能被 Qt 安全忽略
    qss = re.sub(r"\{\{asset\.\w+}}", "none", qss)

    # 收集图片（不注入 QSS，由 main_window 用 QPalette 加载）
    pixmaps = _collect_image_paths(assets_cfg.get("images", {}), theme_dir)

    # 确保剩余的 {{color.xxx}} 占位符回退（如果 QSS 中有但主题没定义的）
    for key, val in _BUILTIN_COLORS.items():
        qss = qss.replace("{{color." + key + "}}", val)

    # 构建最终 QSS（附加颜色字典中没有但在内置 QSS 中需要的值）
    full_qss = qss
    # 把 font_family/font_size 注入到 QSS 的 %() 格式化（仅用于内置兜底 QSS）
    colors_with_font: dict[str, Any] = dict(colors)
    colors_with_font["font_family"] = font_family
    colors_with_font["font_size"] = str(font_size)

    # 如果 QSS 文件加载失败兜底用了 _BUILTIN_QSS，需要 % 格式化
    if not (theme_dir / "style.qss").exists():
        full_qss = qss % colors_with_font

    return Theme(
        qss=full_qss,
        colors=colors_with_font,
        titlebar=titlebar,
        assets_dir=assets_dir,
        pixmaps=pixmaps,
    )


def _fallback_theme() -> Theme:
    """最终兜底：返回内置硬编码亮色主题。"""
    colors: dict[str, Any] = dict(_BUILTIN_COLORS)
    colors["font_family"] = _DEFAULT_FONT
    colors["font_size"] = "13"
    colors["header_font_size"] = "12"
    colors["row_header_font_size"] = "11"
    colors["table_font_size"] = "13"
    qss = _BUILTIN_QSS % colors
    return Theme(
        qss=qss,
        colors=colors,
        titlebar=dict(_BUILTIN_TITLEBAR),
        assets_dir=_THEMES_DIR / "builtin_light" / "assets",
        pixmaps={},
    )


def _load_fonts(fonts: list[dict], assets_dir: Path) -> None:
    """从 assets/ 加载 TTF 字体文件。"""
    for entry in fonts:
        file = entry.get("file", "")
        if not file:
            continue
        path = assets_dir / file
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


# 图片配置 → QSS 选择器映射
_IMAGE_SELECTORS: dict[str, str] = {
    "main_bg":        "#contentWidget",
    "table_bg":       "QTableWidget",
    "header_bg":      "QHeaderView::section",
    "row_header_bg":  "QHeaderView::section:vertical",
    "corner_bg":      "QTableCornerButton::section",
    "button_bg":      "QPushButton",
    "statusbar_bg":   "#customStatusBar",
}

def _substitute_asset_paths(qss: str, images: dict, assets_dir: Path) -> str:
    """将 {{asset.<key>}} 替换为 assets/<file> 的绝对 POSIX 路径。

    QSS 的 url(...) 在所有平台都需要正斜杠（Windows 的反斜杠会失败）。
    """
    for key, cfg in images.items():
        if not isinstance(cfg, dict):
            continue
        file = (cfg.get("file", "") or "").strip()
        if not file:
            continue
        file_path = assets_dir / file
        # as_posix() 给出正斜杠路径，兼容 Qt 的 url(...) 解析
        url = file_path.resolve().as_posix()
        qss = qss.replace("{{asset." + key + "}}", url)
    return qss


def _collect_image_paths(images: dict, theme_dir: Path) -> dict[str, str]:
    """收集存在的图片文件路径，返回 {selector: file_path}。"""
    assets_dir = theme_dir / "assets"
    result: dict[str, str] = {}
    for key, cfg in images.items():
        if not isinstance(cfg, dict):
            continue
        file = (cfg.get("file", "") or "").strip()
        if not file:
            continue
        file_path = assets_dir / file
        if not file_path.exists():
            continue
        selector = _IMAGE_SELECTORS.get(key)
        if selector:
            result[selector] = str(file_path)
    return result
