"""段位图标资源管理 — 为 UI 表格提供段位图标的缩略图。

================================================================================
这个模块做了什么？

    游戏中有 8 个大段位（新手、青铜、白银、黄金、铂金、钻石、大师、巅峰），
    每个段位对应一个 PNG 图标文件（290×290 像素）。

    这个模块负责：
    1. 启动时把这 8 个 PNG 加载到内存
    2. 缩放到 22×22 像素（表格行高只有 28px，29 0 太大）
    3. 存到缓存字典里，后面每次绘制直接取，不用反复读磁盘
    4. 提供一个查询接口：给我 "铂金 I"，我返回铂金的图标

================================================================================
为什么图标文件要缩放？

    原始的段位图标是 290×290 的 RGBA PNG，用来做模板匹配识别的（detector.py）。
    但在 UI 表格里，行高只有 28 像素，如果画 290 像素的图会撑爆单元格。
    缩放成 22×22 刚好适配行高，留一点呼吸空间。

================================================================================
如果图标文件不存在怎么办？

    不会报错。init_rank_icons() 遇到缺失文件就跳过，缓存为空。
    后续 get_rank_icon() 查不到图标就返回 None，表格会退化显示纯文字。
    用户在 README 里看到的 "因版权原因图标需自行准备" 就是为这个场景准备的。

================================================================================
对外接口

    init_rank_icons(icon_size=22)
        预加载并缩放所有图标。必须在 QApplication 创建之后调用
        （因为 QPixmap 需要 Qt 初始化完成）。重复调用是安全的（幂等）。

    get_rank_icon("铂金 I") → QPixmap | None
        传入单元格文本，自动提取大段名查图标。找不到返回 None。

    KNOWN_TIERS
        所有已知大段名的列表，按从低到高排列。
        ["新手", "青铜", "白银", "黄金", "铂金", "钻石", "大师", "巅峰"]
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from src.config import get_project_root

# =============================================================================
# 段位名 → 图标文件名的映射表
#
# 键是中文段位名（和 CSV 里存的、屏幕上显示的一致）。
# 值是图标文件名的前缀，完整文件名是 "{前缀}_l.png"。
#
# 注意：巅峰的文件名前缀是 img_rateicon_01，和其他段位的
# img_rankicon_0X 命名规则不同。这是游戏资源包里的原始命名，
# 不是我们定的，只是如实记录。
# =============================================================================
_RANK_NAME_TO_PREFIX: dict[str, str] = {
    "新手": "img_rankicon_01",
    "青铜": "img_rankicon_02",
    "白银": "img_rankicon_03",
    "黄金": "img_rankicon_04",
    "铂金": "img_rankicon_05",
    "钻石": "img_rankicon_06",
    "大师": "img_rankicon_07",
    "巅峰": "img_rateicon_01",        # ← 注意前缀不同
}

# 从映射表的键生成大段名列表，方便其他地方遍历
KNOWN_TIERS: list[str] = list(_RANK_NAME_TO_PREFIX.keys())

# =============================================================================
# 模块级缓存变量
#
# _icon_cache: 段位名 → 缩放后的 QPixmap
#     QPixmap 是 Qt 里的"图片对象"，可以画到屏幕上。
#     缓存起来避免每次 paint 都重新读文件、重新缩放。
#
# _icon_size:  当前缓存的图标尺寸（像素）
# _initialized: 是否已经执行过 init_rank_icons()
#     用于防止重复初始化（幂等保护）。
# =============================================================================
_icon_cache: dict[str, QPixmap] = {}
_icon_size: int = 22
_initialized: bool = False


def init_rank_icons(icon_size: int = 22) -> None:
    """加载所有段位图标，缩放到指定尺寸，存入缓存。

    这个函数应该在程序启动时调用一次（MainWindow.__init__ 中）。
    之后 get_rank_icon() 直接从缓存取，不需要再读磁盘。

    幂等：如果已经用相同尺寸初始化过，再次调用会直接跳过，
    不会重复加载浪费内存。

    Args:
        icon_size: 图标缩放后的边长（像素）。表格行高 28px，
                   22px 刚好适配，留 3px 上下边距。
    """
    # 操作模块级变量，必须声明 global
    global _icon_cache, _icon_size, _initialized

    # 幂等检查：相同尺寸已经初始化过 → 跳过
    if _initialized and _icon_size == icon_size:
        return

    _icon_size = icon_size
    _icon_cache.clear()  # 清空旧缓存（如果有的话）

    # 图标文件所在的目录
    rankicons_dir = get_project_root() / "resource" / "templates" / "rankicons"

    # 遍历 8 个段位，逐个加载图标
    for rank_name, prefix in _RANK_NAME_TO_PREFIX.items():
        # 拼接完整路径，如 "resource/templates/rankicons/img_rankicon_01_l.png"
        path = rankicons_dir / f"{prefix}_l.png"

        if not path.exists():
            # 文件不存在 → 跳过这个段位（不报错，不崩溃）
            # 用户可能还没准备好图标文件（README 说需要自行提取）
            continue

        # QPixmap(str(path)) 从文件加载图片到内存
        pixmap = QPixmap(str(path))

        if pixmap.isNull():
            # 文件存在但损坏或格式不支持 → 跳过
            continue

        # 缩放到目标尺寸。KeepAspectRatio 保持宽高比不变形，
        # SmoothTransformation 用高质量算法缩放（比 FastTransformation 清晰）
        pixmap = pixmap.scaled(
            icon_size, icon_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # 存入缓存：段位名 → 缩放后的图标
        _icon_cache[rank_name] = pixmap

    # 标记已初始化（即使一个图标都没加载成功也标记，避免反复尝试）
    _initialized = True


def get_rank_icon(rank_text: str) -> QPixmap | None:
    """根据段位文本查找对应的图标。

    表格单元格里存储的是完整段位字符串，例如 "铂金 I"、"钻石 V"、"巅峰"。
    这个函数会自动从中提取大段名（"铂金"、"钻石"、"巅峰"），
    然后去缓存里找对应的图标。

    提取逻辑：
        1. 先精确匹配：整个文本是不是就是大段名？（如 "巅峰" 无等级数字）
        2. 再前缀匹配：文本是不是以某个大段名开头？（如 "铂金 I" 以 "铂金" 开头）

    Args:
        rank_text: 单元格中的段位文本，如 "铂金 I"、"钻石 V"、"巅峰"。

    Returns:
        缩放后的 QPixmap，如果找不到匹配的图标就返回 None。
        调用方收到 None 应该降级为纯文本显示。
    """
    # 空字符串或全是空格 → 没有段位数据
    if not rank_text or not rank_text.strip():
        return None

    rank_text = rank_text.strip()

    # 第 1 步：精确匹配（处理"巅峰"这种没有等级后缀的段位）
    if rank_text in _icon_cache:
        return _icon_cache[rank_text]

    # 第 2 步：前缀匹配（处理"铂金 I"、"钻石 V"这种带等级的段位）
    # 遍历所有已知大段名，检查文本是否以它开头
    for tier_name in KNOWN_TIERS:
        if rank_text.startswith(tier_name):
            # 找到了！用大段名去缓存取图标
            return _icon_cache.get(tier_name)

    # 既不是已知大段名，也不以已知大段名开头 → 查不到
    return None


def has_icons() -> bool:
    """检查是否至少加载了一个段位图标。

    如果返回 False，说明 icon 文件全部缺失或加载失败，
    此时 UI 应该全部降级为纯文本，不尝试绘制图标。
    """
    return len(_icon_cache) > 0
