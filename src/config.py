"""配置加载模块 — 从 config.toml 读取程序的所有可配置项。

================================================================================
配置文件结构 (config.toml)
================================================================================

    [detection]
    interval = 0.3              # 截图间隔（秒），推荐 0.3 ~ 1.0
    confidence_threshold = 0.8  # 模板匹配置信度阈值 (0.0~1.0)，推荐 0.75~0.90

    [window]
    width = 1300                # 主窗口宽度（像素）
    height = 700                # 主窗口高度（像素）

    [appearance]
    theme = "macaron"           # 界面主题，填 themes/ 下的文件夹名
                                # 内置: "dark"（暗色沉浸）、"light"（亮色清爽）、
                                #       "macaron"（马卡龙水彩）
                                # 自定义: 建 themes/my-theme/，填 "my-theme"

    [opponent_decks]
    presets = ["炎兽", "闪刀姬"]  # 对方卡组预设（记录表格下拉菜单选项）

    [recorder]
    daily_files = false           # 是否按日期分文件存储 CSV

    [clipboard]
    vertical_layout = false       # 竖排模式: true=key\\tvalue，false=横排 TSV
    scope = "all"                 # 复制范围: "current"=当前卡组, "all"=全部
    columns = []                  # 要复制的列名列表（空=全部 16 列）

    [floating_window]
    width = 250                   # 悬浮窗宽度（像素）
    height = 300                  # 悬浮窗高度（像素）
    bg_color = "#BDEF0A"          # 悬浮窗背景色（十六进制 RGB）
    opacity = 50                  # 不透明度 0-100（0=全透明, 100=不透明）
    font_size = 20                # 悬浮窗文字字号（像素）
    text_color = "#000000"        # 悬浮窗文字颜色
    font_family = "Microsoft YaHei"  # 悬浮窗字体（空则用全局字体）
    rows = []                     # 悬浮窗数据行（空=默认 8 行）

"""

import sys
from pathlib import Path
from typing import Any

import tomllib


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


def load_config() -> dict[str, Any]:
    """加载并解析 config.toml，返回嵌套字典。

    返回值示例:
        {
            "detection": {"interval": 0.3, "confidence_threshold": 0.8},
            "window": {"width": 1300, "height": 700},
            "appearance": {"theme": "macaron"},
            "opponent_decks": {"presets": ["炎兽", "闪刀姬", "烙印", "白银城"]},
            "recorder": {"daily_files": False},
            "clipboard": {
                "vertical_layout": False, "scope": "all", "columns": [],
            },
            "floating_window": {
                "width": 250, "height": 300,
                "bg_color": "#BDEF0A", "opacity": 50,
                "font_size": 20, "text_color": "#000000",
                "font_family": "Microsoft YaHei",
                "rows": [],
            },
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
