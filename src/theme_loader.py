"""主题加载模块 — 从 themes/ 文件夹加载 QSS、颜色表、标题栏配置及图片资源。

================================================================================
加载优先级（三级回退）
================================================================================

程序启动或切换主题时，调用 load_theme(theme_name) 加载主题。
按以下顺序尝试，任意一步成功即返回：

    第1级: themes/{name}/theme.toml + style.qss
           ↓ 主题文件夹存在 → 读取 TOML 和 QSS 文件，替换占位符
    第2级: 内置硬编码亮色主题（_BUILTIN_COLORS + _BUILTIN_QSS）
           ↓ 主题文件夹不存在 → 返回零依赖的亮色主题（即使 themes/ 被删除也能运行）

在第1级内部还有子回退：
    第1a: theme.toml 中某个 section 缺失 → 用 _BUILTIN_xxx 兜底
    第1b: 某个 color key 未定义 → 逐个从 _BUILTIN_COLORS 补
    第1c: style.qss 不存在 → 用 _BUILTIN_QSS 兜底

================================================================================
两种 QSS 占位符系统
================================================================================

项目中存在两套不同的 QSS 模板，使用不同的占位符格式：

    主题文件 QSS（themes/*/style.qss）: 使用 {{color.key}} 和 {{asset.key}}
        示例: background-color: {{color.main_bg}};
              border-image: url({{asset.main_bg}}) 0 0 0 0 stretch stretch;
        处理方式: Python 的 str.replace() 逐个替换

    内置兜底 QSS（_BUILTIN_QSS）: 使用 %(key)s
        示例: background-color: %(main_bg)s;
        处理方式: Python 的 % 字符串格式化

为什么有两套？
    主题 QSS 用 {{key}} 是为了让用户打开 style.qss 时能直观看到占位符含义。
    内置 QSS 用 %(key)s 是因为它嵌在 Python 字符串中，多层花括号会导致转义混乱。

================================================================================
theme.toml 完整结构（以 macaron 主题为例）
================================================================================

    [meta]
    name = "马卡龙"                    # 主题显示名称（仅用于 UI 展示）

    [titlebar]
    height = 40                        # 标题栏总高度（像素）
    icon_size = 22                     # 图标显示尺寸（像素）
    text_color = "#9b6b8e"             # 标题文字颜色
    text_size = 16                     # 标题文字字号（像素）
    text_font = '"Marker Felt", ...'   # 标题字体栈（可选，空=用全局字体）
    text_shadow = "#fce4ec"            # 标题文字阴影颜色（可选，空=不启用）
    btn_hover_bg = "#fce4ec"           # 最小化按钮悬停背景色
    btn_close_hover = "#f0a5b5"        # 关闭按钮悬停背景色（红色系）

    [assets]
    font_family = "Microsoft YaHei"    # 全局字体族名
    font_size = 14                     # 全局字号（像素）
    header_font_size = 14              # 列标题字号（像素）
    row_header_font_size = 14          # 行号列字号（像素）
    table_font_size = 14               # 表格内文字字号（像素）

    [[assets.fonts]]                   # 自定义 TTF 字体（可多项，可选）
    file = "MyCustomFont.ttf"          #   assets/ 下的字体文件名
    family = "My Custom Font"          #   加载后的字体族名（填入 font_family 回退栈）

    [assets.images]                    # 背景图片（全部可选，file="" 时用纯色）
    main_bg      = { file = "main_bg.png", mode = "stretch" }
    panel_bg     = { file = "panel_bg.png", mode = "stretch" }
    table_bg     = { file = "table_bg.png", mode = "stretch" }
    header_bg    = { file = "header_bg.png", mode = "stretch" }
    row_header_bg= { file = "row_header_bg.png", mode = "stretch" }
    corner_bg    = { file = "corner_bg.png", mode = "stretch" }
    button_bg    = { file = "button_texture.png", mode = "tile" }
    statusbar_bg = { file = "statusbar_bg.png", mode = "stretch" }

    [colors]                           # 颜色表（所有值都是 #RRGGBB 格式）
    # ... 约 50 个颜色 key，详见 themes/dark/theme.toml 注释

================================================================================
使用方式

    from src.theme_loader import load_theme

    theme = load_theme("dark")           # 加载暗色主题
    window.setStyleSheet(theme.qss)      # 应用 QSS 到窗口
    titlebar = TitleBar("MD Stats",
                        theme.titlebar,   # 标题栏配置
                        theme.assets_dir) # 资源目录路径
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import get_project_root

# ---- TOML 解析：Python 3.11+ 内置，3.10 降级到 tomli ----
import tomllib

# 字体加载（Qt 提供的跨平台字体管理 API）
from PySide6.QtGui import QFontDatabase

# themes/ 文件夹路径（开发模式: 项目根/themes，打包模式: EXE所在目录/themes）
_THEMES_DIR = get_project_root() / "themes"

# 全局默认字体（当主题未指定字体时的兜底）
_DEFAULT_FONT = "Microsoft YaHei"


# =============================================================================
# Theme — 数据类，存储加载完成的主题数据
# =============================================================================

@dataclass
class Theme:
    """加载完成的主题数据包。

    字段说明:
        qss        — 完整的 QSS 样式表字符串（占位符已被替换为实际值）
                     可以直接传给 widget.setStyleSheet() 使用
        colors     — 颜色字典 {key: "#RRGGBB"}，同时包含字体相关的 key
                     （font_family, font_size 等是为了兼容内置 QSS 的 % 格式化）
        titlebar   — 标题栏配置字典，传给 TitleBar 控件
        assets_dir — 主题 assets/ 目录的绝对路径（Path 对象）
        pixmaps    — 图片路径映射 {QSS选择器: 文件路径}，
                     用于 main_window 用 QPalette 贴背景图
    """
    qss: str
    colors: dict[str, str]
    titlebar: dict[str, Any]
    assets_dir: Path
    pixmaps: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 最终兜底：硬编码亮色主题（零外部依赖）
#
# 这些常量的作用是：即使整个 themes/ 文件夹被删除或损坏，
# 程序仍然能启动并显示一个可用的亮色界面，不会崩溃或白屏。
# 颜色值与 themes/light/theme.toml 保持一致。
# =============================================================================

_BUILTIN_COLORS: dict[str, str] = {
    # ---- 背景层次 ----
    "main_bg": "#f5f6fa", "widget_bg": "#ffffff", "alt_row_bg": "#f5f7fa",
    "statusbar_bg": "#ecf0f1",
    # ---- 文字颜色 ----
    "text_primary": "#2c3e50", "text_secondary": "#7f8c8d",
    "text_disabled": "#bdc3c7", "table_text": "#2c3e50",
    # ---- 边框颜色 ----
    "border": "#dcdde1", "border_hover": "#3498db", "border_focus": "#3498db",
    "border_disabled": "#ecf0f1",
    # ---- 交互状态 ----
    "hover_bg": "#e8f0fe", "pressed_bg": "#d5e4f7",
    "selection_bg": "#d5e4f7",
    # ---- 语义色（手动按钮） ----
    "win": "#27ae60", "lose": "#c0392b", "coin": "#e67e22", "turn": "#2980b9",
    "start_bg": "#27ae60", "warning_bg": "#e67e22", "muted_bg": "#95a5a6",
    # ---- 分割器与装饰 ----
    "splitter": "#dcdde1", "splitter_hover": "#3498db", "header_accent": "#3498db",
    # ---- 下拉框与弹窗 ----
    "combo_bg": "#ffffff", "combo_border": "#dcdde1", "msgbox_bg": "#f5f6fa",
    # ---- 细粒度控件配色 ----
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

# 内置 QSS 模板 — 使用 %(key)s 占位符格式
# 内容与 themes/light/style.qss 保持一致，只是占位符格式不同
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
QTableWidget { background-color: %(widget_bg)s; font-size: %(table_font_size)spx; alternate-background-color: %(table_alt_bg)s; color: %(table_text)s; border: none; gridline-color: %(table_grid)s; outline: none; selection-background-color: %(table_selection_bg)s; selection-color: %(table_text)s; }
QTableWidget::item { background-color: %(table_item_bg)s; padding: 2px 6px; }
QTableWidget::item:alternate { background-color: %(table_item_alt_bg)s; }
QTableWidget::item:selected { background-color: %(table_selection_bg)s; color: %(table_text)s; }
QHeaderView#horizontalHeader { background-color: transparent; border: none; }
QHeaderView#verticalHeader { background-color: transparent; border: none; }
QHeaderView::section { border-image: none; background-color: transparent; color: %(text_primary)s; border: none; border-bottom: 2px solid %(header_accent)s; padding: 5px 8px; font-weight: bold; font-size: %(header_font_size)spx; }
QHeaderView::section:vertical { border-image: none; background-color: transparent; color: %(text_primary)s; border: none; border-right: 1px solid %(header_v_border)s; padding: 0px 4px; font-size: %(row_header_font_size)spx; }
QTableCornerButton::section { background-color: transparent; border: none; border-bottom: 2px solid %(header_accent)s; border-right: 1px solid %(header_v_border)s; }
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
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border: none; }
QComboBox QAbstractItemView { background-color: %(combo_list_bg)s; color: %(text_primary)s; border: 1px solid %(combo_border)s; selection-background-color: %(selection_bg)s; outline: none; }
QComboBox QAbstractItemView::item { padding: 4px 8px; }
/* ---------- 消息框 ---------- */
QMessageBox { background-color: %(msgbox_bg)s; }
QMessageBox QLabel { color: %(text_primary)s; }
"""


# =============================================================================
# 公共 API
# =============================================================================

def load_theme(name: str) -> Theme:
    """加载指定主题，按优先级回退。

    这是模块唯一的公开入口。调用方只需要传主题名，不需要关心内部回退逻辑。

    参数:
        name — 主题文件夹名（如 "dark"、"macaron"），也支持子路径

    返回:
        Theme 对象，包含 QSS、颜色、标题栏配置等

    回退链:
        name 为空 → 当作 "light"
        themes/{name}/ 存在 → _build_theme() 从文件夹构建
        themes/{name}/ 不存在 → _fallback_theme() 返回硬编码亮色主题
    """
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
    """从指定主题文件夹构建 Theme 对象。

    这是主题加载的核心逻辑，分6个步骤：

        步骤1: 加载 theme.toml → 解析 [colors]、[titlebar]、[assets]
        步骤2: 加载 TTF 字体文件（如果有）
        步骤3: 加载 style.qss 文件
        步骤4: 替换 QSS 中的占位符 {{color.xxx}}、{{assets.xxx}}、{{asset.xxx}}
        步骤5: 收集图片文件路径（用于 QPalette 贴背景图）
        步骤6: 兜底清理（未替换的占位符用内置值补、% 格式化）

    参数:
        theme_dir — 主题文件夹的 Path 对象（如 Path("themes/dark")）
    """
    assets_dir = theme_dir / "assets"

    # =====================================================================
    # 步骤1: 加载 theme.toml
    #
    # TOML 文件中的三个顶层 section 分别解析:
    #   [colors]   → 颜色字典
    #   [titlebar] → 标题栏外观配置
    #   [assets]   → 字体、字号、图片配置
    #
    # 如果某个 section 缺失或为空，用内置兜底值代替。
    # 注意 TOML 必须以二进制模式 ("rb") 打开。
    # =====================================================================
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

    # =====================================================================
    # 步骤2: 加载 TTF 字体
    #
    # theme.toml 中 [[assets.fonts]] 是一个数组，每项包含 file 和 family。
    # QFontDatabase.addApplicationFont() 把 TTF 注册到 Qt 的字体系统，
    # 之后 QSS 中通过 font-family 引用即可使用，无需安装到系统。
    # =====================================================================
    _load_fonts(assets_cfg.get("fonts", []), assets_dir)

    font_family = assets_cfg.get("font_family", _DEFAULT_FONT)
    font_size = assets_cfg.get("font_size", 13)

    # =====================================================================
    # 步骤3: 加载 style.qss 文件
    #
    # 优先从主题目录读取，不存在时用内置 QSS 兜底。
    # 内置 QSS 使用 %(key)s 占位符，和主题 QSS 的 {{color.key}} 不同，
    # 所以后续分支会分开处理。
    # =====================================================================
    qss_path = theme_dir / "style.qss"
    if qss_path.exists():
        qss = qss_path.read_text(encoding="utf-8")
    else:
        qss = _BUILTIN_QSS

    # =====================================================================
    # 步骤4: 替换 QSS 中的占位符
    #
    # 有三类占位符需要替换:
    #
    #   {{color.xxx}}       → 颜色值（如 #1a1a2e）
    #     遍历 colors 字典，用 str.replace() 逐个替换
    #
    #   {{assets.font_xxx}} → 字体相关值（font_family、font_size 等）
    #     font_family 特殊处理: 如果值含逗号或引号则视为已格式化的
    #     字体回退栈（如 '"Yuppy SC", "Comic Sans MS"'），原样使用；
    #     否则自动加引号（如 Microsoft YaHei → "Microsoft YaHei"）
    #
    #   {{asset.xxx}}       → 图片文件路径（绝对路径，正斜杠）
    #     由 _substitute_asset_paths() 处理，替换为本地文件路径
    # =====================================================================

    # 4a: {{color.xxx}} — 颜色值
    for key, val in colors.items():
        qss = qss.replace("{{color." + key + "}}", val)

    # 4b: {{assets.font_xxx}} — 字体相关，注意 font_family 的引号处理
    ff_value = font_family if ("," in font_family or '"' in font_family) else f'"{font_family}"'
    qss = qss.replace("{{assets.font_family}}", ff_value)
    qss = qss.replace("{{assets.font_size}}", str(font_size))
    qss = qss.replace("{{assets.header_font_size}}",
                      str(assets_cfg.get("header_font_size", 12)))
    qss = qss.replace("{{assets.row_header_font_size}}",
                      str(assets_cfg.get("row_header_font_size", 11)))
    qss = qss.replace("{{assets.table_font_size}}",
                      str(assets_cfg.get("table_font_size", 13)))

    # 4c: {{asset.xxx}} — 图片路径（替换为绝对路径，确保 Qt 能找到文件）
    qss = _substitute_asset_paths(qss, assets_cfg.get("images", {}), assets_dir)

    # 4d: 清理残留的 {{asset.xxx}} 占位符
    #     无图片资源的主题（如 dark/light 的 file=""）不会触发替换，
    #     用 "none" 代替使 QSS 中的 url(none) 能被 Qt 安全忽略。
    qss = re.sub(r"\{\{asset\.\w+}}", "none", qss)

    # =====================================================================
    # 步骤5: 收集图片文件路径
    #
    # 找出实际存在的图片文件，映射到 QSS 选择器。
    # 这些路径不注入 QSS（QSS 中只用了 border-image），
    # 而是传给 main_window 用 QPalette.setBrush() 设置背景纹理。
    # =====================================================================
    pixmaps = _collect_image_paths(assets_cfg.get("images", {}), theme_dir)

    # =====================================================================
    # 步骤6: 兜底清理
    #
    # 6a: 用内置值补上主题未定义的 color key
    #     例如主题 QSS 中用了 {{color.scrollbar_handle}}，
    #     但 theme.toml 中没定义 scrollbar_handle → 从 _BUILTIN_COLORS 补
    #
    # 6b: 如果 style.qss 不存在（用了内置 QSS 兜底），
    #     内置 QSS 使用 %(key)s 占位符，需要用 % 格式化替换
    # =====================================================================

    # 6a: 逐个补未定义的 color key
    for key, val in _BUILTIN_COLORS.items():
        qss = qss.replace("{{color." + key + "}}", val)

    # 准备颜色+字体的合并字典（用于内置 QSS 的 % 格式化）
    colors_with_font: dict[str, Any] = dict(colors)
    colors_with_font["font_family"] = font_family
    colors_with_font["font_size"] = str(font_size)

    full_qss = qss
    # 6b: 内置 QSS 需要 % 格式化
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
    """最终兜底：返回硬编码亮色主题（零文件依赖）。

    当 themes/ 文件夹不存在，或用户指定的主题文件夹不存在时调用。
    返回的 Theme 对象完全基于 _BUILTIN_xxx 常量构建，不需要读取任何文件。

    内置 QSS 使用 %(key)s 占位符，直接用 colors 字典做 % 格式化。
    """
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
        assets_dir=_THEMES_DIR / "builtin_light" / "assets",  # 不存在也无妨
        pixmaps={},
    )


def _load_fonts(fonts: list[dict], assets_dir: Path) -> None:
    """从主题的 assets/ 目录加载 TTF/OTF 字体文件。

    Qt 的 QFontDatabase.addApplicationFont() 注册字体后，
    该字体在当前程序的生命周期内可用，QSS 中通过 font-family 引用即可。
    字体不需要安装到操作系统。

    参数:
        fonts      — [[assets.fonts]] 数组，每项 {"file": "xxx.ttf", "family": "XXX"}
        assets_dir — 主题的 assets/ 目录路径
    """
    for entry in fonts:
        file = entry.get("file", "")
        if not file:
            continue
        path = assets_dir / file
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


# =============================================================================
# 图片相关工具
# =============================================================================

# 图片 key → QSS 选择器 映射表
# theme.toml 中的 main_bg、table_bg 等 key 对应 QSS 中的具体选择器
_IMAGE_SELECTORS: dict[str, str] = {
    "main_bg":        "#contentWidget",            # 主窗口全幅背景
    "table_bg":       "QTableWidget",              # 表格背景
    "header_bg":      "QHeaderView::section",      # 列标题栏背景
    "row_header_bg":  "QHeaderView::section:vertical",  # 行号栏背景
    "corner_bg":      "QTableCornerButton::section",    # 左上角交叉按钮
    "button_bg":      "QPushButton",               # 按钮纹理
    "statusbar_bg":   "#customStatusBar",          # 底部状态栏
    "float_bg":       "__float_bg__",              # 悬浮窗背景图（不匹配 QSS）
    "settings_bg":    "__settings_bg__",           # 设置弹窗背景图
}


def _substitute_asset_paths(qss: str, images: dict, assets_dir: Path) -> str:
    """将 QSS 中的 {{asset.<key>}} 替换为图片文件的绝对路径。

    为什么需要绝对路径？
        程序运行时的工作目录可能不是项目根目录，
        如果 QSS 中写相对路径 url(table_bg.png)，Qt 会从工作目录找，找不到。

    为什么用 as_posix() 而不是直接用 Path 的字符串？
        Windows 文件路径用反斜杠（C:\a\b.png），但 QSS 的 url(...)
        在所有平台上都需要正斜杠（C:/a/b.png），否则 Qt 解析失败。

    参数:
        qss        — 待处理的 QSS 字符串
        images     — [assets.images] 字典，如 {"main_bg": {"file": "bg.png", "mode": "stretch"}}
        assets_dir — assets/ 目录路径

    返回:
        替换后的 QSS 字符串
    """
    for key, cfg in images.items():
        if not isinstance(cfg, dict):
            continue
        file = (cfg.get("file", "") or "").strip()
        if not file:
            continue
        file_path = assets_dir / file
        url = file_path.resolve().as_posix()      # 转为正斜杠的绝对路径
        qss = qss.replace("{{asset." + key + "}}", url)
    return qss


def _collect_image_paths(images: dict, theme_dir: Path) -> dict[str, str]:
    """收集实际存在的图片文件路径，返回 {QSS选择器: 文件路径}。

    遍历 [assets.images] 中所有配置项，检查对应的文件是否存在。
    只收集实际存在的文件，不存在的不加入结果。

    这些路径后续由 main_window 用 QPalette.setBrush() 设置为控件背景。
    为什么不用 QSS 的 border-image？
        因为 QPalette 的方式可以"纯色打底 + 图片叠加"，而 QSS 的 border-image
        会直接替换背景，纯色打底就没了。两者结合使用可以达到"半透明纹理叠加
        纯色背景"的效果。

    参数:
        images    — [assets.images] 字典
        theme_dir — 主题文件夹路径（用于定位 assets/）

    返回:
        {selector: file_path}，如 {"#contentWidget": "C:/.../main_bg.png"}
    """
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
        selector = _IMAGE_SELECTORS.get(key)   # 把 key 转为 QSS 选择器
        if selector:
            result[selector] = str(file_path)
    return result
