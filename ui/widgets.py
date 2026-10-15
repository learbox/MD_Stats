"""通用控件 — 跨界面复用的自定义控件 + 应用级样式修正。

本模块有两部分：

    1. ThemedComboBox / ThemedFontComboBox —— 下拉箭头自绘的组合框。
       各界面（主窗口表格编辑器、设置对话框、段位统计对话框）统一用它们
       替代裸 QComboBox / QFontComboBox。

    2. ComboDropdownStyle —— 应用级 QProxyStyle，把组合框弹出列表从
       "菜单式定位"改回"向下展开"（在 main.py 里安装）。

================================================================================
为什么需要自绘箭头？
================================================================================

Windows 平台上，QComboBox 一旦被 QSS 样式化（本项目所有主题都是），Qt 就
**完全不再绘制下拉箭头**。要恢复箭头只有几条路，实测（2026-10-16）结论：

    1. 删掉 style.qss 里 QComboBox::drop-down 规则，让系统样式画原生箭头
       → 箭头回来了，但右下角同时出现一条 QSS 消不掉的灰色 L 形边框伪影

    2. 用 QProxyStyle 拦截组合框的绘制
       → 接不到：无样式的组合框能收到 drawComplexControl，被 QSS 样式化的
         组合框 Qt 根本不走那条路（只发一个 PE_IndicatorArrowDown 原语，
         外框由样式表内部绘制）→ 没有介入点

    3. 给 QComboBox::down-arrow 提供 image: url(...)
       → 可行，但必须准备图片文件（运行时生成会往 %TEMP% 写文件）

    4. 组合框自己在 paintEvent 里画（本模块采用的方案）
       → 纯矢量、零图片文件、零伪影、颜色随主题，且对可编辑/不可编辑、
         表格内编辑器组合框一律生效

================================================================================
使用方式
================================================================================

    from ui.widgets import ThemedComboBox, ThemedFontComboBox

    combo = ThemedComboBox(parent)      # 其余用法与 QComboBox 完全一致
    font  = ThemedFontComboBox()        # 其余用法与 QFontComboBox 完全一致

注意：Qt 自带的 QComboBox 子类（如 QFontComboBox）**不会**自动获得箭头，
      需要用它对应的 Themed 版本。
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPalette, QPolygonF
from PySide6.QtWidgets import QComboBox, QFontComboBox, QProxyStyle, QStyle


def _draw_arrow(widget: QComboBox) -> None:
    """在控件右侧的下拉区域中央画一个实心三角（抗锯齿）。

    颜色取控件调色板的 WindowText —— ThemeManager 把主题的 text_primary 设进了
    应用调色板，所以箭头自动跟随主题，禁用状态下也会自动变淡（Disabled 颜色组）。

    QFontComboBox 是 QComboBox 的子类，所以两种控件共用这一个绘制函数。
    """
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)   # 抗锯齿，斜边不发毛刺
    painter.setPen(Qt.PenStyle.NoPen)                          # 只填充，不描边
    painter.setBrush(widget.palette().color(QPalette.ColorRole.WindowText))

    cx = widget.width() - _DROP_DOWN_W / 2.0       # 下拉区域中心
    cy = widget.height() / 2.0
    left = cx - _ARROW_W / 2.0
    top = cy - _ARROW_H / 2.0
    painter.drawPolygon(QPolygonF([
        QPointF(left, top),                        # 左上
        QPointF(left + _ARROW_W, top),             # 右上
        QPointF(cx, top + _ARROW_H),               # 下方尖角
    ]))
    painter.end()


# 箭头三角的宽高（像素）
_ARROW_W = 9
_ARROW_H = 6
# 右侧下拉区域的宽度，与 style.qss 中 `QComboBox::drop-down { width: 20px; }` 保持一致
_DROP_DOWN_W = 20


class ThemedComboBox(QComboBox):
    """下拉箭头自绘的组合框（QComboBox 的完全替代品）。"""

    def paintEvent(self, event) -> None:
        """先让样式表画好本体（背景/边框/文字），再在右端补画箭头。"""
        super().paintEvent(event)     # 样式表/系统绘制：背景、边框、文字、弹出列表
        _draw_arrow(self)


class ThemedFontComboBox(QFontComboBox):
    """下拉箭头自绘的字体选择框（QFontComboBox 的完全替代品）。

    单列一个类是因为 QFontComboBox 虽也是 QComboBox 的子类，但 Qt 不会给它画
    箭头（原因见模块开头的说明），而它的字体列表/字体预览功能又不可替代。
    """

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        _draw_arrow(self)


# =============================================================================
# ComboDropdownStyle — 让下拉列表"向下展开"而不是"像菜单一样对齐当前项"
# =============================================================================

class ComboDropdownStyle(QProxyStyle):
    """应用级样式修正：组合框弹出列表固定向下展开。

    问题（2026-10-16 定位）:
        Qt 的 Fusion 样式对 SH_ComboBox_Popup 返回 1，含义是"组合框弹出列表按
        菜单来定位"——Qt 会把**当前选中项对齐到组合框**上。于是当前值是列表
        最后一项时（先后攻=后攻 / 赢硬币=否 / 结果=负 / 段位升降=降段），整个
        列表会翻到组合框**上方**；当前值是第一项时才在下方。在记录表格里逐行
        双击编辑时，看起来就是"下拉列表乱跳"。

        注意这是 Qt 的样式行为，不是表格或委托的问题：只有设置了 Fusion 才会
        出现（系统默认样式 windows11 返回 0，永远向下）。

    修法:
        把该 styleHint 强制返回 0 → Qt 用普通"下拉列表"定位：列表固定在组合框
        正下方展开，当前项只在列表内部高亮。其余绘制/度量全部转发给基础样式，
        外观不受影响；SH_ComboBox_Popup 也只有 QComboBox 在用。

    用法（main.py）:
        app.setStyle(ComboDropdownStyle("Fusion"))
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0        # 0 = 普通下拉列表（向下展开）；1 = 菜单式（对齐当前项）
        return super().styleHint(hint, option, widget, returnData)
