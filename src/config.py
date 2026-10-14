"""配置加载模块 — 从 config.toml 读取程序的所有可配置项。

================================================================================
职责
================================================================================

    1. 读取与规范化：load_config() 解析 config.toml，逐层兜底——
       语法损坏（坏行逐行跳过 / 整体回退）→ 值级校验（超界 / 类型 / 布尔开关 / 热键）
       → 返回可直接使用的配置字典；磁盘文件在任何情况下不被程序改写。
    2. 生成与渲染：render_config_toml() 是配置文件的唯一渲染入口
       （首启生成 / CI 发布包 / 语法损坏兜底 / 设置界面保存共用），
       注释、段与键的顺序、默认值都来自 _CONFIG_LAYOUT 规格表；
       数值项的"允许范围"由 _RANGED_LIMITS 自动填充，不会与代码实际
       强制范围漂移（有测试兜底）。
    3. 警告收集：load_config(warnings=[...]) 会把"用户输入未被原样采用"
       的项收集起来（结构见 _sanitize_ranged 上方注释），供主窗口状态栏
       提示、点击弹窗明细与日志记录使用。

================================================================================
生成规则（写入 config.toml 的注释必须遵守）
================================================================================

    - 数值项：注释写明"允许 {range}"，由 _RANGED_LIMITS 渲染时自动填充
    - 布尔项：注释必须写出 true / false 两个取值（有测试保证）
    - 枚举 / 列表项：注释列出可选值，或说明空列表 [] 的含义

"""

import re
import sys
from pathlib import Path

import tomllib

from src.hotkey_parse import is_valid_hotkey


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


# 全部数值配置项的合法范围（键 = (配置段, 项名)；范围与设置界面对应滑块完全一致）。
#
# 手改 config.toml 可能写入各种非法值，读取时统一规范化：
#   - interval 类写 0/负数 → _sleep 不睡，忙循环烧 CPU
#   - 置信度类超界 → 匹配永远达不到阈值（识别全失效）或全量误报
#   - 尺寸/时长类超界 → UI 显示失实、各处理链路拿到意外值
#   - 非数值类型 → 工作线程 TypeError 退出
_RANGED_LIMITS: dict[tuple[str, str], tuple[float, float]] = {
    # 识别：对局事件检测
    ("recognition", "interval"): (0.1, 10.0),
    ("recognition", "confidence_threshold"): (0.0, 1.0),
    # 识别：段位图标检测
    ("recognition", "rank_interval"): (0.1, 2.0),
    ("recognition", "rank_confidence_threshold"): (0.5, 0.95),
    # 识别：调试设置
    ("recognition", "periodic_interval"): (0.1, 10.0),
    ("recognition", "failure_sample_offset"): (0.01, 0.50),
    # 系统
    ("system", "notification_duration"): (1, 30),
    # 外观：主窗口尺寸
    ("appearance", "window_width"): (400, 5000),
    ("appearance", "window_height"): (300, 5000),
    # 悬浮窗
    ("floating_window", "width"): (100, 1000),
    ("floating_window", "height"): (100, 1000),
    ("floating_window", "opacity"): (0, 100),
    ("floating_window", "font_size"): (8, 72),
}


# 配置警告条目（load_config 的 warnings 出参元素）:
#   {"section": "recognition", "key": "capture_backend",
#    "raw": "printfwindows", "action": "fallback", "used": "printwindow"}
#   raw    — 文件中写入的原始值（任意类型，供界面/日志展示）
#   action — 处理方式（二选一）:
#              "fallback" 值无法识别，按该项的固定默认值运行
#              "ignore"   值被忽略（类型无效或超出范围），改用内置默认值
#   used   — 实际采用的值；"ignore" 条目通常填规格表默认值（展示为
#            "已改用内置默认值 X"），规格表里没有该键时（自定义键的坏行）为 None
#   line   — 可选。语法错误被跳过的行号；file_error 条目为出错行
#
# 两类都意味着"用户的输入未被原样采用"，需要提示。


def _default_value(section: str, key: str):
    """取某项的内置默认值（规格表口径，见 _CONFIG_LAYOUT / render_config_toml）。

    用于警告条目展示"已改用内置默认值 X"；规格表里没有的键返回 None
    （调用方退回无具体数值的"已忽略"文案）。
    """
    return _load_default_config().get(section, {}).get(key)


def _sanitize_ranged(cfg: dict, warnings: list[dict] | None = None) -> None:
    """规范化表中各数值配置项（原地修改内存中的配置，不写回文件）。

    - 数值超出 [下限, 上限] → 删除该项（读取方使用内置默认值），
      记一条 "ignore" 警告。不做夹紧到边界：阈值类项的边界值不可用
      （置信度夹到 1.0 识别全失效、夹到 0.0 全量误报），
      统一回退出厂默认比"保留方向"更安全
    - 非数值类型（字符串/布尔等）→ 同样删除并记 "ignore" 警告

    Args:
        warnings: 可选。收集值被忽略的条目（结构见上方注释）。
    """
    for (section, key), (lo, hi) in _RANGED_LIMITS.items():
        sec = cfg.get(section)
        if not isinstance(sec, dict) or key not in sec:
            continue
        value = sec[key]
        # 合法值：数值类型且在范围内；其余一律删键 → 读侧 .get 兜底默认值
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and lo <= value <= hi):
            continue
        del sec[key]
        if warnings is not None:
            warnings.append({"section": section, "key": key,
                             "raw": value, "action": "ignore",
                             "used": _default_value(section, key)})


def _sanitize_flags(cfg: dict, warnings: list[dict] | None = None) -> None:
    """校验全部布尔开关项（原地修改内存中的配置，不写回文件）。

    布尔项清单直接从渲染规格 _CONFIG_LAYOUT 推导（默认值为 bool 的键），
    新增开关自动获得校验，不用维护第二份名单。

    危险场景：手改 config.toml 把开关写成非布尔值——
      - 字符串 "false"：非空字符串为真，功能会静默保持「开启」，
        与书写意图相反（最坑的一类）
      - 数字（如 100000）：语义混乱，设置界面 setChecked 行为不可预期
    统一按"值无法识别"处理：删键回退内置默认值，记一条 "ignore" 警告。

    Args:
        warnings: 可选。收集非布尔开关的条目（结构见 _sanitize_ranged 上方注释）。
    """
    for section, _title, entries in _CONFIG_LAYOUT:
        sec = cfg.get(section)
        if not isinstance(sec, dict):
            continue
        for key, _comment, default in entries:
            if not isinstance(default, bool) or key not in sec:
                continue
            value = sec[key]
            if isinstance(value, bool):
                continue
            del sec[key]
            if warnings is not None:
                warnings.append({"section": section, "key": key, "raw": value,
                                 "action": "ignore", "used": default})


# 合法的画面来源（与 capture.capture_window 的 backend 参数、设置界面下拉框一致）
_CAPTURE_BACKENDS = ("printwindow", "mss")


def _sanitize_capture_backend(cfg: dict, warnings: list[dict] | None = None) -> None:
    """规范化 recognition.capture_backend 值（原地修改内存中的配置，不写回文件）。

    手改 config.toml 可能写入非字符串或无法识别的值，
    统一回退到默认 "printwindow"，避免下层截图函数拿到意外值。
    大小写不敏感（写入统一小写形式，纯大小写差异不算警告）。

    Args:
        warnings: 可选。值无法识别时追加一条警告（结构见 _sanitize_ranged 上方注释）。
    """
    sec = cfg.get("recognition")
    if not isinstance(sec, dict) or "capture_backend" not in sec:
        return
    value = sec["capture_backend"]
    if isinstance(value, str) and value.lower() in _CAPTURE_BACKENDS:
        sec["capture_backend"] = value.lower()
    else:
        sec["capture_backend"] = "printwindow"
        if warnings is not None:
            warnings.append({"section": "recognition", "key": "capture_backend",
                             "raw": value, "action": "fallback",
                             "used": "printwindow"})


# 热键类配置项的默认值（与渲染规格 _CONFIG_LAYOUT 中的默认值一致，有测试校验）
_HOTKEY_DEFAULTS = {
    ("recognition", "snapshot_hotkey"): "Ctrl+Shift+S",
    ("recognition", "periodic_hotkey"): "Ctrl+Shift+D",
}


def _sanitize_hotkeys(cfg: dict, warnings: list[dict] | None = None) -> None:
    """校验 recognition 段两个热键字符串（原地修改内存中的配置，不写回文件）。

    非字符串、或解析不出主键的字符串（如 "123abc"、"Ctrl+Shift"）在注册时
    会被静默跳过——用户按键没反应且没有任何提示（见 snapshot_controller
    注册前的 `if vk:` 守卫），这里统一回退规格表默认值并记 "fallback" 警告。
    空字符串表示"不启用该热键"（注册时跳过），是既有合法行为，保持原样。

    Args:
        warnings: 可选。值无法识别时追加警告（结构见 _sanitize_ranged 上方注释）。
    """
    for (section, key), default in _HOTKEY_DEFAULTS.items():
        sec = cfg.get(section)
        if not isinstance(sec, dict) or key not in sec:
            continue
        value = sec[key]
        # 合法值：空串（不启用）或能解析出主键的字符串
        if isinstance(value, str) and (value == "" or is_valid_hotkey(value)):
            continue
        sec[key] = default
        if warnings is not None:
            warnings.append({"section": section, "key": key, "raw": value,
                             "action": "fallback", "used": default})


# ---------------------------------------------------------------------------
# 语法错误兜底：逐行跳过坏行（仅内存，不写回文件）
# ---------------------------------------------------------------------------
#
# 背景：tomllib 是 fail-fast 的——文件里只要有一处语法错误（如值忘了加
# 引号 "confidence_threshold = abc"），整个文件都解析不出来，而且它只报
# 第一处错误。所以"只跳过坏行、其余配置照常生效"要靠循环收敛：
# 报错 → 注释掉该行 → 重解析，直到通过。
#
# 只跳过"键值行"：表头等结构行不能靠注释修复——把 "[debug" 注释掉会让
# 它后面的键并入上一个表，产生"看似成功但配置错位"的结果（比崩溃更
# 危险），这类直接放弃行级修复、整体回退内置默认配置。

# 行级跳过的尝试上限（防御性——正常文件 1~2 处语法错误就该收敛）
_MAX_SYNTAX_REPAIRS = 20

# 行首是 [ 视为表头/结构行（见上方说明）
_STRUCTURAL_LINE_RE = re.compile(r"^\s*\[")
# 从 "key = ..." 行首提取键名
_KEY_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=")
# 旧版本 tomllib 无结构化行号时，从异常消息里回退提取
_POS_IN_MSG_RE = re.compile(r"\(at line (\d+), column \d+\)")
# 展示错误消息时去掉结尾的位置信息（行号已单独展示）
_TRAILING_POS_RE = re.compile(r"\s*\(at line \d+, column \d+\)\s*$")


def _toml_error_line(e: tomllib.TOMLDecodeError) -> int | None:
    """取 TOMLDecodeError 的行号（属性优先，旧版本回退解析消息文本）。"""
    lineno = getattr(e, "lineno", None)
    if isinstance(lineno, int):
        return lineno
    m = _POS_IN_MSG_RE.search(str(e))
    return int(m.group(1)) if m else None


def _locate_bad_line(orig_lines: list[str], lineno: int) -> tuple[str, str]:
    """定位坏行所属的表段与键名（提示展示用，尽力而为）。

    section 取该行往上最近的 [table] 头，找不到（顶层行）回退
    "config.toml"；key 从行首 "key =" 提取，提取不到返回空串。
    """
    section = "config.toml"
    for i in range(lineno - 1):
        stripped = orig_lines[i].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]").strip()
    m = _KEY_LINE_RE.match(orig_lines[lineno - 1])
    return section, (m.group(1) if m else "")


def _load_toml_with_repair(text: str, warnings: list[dict] | None) -> tuple[dict, bool]:
    """解析 TOML 文本；语法错误时逐行注释掉坏行重试（仅内存，不写回文件）。

    返回 (cfg, parsed_ok)：
        - 行级修复成功（或本就无错）→ (解析结果, True)，每个被跳过的坏行
          追加一条带行号的 "ignore" 警告；磁盘文件保持原样
        - 放弃行级修复 → (内置默认配置, False) 并追加一条 "file_error"
          警告。放弃的情形:
            * 错误行是表头等结构行（见文件上方说明，不能猜）
            * 取不到行号 / 行号越界 / 同一行反复报错（修复无进展）
            * 超过 _MAX_SYNTAX_REPAIRS 次仍未通过

    被跳过的键在后续读取时自然回退到内置默认值——与 _sanitize_ranged
    的 "ignore" 语义一致。
    """
    orig_lines = text.splitlines()          # 定位坏行用（不变）
    lines = text.splitlines(keepends=True)  # 修复用（可变）
    last_error: tomllib.TOMLDecodeError | None = None
    skipped: set[int] = set()
    for _ in range(_MAX_SYNTAX_REPAIRS):
        try:
            return tomllib.loads("".join(lines)), True
        except tomllib.TOMLDecodeError as e:
            last_error = e
            lineno = _toml_error_line(e)
            if (lineno is None or not 1 <= lineno <= len(lines)
                    or lineno in skipped
                    or _STRUCTURAL_LINE_RE.match(lines[lineno - 1])):
                break
            skipped.add(lineno)
            if warnings is not None:
                section, key = _locate_bad_line(orig_lines, lineno)
                warnings.append({"section": section, "key": key,
                                 "raw": orig_lines[lineno - 1].strip(),
                                 "action": "ignore",
                                 "used": _default_value(section, key),
                                 "line": lineno})
            lines[lineno - 1] = "# " + lines[lineno - 1]  # 内存中注释掉，重试

    # 行级修复失败 → 整体回退内置默认配置（不覆盖用户文件）
    if warnings is not None:
        lineno = _toml_error_line(last_error) if last_error is not None else None
        msg = str(last_error) if last_error is not None else "无法解析"
        warnings.append({"section": "config.toml", "key": "",
                         "raw": _TRAILING_POS_RE.sub("", msg),
                         "action": "file_error", "used": None, "line": lineno})
    return _load_default_config(), False


def load_config(warnings: list[dict] | None = None) -> dict:
    """加载并解析 config.toml，返回嵌套字典。

    如果 config.toml 不存在，自动在当前目录生成一份默认配置文件，
    包含所有内置默认值，然后正常返回。程序不会因配置文件丢失而崩溃；
    语法损坏（如值忘了加引号）也不会崩溃——坏行会被逐行跳过（仅内存），
    其余配置照常生效；修复不了时整体回退内置默认配置。磁盘文件在任何
    情况下都不会被程序改写。

    Args:
        warnings: 可选。传入列表时，"值无法识别/超界/语法损坏，已被修正或
            忽略"的配置项会以条目形式追加进去（结构见 _sanitize_ranged
            上方注释），供界面提示与日志记录；不传则只做规范化（识别线程
            等调用方无需关心）。

    返回值示例:
        {
            "recognition": {"interval": 0.3, "confidence_threshold": 0.8},
            ...
        }

    注意事项:
        - 文件按 UTF-8 文本读取（utf-8-sig，兼容 BOM），因为语法修复需要
          逐行处理文本；编码损坏（如被 GBK 编辑器保存）同样走整体兜底。
        - 返回值中所有值都是 Python 原生类型 (dict/list/str/int/float/bool)。
        - 数值项（各 interval、匹配阈值、窗口尺寸等）会经 _sanitize_ranged
          规范化，布尔开关会经 _sanitize_flags 校验（见两函数说明）。
    """
    path = _get_config_path()
    if not path.exists():
        generate_default_config(path)

    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # 编码损坏（如被 GBK 编辑器保存）→ 整体回退默认配置
        if warnings is not None:
            warnings.append({"section": "config.toml", "key": "",
                             "raw": "文件不是有效的 UTF-8 文本（编码损坏）",
                             "action": "file_error", "used": None, "line": None})
        return _load_default_config()

    cfg, parsed_ok = _load_toml_with_repair(text, warnings)
    if parsed_ok:
        # 语法层通过后，再做语义层规范化（值级兜底）
        _sanitize_ranged(cfg, warnings)
        _sanitize_flags(cfg, warnings)
        _sanitize_capture_backend(cfg, warnings)
        _sanitize_hotkeys(cfg, warnings)
    return cfg


# ---------------------------------------------------------------------------
# config.toml 渲染规格 —— 注释、段/键顺序、默认值的唯一来源
# ---------------------------------------------------------------------------
#
# 首启自动生成、CI 发布包、语法损坏兜底、设置界面保存全部调用
# render_config_toml() 渲染，保证各处生成的 config.toml 注释与段顺序
# 永远一致（此前"代码模板"与"设置界面保存"是两套注释，已经开始漂移）。
#
# 注释里的 "允许 {range}" 由 _RANGED_LIMITS 渲染时自动填充——读取侧强制
# 范围改了注释自动跟着变，结构性防止文档与代码脱节。写入要求见文件头
# 的"生成规则"。
#
# 结构: [(段名, 段标题注释（空字符串 = 该段不写标题）, [(键, 注释, 默认值), ...])]

_CONFIG_LAYOUT: list[tuple[str, str, list[tuple[str, str, object]]]] = [
    ("recognition", "识别", [
        ("capture_backend",
         '画面来源："printwindow" = 游戏窗口（默认，不受悬浮窗/其他窗口遮挡影响）\n'
         '          "mss" = 屏幕（兼容模式；被别的窗口盖住会截入遮挡物）',
         "printwindow"),
        ("interval",
         "对局事件检测间隔（秒），允许 {range}，推荐 0.3 ~ 1.0",
         0.3),
        ("confidence_threshold",
         "对局事件检测的匹配置信度阈值，允许 {range}，推荐 0.75 ~ 0.90",
         0.8),
        ("detection_sound",
         "对局事件提示音总开关（true / false）：关闭时硬币/先后攻/胜负三个音效全部静音",
         False),
        ("coin_sound",
         "识别到硬币结果时播放提示音（true / false；音效: resource/sounds/coin.wav）",
         False),
        ("turn_sound",
         "识别到先后攻时播放提示音（true / false；音效: resource/sounds/turn.wav）",
         False),
        ("result_sound",
         "识别到对局胜负时播放提示音（true / false；音效: resource/sounds/result.wav）",
         False),
        ("rank_enabled",
         "是否启用段位图标检测（true / false）",
         True),
        ("rank_interval",
         "段位图标检测间隔（秒），允许 {range}，推荐 0.3 ~ 1.0",
         0.3),
        ("rank_confidence_threshold",
         "段位图标匹配置信度阈值，允许 {range}，推荐 0.7",
         0.7),
        ("save_screenshots",
         "每次检测到对局事件（硬币/先后攻/胜负）时保存截图到 screenshots/（true / false）",
         False),
        ("auto_clear_screenshots",
         "下一局开始时自动清除上一局的截图（true / false）",
         False),
        ("save_failure_samples",
         "识别失败时诊断截图（匹配度接近阈值但未达标时自动截图 + 诊断数据；true / false）",
         False),
        ("failure_sample_offset",
         "触发偏移量，允许 {range}：记录下限 = 匹配阈值 − 偏移量，值越大越容易触发",
         0.2),
        ("hotkey_enabled",
         "启用截图热键（true / false）：全局热键，游戏全屏时也可用",
         False),
        ("snapshot_hotkey",
         '单次截图热键，格式"修饰键+主键"（如 "Ctrl+Shift+S"；'
         "修饰键 Ctrl/Shift/Alt/Win，主键 A-Z / 0-9 / F1-F12）",
         "Ctrl+Shift+S"),
        ("snapshot_sound",
         "单次截图的结果音效（true / false）：成功播提示音（resource/sounds/snapshot.wav），\n"
         "只要未成功（如窗口未找到、磁盘不可写）播警示音（resource/sounds/error.wav）",
         False),
        ("periodic_hotkey",
         '周期截图热键（按一下开始，再按停止；格式同单次截图热键，如 "Ctrl+Shift+D"）',
         "Ctrl+Shift+D"),
        ("periodic_interval",
         "周期截图间隔（秒），允许 {range}",
         0.5),
    ]),
    ("appearance", "外观", [
        ("theme",
         '主题文件夹名（"dark" / "light" / "macaron"，'
         '或 resource/themes/ 下的自定义主题文件夹名）',
         "macaron"),
        ("window_width", "主窗口宽度（像素），允许 {range}", 1300),
        ("window_height", "主窗口高度（像素），允许 {range}", 700),
    ]),
    ("clipboard", "剪贴板", [
        ("vertical_layout",
         '竖排模式：true = 每行"key\\tvalue"，false = 横排 TSV',
         False),
        ("scope", '复制范围："current" = 当前卡组，"all" = 全部卡组', "all"),
        ("columns",
         "要复制的列名列表（空列表 [] = 默认 8 项）",
         ["卡组", "对局数", "胜/负", "赢/输硬币", "赢硬币概率", "赢硬币胜率",
          "输硬币胜率", "综合胜率"]),
    ]),
    ("floating_window", "悬浮窗", [
        ("width", "悬浮窗宽度（像素），允许 {range}", 250),
        ("height",
         "悬浮窗高度（像素，实际低于内容高度时自动扩容），允许 {range}",
         330),
        ("bg_color", '背景色（十六进制 "#RRGGBB"，如 "#bdef0a"）', "#bdef0a"),
        ("opacity", "不透明度，允许 {range}（0 = 全透明，100 = 不透明）", 50),
        ("text_color", '文字颜色（十六进制 "#RRGGBB"，如 "#000000"）', "#000000"),
        ("font_size", "文字字号（像素），允许 {range}", 20),
        ("font_family",
         "字体（Qt 从前往后找第一个可用的，含 macOS/Windows 回退）",
         "Microsoft YaHei UI"),
        ("rows",
         "显示数据行（字符串列表，空列表 [] = 默认 8 项）",
         ["卡组", "对局数", "胜/负", "赢/输硬币", "赢硬币概率", "赢硬币胜率",
          "输硬币胜率", "综合胜率"]),
        ("use_theme_bg",
         "是否使用主题背景图：true = 主题背景图，false = 纯色（方便 OBS 颜色键捕捉）",
         False),
        ("show_status",
         "在悬浮窗底部显示当前的状态消息（程序运行状态、识别进度等；true / false）",
         False),
        ("show_status_compact",
         '简洁模式：true = 只显示"——"前面的部分，false = 显示完整消息（仅影响悬浮窗）',
         True),
    ]),
    ("data", "数据", [
        ("deck_presets",
         "记录表格下拉菜单的预设选项（字符串列表）",
         ["闪刀姬", "烙印", "k9vs", "杀手旋律", "绚岚", "烙印星宿", "纠罪巧"]),
        ("stats_columns",
         "统计表格显示的列名列表（空列表 [] = 全部显示）",
         ["卡组", "对局数", "胜", "负", "胜率", "赢硬币次数", "输硬币次数",
          "赢硬币概率", "赢硬币胜率", "输硬币胜率", "先攻次数", "后攻次数",
          "先攻胜", "后攻胜", "先攻胜率", "后攻胜率"]),
        ("daily_files", "是否按日期分文件存储 CSV（true / false）", False),
        ("remember_last_deck",
         "启动时自动填入最近一次使用的卡组（从 CSV 读取；true / false）",
         True),
    ]),
    # 系统页在设置里是最后一个标签（顺序：识别 / 外观 / 剪贴板 / 悬浮窗 / 数据 / 系统）
    ("system", "系统", [
        ("log_mode",
         "开启日志模式：将运行信息写入 logs/ 目录（true / false）",
         False),
        ("log_scope",
         '日志记录范围（字符串列表，可多选）："status"=状态栏消息, '
         '"screenshots"=截图事件, "errors"=错误信息',
         ["status", "screenshots", "errors"]),
        ("notification_enabled",
         "对局结束时弹出系统气泡通知（true / false）",
         True),
        ("notification_duration",
         "通知显示持续时间（秒），允许 {range}",
         1),
        ("minimize_to_tray",
         "关闭时隐藏到系统托盘（true / false；点 × 按钮时隐藏，最小化按钮正常最小化）",
         False),
        ("show_confidence",
         "状态栏显示置信度（段位图标 NCC、等级判读、对局事件检测分数；true / false）",
         False),
    ]),
]


def _fmt_range(lo: float, hi: float) -> str:
    """数值范围的展示文本（10.0 → "10"，0.5 → "0.5"）。"""
    return f"{lo:g} ~ {hi:g}"


def _fmt_toml_value(value) -> str:
    """按类型把 Python 值渲染成 TOML 字面量。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (int, float)):
        return f"{value}"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt_toml_value(v) for v in value) + "]"
    return str(value)  # 规格表由代码控制，正常不会走到这里


def render_config_toml(cfg: dict | None = None) -> str:
    """按 _CONFIG_LAYOUT 渲染完整的 config.toml 文本（含注释与取值说明）。

    唯一渲染入口：首启生成（generate_default_config）、语法损坏兜底、
    设置界面保存（ConfigDialog._write_toml）都调用本函数，保证各处生成的
    注释、段顺序、取值说明永远一致。值取自 cfg 的对应项，缺项用规格表
    默认值（与设置界面既有行为一致）。

    Args:
        cfg: 配置字典；None 时全部使用默认值（生成全新配置文件）。

    Returns:
        完整文件文本（以换行符结尾），可直接 write_text 写盘。
    """
    cfg = cfg or {}
    lines: list[str] = [
        "# MD Stats 配置文件（由程序生成，也可手动编辑）",
        "# 修改后点击主窗口的「设置 → 确定」即时生效。",
        "# 所有时间单位为秒，所有颜色使用十六进制格式。",
    ]
    for section, title, entries in _CONFIG_LAYOUT:
        lines.append("")
        if title:
            lines.append(f"# {title}")
        lines.append(f"[{section}]")
        sec = cfg.get(section)
        if not isinstance(sec, dict):
            sec = {}
        for key, comment, default in entries:
            rng = _RANGED_LIMITS.get((section, key))
            if rng is not None:
                comment = comment.replace("{range}", _fmt_range(*rng))
            for comment_line in comment.split("\n"):
                lines.append(f"# {comment_line}")
            lines.append(f"{key} = {_fmt_toml_value(sec.get(key, default))}")
    return "\n".join(lines) + "\n"


def _load_default_config() -> dict:
    """渲染并解析默认配置文本，返回配置字典（首启生成与语法损坏兜底共用同一来源）。"""
    return tomllib.loads(render_config_toml())


def generate_default_config(path: Path) -> None:
    """生成一份包含所有内置默认值的 config.toml。

    程序首启时（config.toml 缺失）自动调用；CI 构建发布包时也调用
    本函数生成包内默认配置——内容由 _CONFIG_LAYOUT 规格表渲染，与
    设置界面保存的版本逐字节一致，不再手工维护。
    """
    path.write_text(render_config_toml(), encoding="utf-8")
