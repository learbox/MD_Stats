"""热键字符串解析 — 把 "Ctrl+Shift+S" 转成 Windows API 所需的按键码。

独立成无依赖小模块（纯标准库、不 import PySide6），因为调用方横跨两层：
    - src/hotkey_listener.py / src/snapshot_controller.py —— 注册前的解析
    - src/config.py —— 读取配置时的热键合法性校验（回退默认值并提示）
config.py 会被识别线程乃至 CI 生成配置模板的路径引用，不宜牵入 GUI 依赖，
解析规则必须全项目共用一份、避免漂移。
"""


def parse_hotkey(combo: str) -> tuple[int, int]:
    """解析热键字符串为 Windows API 所需的 (修饰键位掩码, 虚拟键码)。

    例如 "Ctrl+Shift+S" → (MOD_CONTROL | MOD_SHIFT = 0x0006, ord('S') = 0x53)

    RegisterHotKey 需要两个参数：
        fsModifiers — 修饰键的位掩码（MOD_ALT=0x0001, MOD_CONTROL=0x0002,
                      MOD_SHIFT=0x0004, MOD_WIN=0x0008）
        vk          — 主键的虚拟键码（A-Z → ord('A')-ord('Z'),
                      F1-F12 → 0x70-0x7B）

    无法识别主键时 vk 为 0（如 "123abc"、只有修饰键的 "Ctrl+Shift"），
    调用方据此判断合法性——注册前跳过、校验时回退默认值。
    """
    _modifiers = {"Ctrl": 0x0002, "Shift": 0x0004, "Alt": 0x0001, "Win": 0x0008}
    keys = combo.split("+")
    mod = 0
    vk = 0
    for k in keys:
        k = k.strip()
        if k in _modifiers:
            mod |= _modifiers[k]               # 累加修饰键位掩码
        elif len(k) == 1:
            vk = ord(k.upper())              # 单个字母/数字的虚拟键码
        else:
            for i in range(1, 13):           # F1-F12
                if k == f"F{i}":
                    vk = 0x70 + i - 1
                    break
    return mod, vk


def is_valid_hotkey(combo: str) -> bool:
    """判断热键字符串是否解析出主键（vk 非 0 即视为可用）。

    与 snapshot_controller 注册前的 `if vk:` 守卫同一口径：
    解析不出主键的组合注册时会被跳过（按了没反应），应视为无效输入。
    """
    return parse_hotkey(combo)[1] != 0
