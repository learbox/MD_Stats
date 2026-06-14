"""主题管理器 — 从 main_window.py 抽离的主题状态和控件着色逻辑。

================================================================================
这个模块做什么？

程序有三套内置主题（dark / light / macaron），用户也可以自定义主题。
主题切换时需要做很多事情：更新全局 QSS 样式、刷新表格背景色、重绘按钮颜色、
更新标题栏外观等。这些"把主题颜色应用到控件"的逻辑全部集中在这个模块中。

================================================================================
使用的 Qt 概念速查

QPalette  — Qt 的"调色板"，定义了一组颜色角色（如 Window 背景、Text 文字、Button 按钮）
            每个控件都会继承父控件的调色板来决定自己的颜色。QSS 覆盖不到的
            场景（如 QComboBox 弹出容器）会用到 QPalette。

QSS      — Qt Style Sheet，类似网页的 CSS。通过选择器 + 属性来设置控件外观。
            项目中的 style.qss 文件就是 QSS 代码，{{color.xxx}} 会被替换为实际颜色值。

QPixmap  — Qt 的"图片对象"，可以加载 .png 文件，然后设置到 QPalette 上作为背景纹理。

QColor   — Qt 的"颜色对象"，支持 #RRGGBB、rgba(r,g,b,a) 格式。

QBrush   — Qt 的"画刷"，用来填充区域。可以是纯色、渐变或纹理图片。

================================================================================
主题应用流程

加载阶段：
    1. ThemeManager.load(theme_name) — 读取主题文件，缓存颜色/图片/标题栏配置
    2. MainWindow.setStyleSheet(theme.qss) — 应用全局 QSS
    3. ThemeManager.apply_app_palette() — 设置 QApplication 级别的 QPalette
    4. ThemeManager.apply_to_widgets() — 逐个控件涂色 + 刷新表格 + 更新按钮

运行时切换（用户点击「重新载入配置」）：
    重复上述 1-4 步，额外需要先清空旧主题遗留的 stylesheet 和 QPalette
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QBoxLayout, QFrame, QHBoxLayout, QPushButton, QTableWidget, QToolButton, QWidget

from src.theme_loader import Theme, load_theme
from ui.titlebar import TitleBar


# =============================================================================
# ThemeWidgets — 控件引用容器
# =============================================================================

@dataclass
class ThemeWidgets:
    """MainWindow 中 ThemeManager 需要访问的控件引用集合。

    为什么需要这个容器？
        ThemeManager 的方法需要操作 MainWindow 里的各种控件（表格、按钮、
        标题栏等）。如果直接传 MainWindow 对象，ThemeManager 就需要访问
        MainWindow 的 protected 成员（以 _ 开头的属性），IDE 会报警告。

    解决方案：
        MainWindow 初始化时把所有 ThemeManager 需要的控件收集到这个容器里，
        ThemeManager 只接收 ThemeWidgets，不再接触 MainWindow。
        这样每个模块的职责清晰：MainWindow 管布局，ThemeManager 管配色。

    每个字段的含义：
        stats_table  / record_table     — 统计表格和记录表格（QTableWidget）
        btn_start / btn_stop / btn_delete_last — 启动/停止/删除最后按钮
        title_bar                       — 自定义标题栏
        status_frame                    — 底部状态栏容器（QFrame#customStatusBar）
        content                         — 窗口主区域（#contentWidget）
        refresh_stats_table             — MainWindow 的刷新统计表格方法
        refresh_record_table            — MainWindow 的刷新记录表格方法
        update_manual_buttons           — MainWindow 的更新手动按钮颜色方法
    """
    stats_table: QTableWidget
    record_table: QTableWidget
    btn_start: QPushButton
    btn_stop: QPushButton
    btn_delete_last: QToolButton
    btn_reload: QToolButton
    title_bar: TitleBar
    status_frame: QFrame
    content: QWidget
    refresh_stats_table: Callable[[], None]
    refresh_record_table: Callable[[], None]
    update_manual_buttons: Callable[[], None]


# =============================================================================
# ThemeManager — 主题状态管理 + 控件着色
# =============================================================================

class ThemeManager:
    """主题状态和控件着色管理。

    保存当前主题的颜色表、图片路径、标题栏配置，
    并提供一系列方法把这些配置实际应用到 Qt 控件上。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化 ThemeManager。

        参数:
            config — 从 config.toml 加载的完整配置字典
        """
        self._config = config                       # 程序配置（用于读取当前主题名等）
        self.colors: dict[str, str] = {}            # 当前主题的颜色表（key → #RRGGBB）
        self.pixmap_paths: dict[str, str] = {}      # 当前主题的图片路径（QSS选择器 → 文件路径）
        self.titlebar_cfg: dict[str, Any] = {}      # 当前主题的标题栏配置
        self.assets_dir: Path | None = None         # 当前主题的 assets 文件夹路径

    # =========================================================================
    # 主题加载
    # =========================================================================

    def load(self, theme_name: str) -> Theme:
        """加载指定主题并更新内部状态。

        调用流程：
            1. 传入主题名（如 "dark"、"macaron"）
            2. theme_loader.load_theme() 读取 themes/{name}/ 下的文件
            3. 解析出 colors、pixmaps、titlebar 配置
            4. 缓存到 self 的属性中

        返回 Theme 对象，MainWindow 用它来设置全局 QSS 样式表。

        参数:
            theme_name — themes/ 下的文件夹名
        """
        theme = load_theme(theme_name)
        self.colors = theme.colors
        self.pixmap_paths = theme.pixmaps
        self.titlebar_cfg = theme.titlebar
        self.assets_dir = theme.assets_dir
        return theme

    # =========================================================================
    # 全局 QPalette
    # =========================================================================

    def apply_app_palette(self) -> None:
        """根据当前主题颜色设置 QApplication 级别的全局调色板。

        为什么需要这个？
            QSS（Qt Style Sheet）能覆盖大部分控件的颜色，但有些场景 QSS 管不到。
            比如 QComboBox 点击后弹出的下拉列表是一个独立的顶层小窗口，
            它的背景色来自 QApplication 的 QPalette，而不是 QSS。
            如果不设置全局 QPalette，dark 主题下弹出列表的容器就是白色（系统默认），
            和黑色下拉选项形成刺眼的白条。

        工作原理：
            QPalette 定义了一系列"颜色角色"（ColorRole），每个角色代表一种用途：
            - Window      → 窗口/容器背景色
            - Base        → 输入框/表格/列表的背景色
            - WindowText  → 窗口文字颜色
            - Text        → 输入框文字颜色
            - Button      → 按钮背景色
            - ButtonText  → 按钮文字颜色
            - Highlight   → 选中项背景色
            - HighlightedText → 选中项文字颜色
            - ToolTipBase → 提示框背景色
            - ToolTipText → 提示框文字颜色

            每个角色又分为三个"颜色组"（ColorGroup）：
            - Active    — 窗口处于激活状态时的颜色
            - Inactive  — 窗口处于非激活状态时的颜色
            - Disabled  — 控件被禁用时的颜色

        实现细节：
            1. 从当前主题的 colors 字典中取 widget_bg、text_primary 等 key 的值
            2. 用 QColor 把这些十六进制字符串转为颜色对象
            3. 创建一个 QPalette，设置各个颜色角色
            4. 通过 QApplication.setPalette() 设为全局调色板
        """
        # QApplication.instance() 返回当前程序唯一的 QApplication 实例
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return  # 防御性检查，理论上不会走到这里

        c = self.colors

        # 用主题颜色创建 QColor 对象，key 不存在时用默认值兜底
        pal = QPalette()                                    # 新建一个空调色板
        base = QColor(c.get("widget_bg", "#ffffff"))        # 控件背景色
        text = QColor(c.get("text_primary", "#000000"))     # 正文颜色
        window = QColor(c.get("main_bg", "#ffffff"))        # 窗口背景色
        highlight = QColor(c.get("selection_bg", "#3080e0"))# 选中高亮色
        disabled_text = QColor(c.get("text_disabled", "#999999"))  # 禁用文字色

        # 批量设置每个颜色角色（Active 和 Inactive 用相同颜色，简化处理）
        role_map: list[tuple[QPalette.ColorRole, QColor]] = [
            (QPalette.ColorRole.Window, window),
            (QPalette.ColorRole.Base, base),
            (QPalette.ColorRole.WindowText, text),
            (QPalette.ColorRole.Text, text),
            (QPalette.ColorRole.Button, base),
            (QPalette.ColorRole.ButtonText, text),
            (QPalette.ColorRole.Highlight, highlight),
            (QPalette.ColorRole.HighlightedText, text),
            (QPalette.ColorRole.ToolTipBase, base),
            (QPalette.ColorRole.ToolTipText, text),
        ]
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            for role, color in role_map:
                pal.setColor(group, role, color)

        # Disabled 组例外：文字颜色用 disabled_text，其他角色保持 Active 的值不变
        for role in (QPalette.ColorRole.WindowText,
                     QPalette.ColorRole.Text,
                     QPalette.ColorRole.ButtonText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, disabled_text)

        app.setPalette(pal)  # 设为全局调色板，所有控件都会继承

    # =========================================================================
    # 控件着色方法
    # =========================================================================

    def apply_to_widgets(self, w: ThemeWidgets) -> None:
        """将已加载的主题完整应用到所有控件。

        这是主题应用的"总入口"，在初始化和主题切换时都会调用。
        执行顺序：
            1. wrap_layouts      — 纯色主题不需要（已由 .ui 文件提供 QFrame），有图主题补充
            2. apply_table_viewport_palette — 表格区域背景色
            3. apply_static_button_palette  — 停止/删除按钮颜色
            4. 刷新统计表格、记录表格、手动按钮的文字
            5. 设置启动按钮的特殊样式
            6. 更新标题栏文字和外观
        """
        self.wrap_layouts(w)
        self.apply_table_viewport_palette(w)
        self.apply_static_button_palette(w)
        w.refresh_stats_table()
        w.refresh_record_table()
        w.update_manual_buttons()
        w.btn_start.setStyleSheet(
            self.make_button_style(
                self.colors["start_bg"], padding="6px 20px"  # 启动按钮稍大
            )
        )
        w.title_bar.set_title("MD Stats")
        w.title_bar.reload_style(self.titlebar_cfg, self.assets_dir)

    def do_apply_pixmaps(self, w: ThemeWidgets) -> None:
        """首次显示窗口时，用 QPalette 贴背景图片。

        为什么在 showEvent 时调用？
            QPixmap 的缩放需要知道控件的实际尺寸，而控件在 __init__ 阶段
            还没有最终尺寸（窗口尚未显示）。showEvent 是窗口第一次显示时
            的时机，此时控件尺寸已经确定，可以正确缩放图片。

        处理逻辑：
            1. 先把 content 和 status_frame 的背景色设为纯色打底
            2. 遍历主题的图片资源，按选择器匹配控件：
               - #contentWidget   → 主窗口全幅背景
               - #customStatusBar → 状态栏背景
               - QTableWidget     → 表格背景（只设置 viewport，因为全局 QSS
                                    已经用 border-image 处理了表头拉伸）
        """
        main_bg = self.colors.get("main_bg", "#f5f6fa")
        status_bg = self.colors.get("statusbar_bg", "#ecf0f1")

        # 先用纯色打底（防止图片加载失败时透明）
        self.set_palette_bg(w.status_frame, None, status_bg)
        self.set_palette_bg(w.content, None, main_bg)

        # 遍历所有图片资源，把存在的图片贴到对应控件上
        for selector, path in self.pixmap_paths.items():
            pm = QPixmap(path)          # 加载图片
            if pm.isNull():             # 图片文件损坏或不存在
                continue
            if selector == "#contentWidget":
                self.set_palette_bg(w.content, pm, main_bg)
            elif selector == "#customStatusBar":
                self.set_palette_bg(w.status_frame, pm, status_bg)
            elif selector == "QTableWidget":
                # 表格背景只设 viewport（表格的可视区域），
                # 表头的 border-image 由全局 QSS 处理
                for table in (w.stats_table, w.record_table):
                    table.viewport().setStyleSheet(
                        f"border-image: url({path}) 0 0 0 0 stretch stretch;"
                        f"background-color: transparent;"
                    )
            elif selector == "QHeaderView::section":
                pass  # 表头背景由全局 QSS 的 border-image 处理拉伸
            elif selector == "QHeaderView::section:vertical":
                pass  # 同上

    def apply_static_button_palette(self, w: ThemeWidgets) -> None:
        """给 QToolButton 控件设置样式。

        btn_delete_last 使用 lose（红色系），btn_reload 使用默认按钮色。
        所有 QToolButton 都不受全局 QSS 的 QPushButton 选择器影响，
        因此所有主题下都需要用 make_button_style 手动设样式，
        并追加 ::menu-button 子控件样式以消除 Qt 默认的直角分隔外观。

        btn_stop 仍是 QPushButton，处理方式不变。
        """
        c = self.colors
        lose_color = c.get("lose", "#f0a5b5")
        if self.pixmap_paths and self.pixmap_paths.get("QPushButton"):
            # 有按钮纹理（macaron）：用实色覆盖水彩纹理
            w.btn_stop.setStyleSheet(
                self.make_button_style(lose_color)
            )
            # macaron hover 提亮 12%
            lose_hover = self.lighter_color(lose_color, 0.12)
        else:
            # 没有按钮纹理（dark/light）：清空局部样式，让全局 QSS 生效
            w.btn_stop.setStyleSheet("")
            # dark/light hover 提亮 25%
            lose_hover = self.lighter_color(lose_color)

        # btn_delete_last — 红色 QToolButton
        w.btn_delete_last.setStyleSheet(
            self.make_button_style(lose_color, selector="QToolButton",
                                   padding="5px 20px 5px 14px")
            + self._make_toolbutton_menu_style(lose_color, lose_hover)
        )

        # btn_reload — 默认按钮色 QToolButton
        btn_bg = c.get("button_bg", "#ffffff")
        btn_border = c.get("button_border", "#dcdde1")
        # 文字颜色使用 text_primary，与 QPushButton 保持一致，
        # 而非 readable_text_color() 自动计算的深色
        btn_text = c.get("text_primary")
        if self.pixmap_paths and self.pixmap_paths.get("QPushButton"):
            reload_hover = self.lighter_color(btn_bg, 0.12)
        else:
            reload_hover = self.lighter_color(btn_bg)
        w.btn_reload.setStyleSheet(
            self.make_button_style(btn_bg, selector="QToolButton",
                                   padding="5px 20px 5px 14px",
                                   border_override=btn_border,
                                   text_color_override=btn_text,
                                   font_weight="normal")
            + self._make_toolbutton_menu_style(btn_bg, reload_hover)
        )

    def apply_table_viewport_palette(self, w: ThemeWidgets) -> None:
        """设置表格区域的背景色。

        Qt 的 QTableWidget 有一个特殊架构：
            QTableWidget（整体）
              ├── viewport()       — 表格数据区域（单元格可见部分）
              ├── horizontalHeader() — 列表头
              └── verticalHeader()   — 行表头（行号列）

        这三个组件各有自己的 QPalette，需要分别设置。如果不处理 viewport
        的 palette，即使 QSS 设置了背景色，也可能被 palette 的默认颜色覆盖。

        处理流程：
            1. 先清空旧主题遗留的 stylesheet 和 QPalette（设为透明）
            2. 如果有图片资源（macaron 主题），贴图
            3. 如果是纯色主题（dark/light），用纯色填充
        """
        # ---- 第 1 步：清空旧主题遗留 ----
        # 用 QColor(0,0,0,0) 即透明的 RGBA 色，清除之前主题的调色板残留
        for table in (w.stats_table, w.record_table):
            for vw in (table.viewport(), table.verticalHeader(),
                       table.horizontalHeader()):
                vw.setStyleSheet("")                     # 清空局部 QSS
                vw.setAutoFillBackground(False)          # 关闭自动填充
                p = vw.palette()
                p.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
                p.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
                p.setBrush(QPalette.ColorRole.Window, QBrush())  # 清空画刷
                p.setBrush(QPalette.ColorRole.Base, QBrush())
                vw.setPalette(p)

        # ---- 第 2 步：有图片资源 → 贴图 ----
        if self.pixmap_paths:
            table_path = self.pixmap_paths.get("QTableWidget")
            for table in (w.stats_table, w.record_table):
                if table_path:
                    # border-image 会沿图片边缘向内切 0px，然后拉伸填充整个区域
                    table.viewport().setStyleSheet(
                        f"border-image: url({table_path}) 0 0 0 0 stretch stretch;"
                        f"background-color: transparent;"
                    )
            return  # 有图片就不走下面的纯色逻辑

        # ---- 第 3 步：纯色主题 → 涂色 ----
        base = self.colors.get("widget_bg", "#ffffff")        # 表格主体背景色
        header_bg = self.colors.get("main_bg", "#f5f6fa")     # 表头背景色
        theme = self._config.get("appearance", {}).get("theme", "dark")
        if theme != "dark":
            # dark 主题的表头用 main_bg 就够暗了，不需要额外区分
            # 非 dark 主题用 statusbar_bg 让表头和表格主体有视觉层次
            header_bg = self.colors.get("statusbar_bg", header_bg)

        for table in (w.stats_table, w.record_table):
            # viewport（数据区域）
            vp = table.viewport()
            self.set_palette_bg(vp, None, base)
            vp.setStyleSheet(f"background-color: {base};")

            # verticalHeader（行号栏）
            vh = table.verticalHeader()
            self.set_palette_bg(vh, None, header_bg)
            vh.setStyleSheet(f"background-color: {header_bg};")

            # horizontalHeader（列标题栏）
            hh = table.horizontalHeader()
            self.set_palette_bg(hh, None, header_bg)
            hh.setStyleSheet(f"background-color: {header_bg};")

    def wrap_layouts(self, w: ThemeWidgets) -> None:
        """把 ctrlLayout 和 bottomLayout 包进 QFrame，方便 QSS 贴 panel_bg。

        背景说明：
            在 .ui 文件中，topPanel 和 bottomPanel 已经是 QFrame（包裹了
            ctrlLayout 和 bottomLayout）。但为了兼容旧版 .ui 文件，这个方法
            会检查 QFrame 是否已存在，如果已存在则跳过；如果不存在则动态创建。

        实际场景：
            新的 main_window.ui 已经内嵌了 QFrame，所以这个方法现在实际上
            是一个空操作。保留它是为了向后兼容：如果用户用旧版 .ui 文件替换，
            程序仍然能正常工作。
        """
        if not self.pixmap_paths:
            return  # 纯色主题不需要 QFrame 包裹（panel_bg 是纯色，不需要贴图）
        content = w.content
        root_layout = content.layout()
        if not isinstance(root_layout, QBoxLayout):
            return

        for layout_name, frame_name in (("ctrlLayout", "topPanel"),
                                         ("bottomLayout", "bottomPanel")):
            # 如果 QFrame 已经在 .ui 文件中存在，跳过
            if content.findChild(QFrame, frame_name) is not None:
                continue

            # 找到需要包裹的布局
            layout = content.findChild(QHBoxLayout, layout_name)
            if layout is None:
                continue

            # 在 rootLayout 中找到这个布局的索引位置
            idx = -1
            for i in range(root_layout.count()):
                item = root_layout.itemAt(i)
                if item is not None and item.layout() is layout:
                    idx = i
                    break
            if idx < 0:
                continue

            # 从 rootLayout 中取出布局，放进新的 QFrame，再放回 rootLayout
            root_layout.takeAt(idx)
            frame = QFrame(content)
            frame.setObjectName(frame_name)
            frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            frame.setLayout(layout)
            layout.setContentsMargins(14, 6, 14, 6)
            root_layout.insertWidget(idx, frame)

    # =========================================================================
    # 按钮样式生成器
    # =========================================================================

    def make_button_style(self, bg: str, *,
                          padding: str = "4px 14px",
                          selector: str = "QPushButton",
                          border_override: str | None = None,
                          text_color_override: str | None = None,
                          font_weight: str = "bold") -> str:
        """生成一个带 hover / pressed / disabled 效果的按钮 QSS 字符串。

        这个方法被 MainWindow 的 _btn_style 调用，用于动态生成手动按钮的样式。
        例如"赢硬币"阶段按钮是橙色，"先攻"阶段是蓝色，"胜"阶段是绿色。

        根据主题是否有按钮纹理，生成两种不同的 QSS：

        A) 有按钮纹理（macaron 主题）
           问题：macaron 的 button_bg 是一张水彩纹理图（button_texture.png），
                全局 QSS 会把这张图设为按钮背景。如果手动按钮只需要一个纯色
                （如绿色=胜），全局 watercolor 纹理仍然在最底层，导致按钮
                只露出边框那一圈颜色。

           解决：用 CSS 的 background 简写属性（而不是 background-color）。
                `background: #2ecc71;` 会一次性清除所有 background 子属性
                （包括 background-image），彻底覆盖水彩纹理。

        B) 没有按钮纹理（dark/light 主题）
           直接用 background-color 设纯色即可。

        参数:
            bg              — 按钮的纯色背景（如 "#27ae60"）
            padding         — QSS padding 值（如 "4px 14px"）
            selector        — QSS 类型选择器，默认 "QPushButton"；
                              QToolButton 等控件需传入对应类型名
            border_override — 边框颜色覆盖，默认 None（macaron 用背景色，
                              dark/light 用 border 色）。传入时强制使用此值。
            text_color_override — 文字颜色覆盖，默认 None（自动根据背景亮度
                              计算）。传入时强制使用此值（如 QToolButton 需
                              与 QPushButton 的 text_primary 保持一致时使用）。

        返回:
            完整的按钮样式字符串（包含 hover/pressed/disabled 伪状态）
        """
        # 检查是否有按钮纹理
        button_texture = (self.pixmap_paths.get("QPushButton")
                          if self.pixmap_paths else None)

        if button_texture:
            # ---- 情况 A：macaron 主题，用 background 简写覆盖纹理 ----
            text_color = text_color_override or self.readable_text_color(bg)  # 优先使用覆盖色
            hover_bg = self.lighter_color(bg, 0.12)            # 悬停时提亮 12%
            pressed_bg = self.darker_color(bg, 0.08)           # 按下时加深 8%
            border_disabled = self.colors.get("border_disabled", "#f5eef4")
            text_disabled = self.colors.get("text_disabled", "#d5ccd8")
            radius = self.colors.get("button_radius", "12")
            border_color = border_override if border_override else bg
            # 关键：用 `background:` 而不是 `background-color:` 来覆盖纹理
            return (
                f"{selector} {{ "
                f"background: {bg}; "                          # 简写，清除纹理
                f"color: {text_color}; font-weight: {font_weight}; "
                f"padding: {padding}; border-radius: {radius}px; "
                f"border: 1px solid {border_color}; "
                f"}} "
                f"{selector}:hover {{ "
                f"background: {hover_bg}; "
                f"border-color: {hover_bg}; "
                f"}} "
                f"{selector}:pressed {{ "
                f"background: {pressed_bg}; "
                f"border-color: {pressed_bg}; "
                f"}} "
                f"{selector}:disabled {{ "
                f"background: {self.colors.get('button_disabled_bg', 'rgba(245,238,244,220)')}; "
                f"color: {text_disabled}; "
                f"border-color: {border_disabled}; "
                f"}}"
            )

        # ---- 情况 B：dark/light 主题，用 background-color ----
        border = border_override if border_override else self.colors.get("border", "#dcdde1")
        hover_border = self.colors.get("border_hover", border)  # hover 边框色（独立于背景色）
        hover_bg = self.lighter_color(bg)                      # 提亮 25%
        text_color = text_color_override or self.readable_text_color(bg)  # 优先使用覆盖色
        disabled_bg = self.colors.get("button_disabled_bg", "#9E9E9E")
        disabled_color = self.colors.get("text_disabled", "#e0e0e0")
        disabled_border = self.colors.get("border_disabled", "#888")
        radius = self.colors.get("button_radius", "12")
        return (
            f"{selector} {{ background-color: {bg}; color: {text_color}; "
            f"font-weight: {font_weight}; padding: {padding}; border-radius: {radius}px; "
            f"border: 1px solid {border}; }}"
            f"{selector}:hover {{ background-color: {hover_bg}; "
            f"border-color: {hover_border}; }}"
            f"{selector}:disabled {{ background-color: {disabled_bg}; "
            f"color: {disabled_color}; border-color: {disabled_border}; }}"
        )

    def _make_toolbutton_menu_style(self, bg: str, hover_bg: str) -> str:
        """生成 QToolButton MenuButtonPopup 模式下 ::menu-button 子控件的 QSS。

        Qt 默认的 MenuButtonPopup 会把主按钮右侧裁成直角、给箭头区域画独立边框，
        视觉上和左侧主按钮割裂。此方法通过 QSS 覆盖默认绘制：
            - 箭头区域用实色背景 + 右侧圆角，遮住主按钮的右侧直角
            - 只保留一条细分隔线（border-left）区分两区域
            - hover 时背景色同步变化

        参数:
            bg       — 和主按钮相同的背景色
            hover_bg — hover 时提亮后的背景色

        返回:
            ::menu-button 子控件的 QSS 字符串
        """
        radius = self.colors.get("button_radius", "12")
        # 分隔线颜色：基于按钮文字色半透明化（浅色主题用黑色半透明，深色主题用白色半透明）
        text_color = self.colors.get("text_primary", "#ffffff")
        tc = QColor(text_color)
        separator = f"rgba({tc.red()},{tc.green()},{tc.blue()},80)"
        return (
            "QToolButton::menu-button {"
            "border: none;"
            f"border-left: 1px solid {separator};"
            f"background: {bg};"
            "width: 16px;"
            "margin: 1px 0px 1px 0px;"
            f"border-top-right-radius: {radius}px;"
            f"border-bottom-right-radius: {radius}px;"
            "}"
            "QToolButton::menu-button:hover {"
            f"background: {hover_bg};"
            "}"
        )

    # =========================================================================
    # 静态颜色工具
    # =========================================================================

    @staticmethod
    def set_palette_bg(widget, pm, fallback_color: str) -> None:
        """给控件设 QPalette 背景：有图片贴图片，没图片涂纯色。

        同时设置 Window 和 Base 两个颜色角色，确保 QAbstractScrollArea
        （如 QTableWidget 的 viewport）也能正确显示背景。

        参数:
            widget         — 要设置背景的控件
            pm             — QPixmap 图片对象（可为 None，None 时用纯色）
            fallback_color — 纯色兜底色（十六进制字符串，如 "#f5f6fa"）
        """
        # WA_StyledBackground 告诉 Qt："这个控件的背景会用 QSS 来画，
        # 请准备好接收 QSS 的样式"
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setAutoFillBackground(True)  # 允许自动填充背景
        p = widget.palette()

        if pm is not None and not pm.isNull():
            # 有图片：把图片缩放到控件大小，设为 Window 和 Base 的画刷
            scaled = pm.scaled(widget.size(),
                               Qt.AspectRatioMode.IgnoreAspectRatio,      # 不保持比例，填满
                               Qt.TransformationMode.SmoothTransformation) # 平滑缩放
            p.setBrush(p.ColorRole.Window, scaled)
            p.setBrush(p.ColorRole.Base, scaled)
        else:
            # 没图片：设纯色
            color = QColor(fallback_color)
            p.setColor(p.ColorRole.Window, color)
            p.setColor(p.ColorRole.Base, color)

        widget.setPalette(p)

    @staticmethod
    def _parse_hex(hex_color: str) -> tuple[int, int, int]:
        """将 #RRGGBB 格式的颜色字符串解析为 (r, g, b) 整数元组。

        例如 "#2ecc71" → (46, 204, 113)
        每个分量是 0-255 的整数。

        这是内部工具方法，所有颜色计算的基础。
        """
        return (
            int(hex_color[1:3], 16),   # 第 1-2 位 = 红色分量
            int(hex_color[3:5], 16),   # 第 3-4 位 = 绿色分量
            int(hex_color[5:7], 16),   # 第 5-6 位 = 蓝色分量
        )

    @classmethod
    def readable_text_color(cls, hex_color: str) -> str:
        """根据底色亮度自动选择易读的文字颜色。

        原理：
            用亮度公式（luma）计算底色的明暗程度。
                luma = 0.299×R + 0.587×G + 0.114×B
            人眼对绿色最敏感（系数0.587），蓝色最不敏感（系数0.114）。

            如果 luma > 170（底色偏亮）→ 用深色文字 "#4a3a52"
            如果 luma ≤ 170（底色偏暗）→ 用白色文字 "#ffffff"

        示例：
            readable_text_color("#ffffff") → "#4a3a52"（白底黑字）
            readable_text_color("#16213e") → "#ffffff"（深蓝底白字）
        """
        r, g, b = cls._parse_hex(hex_color)
        luma = (0.299 * r + 0.587 * g + 0.114 * b)
        return "#4a3a52" if luma > 170 else "#ffffff"

    @classmethod
    def _adjust_color(cls, hex_color: str, factor: float, darken: bool) -> str:
        """将颜色向黑或白方向调整。

        这是 lighter_color 和 darker_color 的公共实现。

        参数:
            hex_color — 原始颜色（#RRGGBB）
            factor    — 调整比例（0.0 ~ 1.0）
            darken    — True=加深（向黑色方向），False=提亮（向白色方向）

        算法：
            加深：每个分量乘以 (1 - factor)，结果向 0 靠近
                 例如 #808080 × 0.85 = #6d6d6d
            提亮：每个分量加上 剩余量×factor，结果向 255 靠近
                 例如 #808080 + (255-128)×0.25 = #a0a0a0

        示例：
            _adjust_color("#808080", 0.25, darken=False) → "#a0a0a0"（提亮 25%）
            _adjust_color("#808080", 0.15, darken=True)  → "#6d6d6d"（加深 15%）
        """
        r, g, b = cls._parse_hex(hex_color)
        if darken:
            r = max(0, int(r * (1 - factor)))
            g = max(0, int(g * (1 - factor)))
            b = max(0, int(b * (1 - factor)))
        else:
            r = min(255, int(r + (255 - r) * factor))
            g = min(255, int(g + (255 - g) * factor))
            b = min(255, int(b + (255 - b) * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    @classmethod
    def lighter_color(cls, hex_color: str, factor: float = 0.25) -> str:
        """将颜色向白色方向提亮。

        factor=1.0 时颜色变成纯白 #ffffff，factor=0.0 时颜色不变。

        用于生成按钮 hover 状态的背景色。
        """
        return cls._adjust_color(hex_color, factor, darken=False)

    @classmethod
    def darker_color(cls, hex_color: str, factor: float = 0.15) -> str:
        """将颜色向黑色方向加深。

        factor=1.0 时颜色变成纯黑 #000000，factor=0.0 时颜色不变。

        用于生成按钮 pressed 状态的背景色。
        """
        return cls._adjust_color(hex_color, factor, darken=True)
