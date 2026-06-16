# MD Stats

基于图像识别的 **Master Duel 对局自动统计工具**。通过 OpenCV 模板匹配自动检测硬币输赢（含段位升降）、先后攻、对局胜负，记录到 CSV 并通过 GUI 展示统计数据。

## 功能

- **自动识别** — 定时截图 + OpenCV 模板匹配，自动检测对局的三阶段信息（硬币/先后攻/胜负），硬币阶段同时检测段位升降
- **手动联动** — 手动按钮与自动识别状态同步，自动漏检时可手动补录，互不冲突
- **统计表格** — 按卡组汇总对局数、胜率、硬币胜负率、先后攻胜率、段位胜率，支持自定义显示列
- **记录表格** — 每条对局的详细信息，支持倒序显示和单元格编辑（下拉菜单 + 自由输入）
- **多分辨率** — 自动检测游戏分辨率，切换对应模板子目录
- **撤销 / 删除** — 手动录入支持逐级撤销，支持删除最后 / 全部记录
- **图形化设置** — 内置设置弹窗，可视化编辑所有配置项，无需手动修改文件
- **主题系统** — 内置暗色/亮色/马卡龙三套主题，支持纯色和图片纹理，可自行制作
- **悬浮统计窗** — 可拖拽的半透明悬浮窗，实时显示当前卡组关键数据，位置持久化
- **版本更新检查** — 在"关于"弹窗中一键检测 GitHub 最新版本
- **调试工具** — 可选的检测截图保存和日志模式，方便排查问题
- **CSV 占用保护** — WPS/Excel 占用 CSV 时记录自动暂存到内存，状态栏持续告警，关闭占用程序后自动补写
- **系统通知** — 对局结束时弹出气泡通知，支持最小化到系统托盘

## 截图

```
┌───────────────────────────────────────────────────────────────────┐
│  [icon] MD Stats                                          [─] [×] │
├───────────────────────────────────────────────────────────────────┤
│  [启动] [停止]    使用卡组: [炎王]    [赢硬币] [输硬币] [撤销] [锁定卡组] │
├───────────────────────────────────────────────────────────────────┤
│  卡组 │ 对局数 │ 胜 │ 负 │ 胜率 │ 赢硬币次数 │ ...                   │  ← 统计表格
│  炎王 │  15   │ 10 │  5 │66.7%│     8     │ ...                    │
│  合计 │  15   │ 10 │  5 │66.7%│     8     │ ...                    │
├────────────────────────────────────────────────────────────────────┤
│  # │ 日期   │ 时间  │ 使用卡组 │ ... │ 赢硬币 │ 先后攻 │ 结果 │ 备注  │  ← 记录表格
│  1 │ 05-18 │ 09:54 │  炎王   │ ... │   是  │  先攻 │  胜  │         │
├────────────────────────────────────────────────────────────────────┤
│  [加载] [复制] [打开CSV] [删除最后] [悬浮窗] [设置] [关于]            │
│  就绪 — 请点击《启动》开始                          📁 data.csv     │
└────────────────────────────────────────────────────────────────────┘
```

## 安装

### 环境要求

- Python ≥ 3.11
- Windows（依赖 `pywin32` 进行窗口定位）

### 使用 uv（推荐）

```bash
git clone https://github.com/learbox/mdstats_py.git
cd mdstats_py
uv sync
```

### 使用 pip

```bash
pip install mss numpy opencv-python pyside6 pywin32
```

## 准备模板图片

在 `resource/templates/` 下按游戏分辨率创建子目录，放入模板截图（必选 6 张 + 可选 2 张段位检测）：

```
resource/templates/
├── 1920x1080/          ← 分辨率子目录（宽×高）
│   ├── coin_win.png    ← 赢硬币标识
│   ├── coin_lose.png   ← 输硬币标识
│   ├── rank_up.png     ← 升段标识（可选）
│   ├── rank_down.png   ← 降段标识（可选）
│   ├── go_first.png    ← 先攻标识
│   ├── go_second.png   ← 后攻标识
│   ├── victory.png     ← 胜利界面标识
│   └── defeat.png      ← 失败界面标识
├── 2560x1440/
│   └── ...
└── 3840x2160/
    └── ...
```

模板建议在目标分辨率下截取 **特征明显的 UI 区域**，尺寸 50×50 到 200×200 像素，支持 PNG/JPG/BMP 格式。

## 运行

```bash
python main.py
```

1. Master Duel 未启动时，点击"启动"会询问是否通过 Steam 启动游戏
2. 等待窗口出现后自动开始识别
3. 对局结束后数据自动写入 `csv/` 目录
4. 如果自动识别有遗漏，用手动按钮补录（按钮会跟随识别状态联动）
5. 记录表格中的单元格可直接双击编辑，修改自动写回 CSV

## 配置

点击主界面的「设置」按钮打开图形化设置弹窗，可视化编辑所有配置项。也可以直接编辑 `config.toml` 后点击「设置 → 确定」重载。

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `detection.interval` | 截图间隔（秒） | `0.3` |
| `detection.confidence_threshold` | 匹配置信度阈值 (0.0~1.0) | `0.8` |
| `window.width` / `height` | 主窗口尺寸（像素） | `1300` / `700` |
| `appearance.theme` | 界面主题，填写 `themes/` 下的文件夹名 | `"macaron"` |
| `opponent_decks.presets` | 对方卡组预设列表 | `["炎兽", "闪刀姬", ...]` |
| `debug.save_screenshots` | 保存检测截图（开启后写入 `screenshots/`） | `false` |
| `debug.auto_clear_screenshots` | 下一局开始时自动清除上一局的截图 | `true` |
| `debug.hotkey_enabled` | 启用截图热键（全局热键） | `false` |
| `debug.snapshot_hotkey` | 单次截图热键 | `"Ctrl+Shift+S"` |
| `debug.periodic_hotkey` | 周期截图热键 | `"Ctrl+Shift+D"` |
| `debug.periodic_interval` | 周期截图间隔（秒） | `0.5` |
| `debug.log_mode` | 日志模式（开启后写入 `logs/`） | `false` |
| `debug.log_scope` | 日志记录范围：`status`/`screenshots`/`errors` | `["status","screenshots","errors"]` |
| `recorder.daily_files` | 是否按日期分 CSV 文件 | `false` |
| `stats.columns` | 统计表格显示的列（空 = 全部） | `[]` |
| `recorder.remember_last_deck` | 启动时自动填入上次使用的卡组 | `true` |
| `clipboard.vertical_layout` | 剪贴板竖排模式 | `true` |
| `clipboard.scope` | 复制范围（`"all"` / `"current"`） | `"all"` |
| `floating_window.width` / `height` | 悬浮窗尺寸（高度低于内容时自动扩容） | `250` / `330` |
| `notification.enabled` | 对局结束系统气泡通知 | `false` |
| `notification.duration` | 通知显示时长（秒） | `5` |
| `notification.minimize_to_tray` | 最小化到系统托盘 | `false` |
| `notification.obs_mode` | OBS 捕获模式（悬浮窗显示任务栏图标） | `false` |
| `floating_window.bg_color` | 悬浮窗背景色 | `#BDEF0A` |
| `floating_window.opacity` | 悬浮窗不透明度 (0-100) | `50` |
| `floating_window.show_status` | 悬浮窗底部显示检测状态 | `false` |
| `floating_window.rows` | 悬浮窗显示数据行 | 8 项默认 |

### 日志模式快速上手

开启"系统"标签页中的日志模式后，所有左下角状态栏文字自动写入 `logs/mdstats_YYYYMMDD.log`。日志按类别分为三种：

| 作用域 | 标签 | 内容示例 |
|--------|------|---------|
| 状态栏消息 | `[STATUS]` | `正在运行 — 等待识别硬币…` |
| 截图事件 | `[SCRN]` | `已保存: coin_win_1920x1080.png` |
| 错误信息 | `[ERROR]` | `工作线程异常: ...` |

可在设置中单独勾选要记录的类别，点击「查看日志」按钮快速打开日志文件夹。

### 主题

内置三套主题：`dark`（暗色沉浸）、`light`（亮色清爽）、`macaron`（马卡龙水彩纹理）。通过设置弹窗或 `config.toml` 切换。

**制作自定义主题**：在 `themes/` 下新建文件夹 → 放入 `theme.toml`（修改颜色/字体/图片）+ `style.qss`（复制内置模板）+ `assets/`（图片和字体） → 在 `config.toml` 中填写文件夹名。详见 `themes/README.md`。

## 项目结构

```
mdstats_py/
├── main.py                  # 程序入口
├── config.toml              # 配置文件
├── pyproject.toml           # 项目元数据与依赖 (uv)
├── uv.lock                  # 依赖锁定文件
├── CHANGELOG.md             # 更新日志
├── LICENSE                  # MIT 开源协议
├── .app_state.json          # 窗口状态持久化
├── .github/workflows/       # CI/CD 自动构建与发布
├── docs/                    # 文档
│   ├── README_release.md    # 发行包附带说明
│   ├── TROUBLESHOOTING.md   # 常见问题排查
│   └── RELEASE.md           # 发布流程
├── resource/templates/      # 模板图片（按分辨率分目录）
├── csv/                     # 对战数据 CSV 文件
├── screenshots/             # 调试截图输出（开启 save_screenshots 后自动生成）
├── logs/                    # 日志文件输出（开启 log_mode 后自动生成）
├── themes/                  # 主题目录
│   ├── README.md            # 主题制作指南
│   ├── dark/                # 暗色沉浸主题
│   │   ├── theme.toml
│   │   ├── style.qss
│   │   └── assets/
│   ├── light/               # 亮色清爽主题
│   └── macaron/             # 马卡龙水彩纹理主题
│       ├── theme.toml
│       ├── style.qss
│       └── assets/          # 背景图片 + 图标
├── src/
│   ├── app_state.py         # 应用状态持久化（窗口位置 / 列宽）
│   ├── theme_loader.py      # 主题加载（TOML 解析 + QSS 占位符替换）
│   ├── capture.py           # 窗口定位与截图（mss + pywin32）
│   ├── config.py            # config.toml 配置加载
│   ├── detector.py          # OpenCV 模板匹配识别
│   ├── hotkey_listener.py   # 全局热键监听（独立线程）
│   ├── logger.py            # 日志模块（线程安全 + 作用域过滤）
│   ├── match_state.py       # 对局三阶段状态机
│   ├── recorder.py          # CSV 读写与统计计算
│   ├── snapshot_controller.py # 截图热键与周期截图
│   └── stats_worker.py      # 后台识别线程（QThread）
└── ui/
    ├── main_window.py       # 主窗口逻辑
    ├── main_window.ui       # Qt Designer 界面文件（源文件）
    ├── main_window_ui.py    # 编译后的 UI（pyside6-uic 生成）
    ├── config_dialog.py     # 设置弹窗（GUI 配置编辑器）
    ├── about_dialog.py      # 关于弹窗 + 版本号等元数据
    ├── titlebar.py          # 自定义标题栏
    ├── theme_manager.py     # 主题管理器
    └── floating_window.py   # 悬浮统计窗
```

## 致谢

- 设计思路参考了 [ULeang/mdstats](https://github.com/ULeang/mdstats)（GPL-3.0，C++）— 代码完全独立编写
- 马卡龙主题感谢 [KleeKlee](https://github.com/slimpigs) 提供代码修改支持和无偿提供的美术资源
- 感谢 [ULya_tooru](https://github.com/ULeang) 提供原版思路
## 工具与资源

- 代码辅助：Claude Code (Anthropic)、GLM-5.1 (智谱)、DeepSeek-V4-Pro
- 主题图片资源由 GPT-5.5 生成

## 免责声明

- 游戏王为 KONAMI 公司的注册商标。本工具为非官方玩家自制辅助，与 KONAMI 无任何关联，也未经其认可。
- **本软件按"原样"提供，不提供任何形式的明示或暗示担保。** 作者不对因使用本软件而产生的任何直接或间接损失承担责任，包括但不限于数据丢失、游戏封号、财产损失等。详见 [LICENSE](LICENSE)。

## 遇到问题？

查看 [常见问题排查](docs/TROUBLESHOOTING.md)。识别不准确时，99% 是模板问题——请在对应分辨率下重新截取模板图片。

## 许可证

本项目使用 MIT 协议。依赖的第三方库及其协议：

| 库 | 协议 |
| --- | --- |
| PySide6 | LGPL |
| opencv-python | Apache 2.0 |
| numpy | BSD-3-Clause |
| mss | MIT |
| pywin32 | PSF |
