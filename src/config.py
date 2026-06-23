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
    columns = []                  # 要复制的列名列表（空=默认 8 项，和悬浮窗一致）

    [floating_window]
    use_theme_bg = false          # 是否使用主题背景图（false=纯色，方便 OBS 绿幕）
    width = 250                   # 悬浮窗宽度（像素）
    height = 300                  # 悬浮窗高度（像素）
    bg_color = "#BDEF0A"          # 悬浮窗背景色（十六进制 RGB）
    opacity = 50                  # 不透明度 0-100
    font_size = 20                # 悬浮窗文字字号（像素）
    text_color = "#000000"        # 悬浮窗文字颜色
    font_family = "Microsoft YaHei, -apple-system, sans-serif"
    rows = []                     # 悬浮窗数据行（空=默认 8 项）

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

    如果 config.toml 不存在，自动在当前目录生成一份默认配置文件，
    包含所有内置默认值，然后正常返回。程序不会因配置文件丢失而崩溃。

    返回值示例:
        {
            "detection": {"interval": 0.3, "confidence_threshold": 0.8},
            ...
        }

    注意事项:
        - TOML 文件必须以二进制模式 ("rb") 打开，这是 tomllib 的要求。
        - 返回值中所有值都是 Python 原生类型 (dict/list/str/int/float/bool)。
    """
    path = _get_config_path()
    if not path.exists():
        _generate_default_config(path)

    with open(path, "rb") as f:
        return tomllib.load(f)


def _generate_default_config(path: Path) -> None:
    """生成一份包含所有内置默认值的 config.toml。"""
    path.write_text("""\
# MD Stats 配置文件（由程序自动生成）
# 修改后点击主窗口的「设置 → 确定」即时生效。
# 所有时间单位为秒，所有颜色使用十六进制格式。

# 图像识别相关配置
[detection]
# 截图间隔（秒），推荐 0.3 ~ 1.0
interval = 0.3
# 匹配置信度阈值 (0.0~1.0)，推荐 0.75~0.90
confidence_threshold = 0.8

[window]
# 主窗口宽度（像素）
width = 1300
# 主窗口高度（像素）
height = 700

# 界面外观
[appearance]
# 主题文件夹名（内置: "dark" / "light" / "macaron"）
theme = "macaron"

# 对方卡组预设
[opponent_decks]
# 记录表格下拉菜单的预设选项
presets = ["闪刀姬", "烙印", "白银城", "k9vs"]

# 数据存储
[recorder]
# 是否按日期分文件存储 CSV
daily_files = false
# 启动时自动填入最近一次使用的卡组（从 CSV 读取）
remember_last_deck = true

# 统计表格显示
[stats]
# 统计表格显示的列名列表（空 = 全部显示）
columns = []

# 剪贴板复制行为
[clipboard]
# 竖排模式：true = 每行"key\\tvalue"，false = 横排 TSV
vertical_layout = true
# 复制范围："current" = 当前卡组，"all" = 全部卡组
scope = "all"
# 要复制的列名列表（空 = 默认 8 项）
columns = ["卡组", "对局数", "胜/负", "赢/输硬币", "赢硬币概率", "赢硬币胜率", "输硬币胜率", "综合胜率"]

# 调试与实验功能
[debug]
# 每次检测到关键事件（硬币/先后攻/胜负）时保存截图到 screenshots/
save_screenshots = false
# 下一局开始时自动清除上一局的截图
auto_clear_screenshots = true
# 启用截图热键（全局热键，游戏全屏时也可用）
hotkey_enabled = false
# 单次截图热键（优先截取 Master Duel 窗口）
snapshot_hotkey = "Ctrl+Shift+S"
# 周期截图热键（按一下开始，再按停止）
periodic_hotkey = "Ctrl+Shift+D"
# 周期截图间隔（秒）
periodic_interval = 0.5
# 开启日志模式：将运行信息写入 logs/ 目录
log_mode = false
# 日志记录范围："status"=状态栏消息, "screenshots"=截图事件, "errors"=错误信息
log_scope = ["status", "screenshots", "errors"]
# 状态栏显示置信度（段位图标 NCC、等级判读、三阶段检测分数）
show_confidence = false
# 识别失败时诊断截图（匹配度接近阈值但未达标时自动截图 + 诊断数据）
save_failure_samples = false
# 偏移量（值越大越容易触发，0 = 仅保存未达标帧的最高分）
failure_sample_offset = 0.10

# 系统通知
[notification]
# 对局结束时弹出系统气泡通知
enabled = false
# 通知显示持续时间（秒）
duration = 5
# 最小化时隐藏到系统托盘（而非任务栏）
minimize_to_tray = false
# OBS 捕获模式（悬浮窗显示任务栏图标以允许 OBS 捕获）
obs_mode = false

# 悬浮统计窗
[floating_window]
# 是否使用主题背景图（false = 纯色，方便 OBS 颜色键捕捉）
use_theme_bg = false
# 在悬浮窗底部显示检测状态（硬币/先后攻/胜负分数）
show_status = false
# 悬浮窗宽度（像素）
width = 250
# 悬浮窗高度（像素，实际低于内容高度时自动扩容）
height = 330
# 背景色
bg_color = "#bdef0a"
# 不透明度 0-100
opacity = 50
# 文字字号（像素）
font_size = 20
# 文字颜色
text_color = "#000000"
# 字体（Qt 从前往后找第一个可用的，含 macOS/Windows 回退）
font_family = "Microsoft YaHei UI"
# 显示数据行（空 = 默认 8 项）
rows = ["卡组", "对局数", "胜/负", "赢/输硬币", "赢硬币概率", "赢硬币胜率", "输硬币胜率", "综合胜率"]

# 段位图标检测
[rank_detection]
# 是否启用段位图标检测
enabled = true
# 截图间隔（秒），0.3 ~ 1.0
interval = 0.5
# 匹配置信度阈值 (0.0~1.0)
confidence_threshold = 0.7
""", encoding="utf-8")
