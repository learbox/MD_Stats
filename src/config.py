"""配置加载模块 — 从 config.toml 读取程序的所有可配置项。

================================================================================
配置文件结构 (config.toml)
================================================================================

    [detection]
    interval = 0.5              # 截图间隔（秒）
    confidence_threshold = 0.8  # 模板匹配置信度阈值

    [window]
    width = 1100                # 主窗口宽度（像素）
    height = 700                # 主窗口高度（像素）

    [appearance]
    theme = "dark"              # 界面主题: "dark" = 暗色沉浸, "light" = 亮色清爽

    [opponent_decks]
    presets = ["炎兽", "闪刀姬"]  # 对方卡组预设（下拉菜单选项）

    [recorder]
    daily_files = false           # 是否按日期分文件存储数据

================================================================================
TOML 解析
================================================================================

Python 3.11+ 内置了 tomllib 模块。对于更早的 Python 版本，
需要安装第三方库 tomli（pip install tomli），API 与 tomllib 完全兼容。
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 兼容 Python 3.10 及以下版本：优先使用标准库 tomllib，否则降级到 tomli
# ---------------------------------------------------------------------------
if sys.version_info >= (3, 11):
    import tomllib  # Python 3.11+ 内置
else:
    import tomli as tomllib  # type: ignore[import-not-found]


def get_project_root() -> Path:
    """获取项目根目录的绝对路径。

    开发模式: __file__ → src/config.py → 上两级 → 项目根目录
    打包模式 (sys.frozen): sys.executable → EXE 所在目录
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _get_config_path() -> Path:
    """获取 config.toml 的绝对路径。"""
    return get_project_root() / "config.toml"


def load_config() -> dict:
    """加载并解析 config.toml，返回嵌套字典。

    返回值示例:
        {
            "detection": {"interval": 0.5, "confidence_threshold": 0.8},
            "window": {"width": 1100, "height": 700},
            "appearance": {"theme": "dark"},
            "opponent_decks": {"presets": ["炎兽", "闪刀姬"]},
            "recorder": {"daily_files": False},
        }

    异常:
        FileNotFoundError: 如果项目根目录下不存在 config.toml 文件。

    注意事项:
        - TOML 文件必须以二进制模式 ("rb") 打开，这是 tomllib 的要求。
        - 返回值中所有值都是 Python 原生类型 (dict/list/str/int/float/bool)。
    """
    path = _get_config_path()
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, "rb") as f:
        return tomllib.load(f)
