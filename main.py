"""MD Stats — 基于图像识别的 Master Duel 对局自动统计工具。

================================================================================
程序入口文件
================================================================================

功能概述:
    本程序通过定时截取 Master Duel 游戏窗口，使用 OpenCV 模板匹配技术
    自动识别对局的三阶段信息：
        阶段 1 — 硬币输赢（赢硬币 / 输硬币）
        阶段 2 — 先后攻（先攻 / 后攻）
        阶段 3 — 对局胜负（胜 / 负）

    识别结果持久化到 CSV 文件（支持按日期分文件），通过 GUI 界面展示
    统计表格和记录表格。支持手动录入、配置热加载、多分辨率模板切换。

启动方式:
    python main.py

依赖:
    - PySide6:     Qt 的 Python 绑定，提供 GUI 框架
    - opencv-python: 图像识别（模板匹配）
    - mss:         高性能屏幕截图（DirectX）
    - numpy:       数组/图像数据处理
    - pywin32:     窗口定位与客户区获取
"""


import sys

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main() -> None:
    """程序主入口：创建 Qt 应用并显示主窗口。

    执行流程:
        1. 创建 QApplication 实例（Qt 应用核心，管理事件循环）
        2. 设置 "Fusion" 风格，使 UI 在不同平台上外观一致
        3. 创建 MainWindow 主窗口并显示
        4. 进入 Qt 事件循环（app.exec()），等待用户操作
        5. 窗口关闭后事件循环退出，程序结束
    """
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
