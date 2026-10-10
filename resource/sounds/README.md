# sounds — 提示音资源

本目录存放程序音效。文件名即 `src/sound.py` 中 `play_sound(name)` 的 name 参数。

## snapshot.wav

- **用途**：单次截图热键（`debug.snapshot_sound`）的**成功**提示音，截图保存成功后播放
- **原始录音**：[Mouse Click Sound.mp3 by Pixeliota](https://freesound.org/s/678248/)，来自 Freesound
- **许可**：Creative Commons 0（CC0，公共领域）——可自由使用、修改、再分发，无需署名
- **分发渠道**：经 [@remotion/sfx](https://www.remotion.dev/docs/sfx/mouse-click)（MIT）音效库获取
- **处理**：统一为 44.1kHz / 单声道 / 16bit PCM，峰值归一化至 -3dB

## error.wav

- **用途**：单次截图**未成功**（任何原因，如窗口未找到、磁盘不可写）时播放的警示音
  （与 snapshot.wav 同受 `debug.snapshot_sound` 开关控制）
- **来源**：本仓库自产——numpy 合成（下行双音 660→440Hz，0.43s，
  正弦基波 + 二三次谐波 + 指数衰减包络），无版权限制，可自由使用与修改
- **处理**：44.1kHz / 单声道 / 16bit PCM，峰值归一化至 -3dB

## coin.wav / turn.wav / result.wav

- **用途**：检测事件提示音——由 `debug.detection_sound`（总开关）与
  `debug.coin_sound` / `turn_sound` / `result_sound`（分段开关）控制，
  识别到硬币结果、先后攻、对局胜负时播放
- **来源**：本仓库自产——numpy 合成（正弦基波 + 二三次谐波 + 指数衰减包络），
  无版权限制，可自由使用与修改
- **设计**：三段音调可区分——coin 高音单叮（C6，0.35s）、turn 上行双音
  （G5→C6，0.46s）、result 下行双音（C6→G5，0.60s）
- **处理**：44.1kHz / 单声道 / 16bit PCM，峰值归一化至 -3dB
- **备注**：过渡性音效，后续替换更满意的音源时保持文件名不变即可

## 新增音效

1. 将标准 PCM wav 放入本目录（建议 44.1kHz / 单声道 / 16bit，峰值归一化到 -3dB）
2. 调用 `play_sound("文件名")` 即可播放
3. 在本文件中为该音效补充小节，注明来源与许可——优先选择 CC0 / Apache-2.0
   等允许随仓库再分发的许可；仅限项目内使用、不允许再分发的素材（如 Mixkit）
   不要放入本目录
