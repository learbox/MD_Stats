# MD Stats v1.3.1

基于图像识别的 **Master Duel 对局自动统计工具**。

## 快速开始

1. 双击 `MDStats.exe` 启动程序
2. 启动 Master Duel 游戏
3. 点击「启动」按钮，自动识别对局信息并记录
4. 对局结束后数据自动写入 `csv/` 目录

## 使用说明

- **自动识别** — 程序定时截图并匹配游戏界面，自动检测硬币输赢、先后攻、对局胜负
- **手动补录** — 自动识别遗漏时，可点击手动按钮补录（按钮与自动识别状态联动）
- **记录编辑** — 双击记录表格中的单元格可直接编辑，修改自动写回 CSV
- **悬浮统计窗** — 点击「悬浮窗」按钮，弹出可拖拽的半透明统计窗口
- **撤销 / 删除** — 手动录入支持逐级撤销，也可删除最后一条记录

## 配置

编辑 `config.toml` 修改配置，修改后点击「重新载入配置」即时生效。

常用配置项：

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `detection.interval` | 截图间隔（秒） | `0.3` |
| `detection.confidence_threshold` | 匹配置信度阈值 | `0.8` |
| `appearance.theme` | 界面主题（`dark`/`light`/`macaron`） | `"dark"` |
| `opponent_decks.presets` | 对方卡组预设列表 | `["炎兽", ...]` |
| `floating_window.opacity` | 悬浮窗不透明度 (0-100) | `50` |

## 模板图片

`resource/templates/` 下按分辨率存放模板截图。如果游戏分辨率不在已有目录中，需要新建对应文件夹并放入模板图片：

```
resource/templates/
├── 1920x1080/
│   ├── coin_win.png     ← 赢硬币标识
│   ├── coin_lose.png    ← 输硬币标识
│   ├── go_first.png     ← 先攻标识
│   ├── go_second.png    ← 后攻标识
│   ├── victory.png      ← 胜利界面标识
│   └── defeat.png       ← 失败界面标识
├── 2560x1440/
└── 3840x2160/
```

## 主题

内置三套主题：`dark`（暗色沉浸）、`light`（亮色清爽）、`macaron`（马卡龙水彩纹理）。

在 `themes/` 下新建文件夹即可创建自定义主题，详见 `themes/README.md`。

## 文件结构

```
MDStats/
├── MDStats.exe              # 主程序
├── config.toml              # 配置文件
├── .app_state.json          # 窗口状态持久化
├── csv/                     # 对战数据
├── resource/templates/      # 模板图片
├── themes/                  # 主题目录（可自定义）
└── .runtime/                # 运行时依赖（请勿修改）
```
