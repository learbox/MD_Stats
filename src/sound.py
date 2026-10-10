"""音效播放模块 — 基于标准库 winsound 播放 resource/sounds/ 下的 wav 音效。

供截图提示音及后续其他提示音场景（如三段循环音效）复用。
新增音效只需两步：
    1. 放入 resource/sounds/{name}.wav（标准 PCM wav，来源与许可注明在
       该目录 README.md）
    2. 调用 play_sound(name)；"播不播"的开关判断由调用方自行负责

winsound 是 Windows 特有的标准库模块（底层为 winmm.dll 的薄封装），
只能播放 WAV（PCM）与系统注册表中的声音别名。
"""

# PEP 810 懒加载（Python 3.15+）：首次调用 play_sound 时才导入 winsound
lazy import winsound

from src.config import get_project_root


def play_sound(name: str) -> None:
    """播放 resource/sounds/{name}.wav，例如 play_sound("snapshot")。

    异步播放：立即返回，不阻塞调用方（热键响应、检测线程均不受影响）；
    SND_NODEFAULT 确保音效文件缺失时静默跳过，不会回退播放系统提示音。
    注意 winsound 为单通道播放，新的播放会打断尚未播完的上一段音效。

    Args:
        name: 音效名（不带扩展名），对应 resource/sounds/{name}.wav。
    """
    path = get_project_root() / "resource" / "sounds" / f"{name}.wav"
    if path.exists():
        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
