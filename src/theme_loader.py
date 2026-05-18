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

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# 字体加载
from PySide6.QtGui import QFontDatabase

# themes/ 文件夹相对于本文件的路径
_THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"


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
    "main_bg": "#f5f6fa", "widget_bg": "#ffffff", "alt_row_bg": "#f5f7fa",
    "statusbar_bg": "#ecf0f1", "text_primary": "#2c3e50", "text_secondary": "#7f8c8d",
    "text_disabled": "#bdc3c7", "table_text": "#2c3e50",
    "border": "#dcdde1", "border_hover": "#3498db", "border_focus": "#3498db",
    "border_disabled": "#ecf0f1", "hover_bg": "#e8f0fe", "pressed_bg": "#d5e4f7",
    "selection_bg": "#d5e4f7",
    "win": "#27ae60", "lose": "#c0392b", "coin": "#e67e22", "turn": "#2980b9",
    "start_bg": "#27ae60", "warning_bg": "#e67e22", "muted_bg": "#95a5a6",
    "splitter": "#dcdde1", "splitter_hover": "#3498db", "header_accent": "#3498db",
    "combo_bg": "#ffffff", "combo_border": "#dcdde1", "msgbox_bg": "#f5f6fa",
}

_BUILTIN_TITLEBAR: dict[str, Any] = {
    "height": 36, "icon_size": 20,
    "text_color": "#2c3e50", "text_size": 12,
    "btn_hover_bg": "#d5e4f7", "btn_close_hover": "#e74c3c",
}

_BUILTIN_ASSETS: dict[str, Any] = {
    "font_family": "Microsoft YaHei", "font_size": 13,
    "fonts": [], "images": {},
}

_BUILTIN_QSS = """\
QMainWindow { background-color: %(main_bg)s; }
QWidget { color: %(text_primary)s; font-family: "%(font_family)s"; font-size: %(font_size)dpx; }
QPushButton { background-color: %(widget_bg)s; color: %(text_primary)s; border: 1px solid %(border)s; border-radius: 6px; padding: 4px 14px; }
QPushButton:hover { background-color: %(hover_bg)s; border-color: %(border_hover)s; }
QPushButton:pressed { background-color: %(pressed_bg)s; }
QPushButton:disabled { background-color: %(border_disabled)s; color: %(text_disabled)s; border-color: %(border_disabled)s; }
QLineEdit { background-color: %(widget_bg)s; color: %(text_primary)s; border: 1px solid %(border)s; border-radius: 4px; padding: 3px 8px; }
QLineEdit:focus { border-color: %(border_focus)s; }
QLineEdit:disabled { background-color: %(border_disabled)s; color: %(text_disabled)s; }
QTableWidget { background-color: %(widget_bg)s; alternate-background-color: %(alt_row_bg)s; color: %(table_text)s; border: 1px solid %(border)s; gridline-color: %(border)s; outline: none; }
QTableWidget::item:selected { background-color: %(selection_bg)s; color: %(table_text)s; }
QHeaderView { background-color: %(statusbar_bg)s; }
QHeaderView::section { background-color: %(statusbar_bg)s; color: %(text_primary)s; border: none; border-bottom: 2px solid %(header_accent)s; padding: 5px 8px; font-weight: bold; font-size: 12px; }
QHeaderView::section:vertical { background-color: %(statusbar_bg)s; color: %(text_secondary)s; border: none; border-right: 1px solid %(border)s; padding: 0px 4px; font-size: 11px; }
QTableCornerButton::section { background-color: %(statusbar_bg)s; border: none; border-bottom: 2px solid %(header_accent)s; border-right: 1px solid %(border)s; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: %(text_secondary)s; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(muted_bg)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; }
QScrollBar::handle:horizontal { background: %(text_secondary)s; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: %(muted_bg)s; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
#customStatusBar { background-color: %(statusbar_bg)s; border: none; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; }
#statusMessage { color: %(text_secondary)s; background: transparent; border: none; font-size: 12px; }
#contentWidget { background-color: %(main_bg)s; border-radius: 8px; }
#titleBar { background-color: %(main_bg)s; border-top-left-radius: 8px; border-top-right-radius: 8px; }
#titleMinBtn, #titleCloseBtn { background: transparent; border: none; border-radius: 4px; }
QSplitter::handle { background-color: %(splitter)s; }
QSplitter::handle:hover { background-color: %(splitter_hover)s; }
QSplitter::handle:vertical { height: 3px; }
QLabel { background: transparent; border: none; }
QComboBox { background-color: %(combo_bg)s; color: %(text_primary)s; border: 1px solid %(combo_border)s; border-radius: 4px; padding: 3px 8px; }
QComboBox:hover { border-color: %(border_hover)s; }
QComboBox QAbstractItemView { background-color: %(combo_bg)s; color: %(text_primary)s; border: 1px solid %(combo_border)s; selection-background-color: %(selection_bg)s; outline: none; }
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
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    else:
        data = {}

    colors: dict[str, str] = dict(data.get("colors", {})) if data.get("colors") else dict(_BUILTIN_COLORS)
    titlebar: dict[str, Any] = dict(data.get("titlebar", {})) if data.get("titlebar") else dict(_BUILTIN_TITLEBAR)
    assets_cfg: dict[str, Any] = dict(data.get("assets", {})) if data.get("assets") else dict(_BUILTIN_ASSETS)

    # --- 加载字体 ---
    _load_fonts(assets_cfg.get("fonts", []), assets_dir)

    font_family = assets_cfg.get("font_family", "Microsoft YaHei")
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

    # 替换 {{asset.<image_key>}} 占位符 → 资源文件的绝对路径（POSIX，正斜杠）
    # QSS 中可以用 border-image: url({{asset.main_bg}}) ... 引用主题图片
    qss = _substitute_asset_paths(qss, assets_cfg.get("images", {}), assets_dir)

    # 收集图片（不注入 QSS，由 main_window 用 QPalette 加载）
    pixmaps = _collect_image_paths(assets_cfg.get("images", {}), theme_dir)

    # 确保剩余的 {{color.xxx}} 占位符回退（如果有 QSS 中有但主题没定义的）
    for key, val in _BUILTIN_COLORS.items():
        qss = qss.replace("{{color." + key + "}}", val)
    qss = qss.replace("{{assets.font_family}}", f'"{font_family}"')
    qss = qss.replace("{{assets.font_size}}", str(font_size))

    # 构建最终 QSS（附加颜色字典中没有但在内置 QSS 中需要的值）
    full_qss = qss
    # 把 font_family/font_size 注入到 QSS 的 %() 格式化（仅用于内置兜底 QSS）
    colors_with_font = dict(colors)
    colors_with_font["font_family"] = font_family
    colors_with_font["font_size"] = font_size

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
    colors = dict(_BUILTIN_COLORS)
    colors["font_family"] = "Microsoft YaHei"
    colors["font_size"] = 13
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
    "main_bg":      "#contentWidget",
    "table_bg":     "QTableWidget",
    "header_bg":    "QHeaderView::section",
    "button_bg":    "QPushButton",
    "statusbar_bg": "#customStatusBar",
}

def _inject_qss_property(qss: str, selector: str, prop_line: str) -> str:
    """在已有选择器块 } 之前注入一行属性（不创建重复块）。"""
    idx = qss.find(selector + " {")
    if idx == -1:
        return qss + f"\n{selector} {{\n{prop_line}\n}}\n"
    # 找到匹配的 }
    i = idx + len(selector) + 2
    depth = 1
    j = i
    while j < len(qss) and depth > 0:
        if qss[j] == "{":
            depth += 1
        elif qss[j] == "}":
            depth -= 1
        j += 1
    return qss[:j - 1] + "    " + prop_line + "\n" + qss[j - 1:]


def _remove_qss_property(qss: str, selector: str, prop: str) -> str:
    """从 QSS 中删除指定选择器块内的指定属性行。"""
    import re
    # 匹配 "selector { ... }" 块
    pattern = re.compile(
        re.escape(selector) + r'\s*\{[^}]*\}',
        re.DOTALL,
    )
    def _clean(m: re.Match[str]) -> str:
        block = m.group()
        # 删除 prop: ...; 行
        block = re.sub(r'\s*' + re.escape(prop) + r'\s*:\s*[^;]+;', '', block)
        return block
    return pattern.sub(_clean, qss)


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
