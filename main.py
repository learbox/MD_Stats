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
from src import logger as _log
from ui.main_window import MainWindow


# =============================================================================
# 全局未捕获异常钩子
# =============================================================================
#
# Python 中未处理的异常默认走 sys.excepthook → 打印 traceback → 退出。
# 我们在这里插入一层自定义钩子，在默认行为之前先把异常信息写入日志文件。
#
# 能捕获什么？
#   主线程同步路径上的所有异常 — load_config() 的 FileNotFoundError、
#   capture.py 的错误、任何未被 try/except 处理的崩溃。
#
# 不能捕获什么？
#   QThread 子线程中的异常（Qt 只打印到 stderr，不触发 sys.excepthook）。
#   工作线程的异常由 StatsWorker.run() 中的独立 try/except 覆盖。
#
# 日志模式关闭时：
#   _log.write() 检测到日志未初始化，静默跳过，不产生任何副作用。
# =============================================================================


def _excepthook(exc_type, exc_value, exc_tb):
    """全局未捕获异常钩子：先写入日志，再调用默认处理（打印 traceback）。"""
    # 注意：如果日志尚未初始化（log_mode=false），_log.write() 会静默跳过
    _log.write("ERROR", f"{exc_type.__name__}: {exc_value}")
    # 回退到 Python 默认行为：打印 traceback 到 stderr
    sys.__excepthook__(exc_type, exc_value, exc_tb)


# 替换 Python 默认的异常钩子，必须在任何可能抛异常的代码之前设置
sys.excepthook = _excepthook


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
    _window = MainWindow()  # 必须存引用以防 GC 回收（窗口在 app.exec() 期间存活）
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
