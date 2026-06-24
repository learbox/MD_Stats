# MD Stats v1.10.0

基于图像识别的 **Master Duel 对局自动统计工具**。

## 快速开始

1. 双击 `MDStats.exe` 启动程序
2. 启动 Master Duel 游戏
3. 点击「启动」按钮，自动识别对局信息并记录
4. 对局结束后数据自动写入 `csv/` 目录

## 使用说明

- **自动识别** — 程序定时截图并匹配游戏界面，自动检测硬币输赢（含段位升降）、先后攻、对局胜负，状态栏显示匹配分数
- **手动补录** — 自动识别遗漏时，可点击手动按钮补录（按钮与自动识别状态联动）
- **记录编辑** — 双击记录表格中的单元格可直接编辑，修改自动写回 CSV
- **段位图标显示** — 段位列自动显示图标缩略图 + 段位名称（图标文件放入 `rankicons/` 目录即可，缺失时降级为纯文字）
- **段位快速编辑** — 双击段位单元格弹出按钮矩阵面板：点大段 → 点小段，两次点击完成选择；也支持输入自定义文字
- **统计表格** — 按卡组汇总对局数、胜率、硬币胜负率、先后攻胜率、段位胜率，支持自定义显示列
- **剪贴板复制** — 横排 TSV × 竖排 key: value 两种格式，一键复制
- **悬浮统计窗** — 可拖拽的半透明悬浮窗，实时显示当前卡组关键数据和检测状态
- **撤销 / 删除** — 手动录入支持逐级撤销，也可删除最后一条记录
- **记住卡组** — 开启后启动时自动从 CSV 填入上次使用的卡组名
- **调试工具** — 可选开启检测截图保存、接近成功的截图自动保留和日志模式，方便排查问题
- **段位图标识别** — 独立线程持续截图 + NCC 模板匹配 + RGBA 背景合成 + 列投影数字识别，自动检测双方段位（新手~巅峰 + I~V），写入 CSV 己方/对方段位列，可在设置中关闭
- **详细统计弹窗** — 按卡组 + 己方段位动态筛选，展示 17 项统计指标，支持一键复制。段位下拉从 CSV 数据动态生成，未知段位自动归入"无段位/其他"
- **CSV 占用暂存** — CSV 被其他程序占用时记录自动暂存，状态栏持续提醒，关闭后自动补写，退出时弹窗确认
- **系统通知** — 对局结束时弹出气泡通知，写入失败时气泡变 ⚠ 警告
- **主题切换** — 内置暗色/亮色/马卡龙三套主题，可自行制作
- **版本检查** — 在"关于"弹窗中一键检测 GitHub 最新版本

## 配置

点击主界面「设置」按钮打开图形化设置窗口，所有配置项均可可视化编辑，修改后即时生效。也可以直接编辑 `config.toml` 后点击「设置 → 确定」重载。

| 标签页 | 包含配置 |
|--------|---------|
| 识别 | 截图间隔、置信度阈值、段位检测开关及参数 |
| 调试 | 识别成功时保存截图、识别失败时诊断截图、截图热键 |
| 外观 | 主题选择、字体更换、窗口尺寸 |
| 剪贴板 | 竖排/横排模式、复制范围、列选择 |
| 悬浮窗 | 尺寸、背景色、透明度、文字颜色、字体、字号、背景图、显示数据行、状态行 |
| 数据 | 对方卡组预设、统计表格显示列、按日期分文件、记住上次卡组 |
| 系统 | 日志模式、系统通知、显示时长、最小化到托盘、置信度显示 |

## 模板图片

`resource/templates/` 下按分辨率存放模板截图（必选 6 张 + 可选 2 张）。如果游戏分辨率不在已有目录中，需要新建对应文件夹并放入模板图片。

> **段位图标需自行准备**：`rankicons/` 下的 9 张图片因版权未打包，需用 AssetRipper 从游戏资源中提取后放入对应目录（文件夹已创建），缺失时段位检测自动跳过。

```
resource/templates/
├── rankicons/               # 段位图标源素材（需自行提取 ⚠️）
│   ├── img_rankicon_01_l.png  → 新手
│   ├── img_rankicon_02_l.png  → 青铜
│   ├── img_rankicon_03_l.png  → 白银
│   ├── img_rankicon_04_l.png  → 黄金
│   ├── img_rankicon_05_l.png  → 铂金
│   ├── img_rankicon_06_l.png  → 钻石
│   ├── img_rankicon_07_l.png  → 大师
│   ├── img_rateicon_01_l.png  → 巅峰
│   └── rank_positions.toml    # 位置缓存（自动生成）
├── 1920x1080/
│   ├── coin_win.png        ← 赢硬币标识（必选）
│   ├── coin_lose.png       ← 输硬币标识（必选）
│   ├── rank_up.png         ← 升段标识（可选）
│   ├── rank_down.png       ← 降段标识（可选）
│   ├── go_first.png        ← 先攻标识（必选）
│   ├── go_second.png       ← 后攻标识（必选）
│   ├── victory.png         ← 胜利界面标识（必选）
│   ├── defeat.png          ← 失败界面标识（必选）
│   └── roi.toml            ← 搜索区域裁剪（可选）
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
├── LICENSE                  # MIT 开源协议
├── README.md                # 使用说明（当前文件）
├── TROUBLESHOOTING.md       # 常见问题排查
├── config.toml              # 配置文件
├── .app_state.toml          # 窗口状态持久化（自动生成）
├── csv/                     # 对战数据 CSV
├── screenshots/             # 调试截图（开启后自动生成）
│   └── debug/               # 诊断截图（匹配接近阈值时自动保留）
├── logs/                    # 日志文件（开启后自动生成）
│
├── resource/                # 静态资源
│   ├── icons/               # 程序图标
│   │   ├── app_icon.png           # 主窗口 + 系统托盘图标
│   │   └── floating_window_icon.png  # 悬浮窗图标
│   │
│   └── templates/           # 图像识别模板
│       ├── README.md              # 模板制作指南
│       │
│       ├── rankicons/             # 段位图标（识别用 + 表格显示用 ⚠️）
│       │   ├── img_rankicon_01_l.png  → 新手
│       │   ├── img_rankicon_02_l.png  → 青铜
│       │   ├── img_rankicon_03_l.png  → 白银
│       │   ├── img_rankicon_04_l.png  → 黄金
│       │   ├── img_rankicon_05_l.png  → 铂金
│       │   ├── img_rankicon_06_l.png  → 钻石
│       │   ├── img_rankicon_07_l.png  → 大师
│       │   ├── img_rateicon_01_l.png  → 巅峰
│       │   ├── img_rankicon_crown_l.png  （备用，未使用）
│       │   └── rank_positions.toml    # 图标位置缓存（自动生成）
│       │
│       ├── 1600x900/        # 1600×900 分辨率
│       │   ├── coin_win.png / coin_lose.png   ← 赢/输硬币（必选）
│       │   ├── go_first.png / go_second.png   ← 先攻/后攻（必选）
│       │   ├── victory.png / defeat.png       ← 胜/负界面（必选）
│       │   ├── rank_up.png / rank_down.png    ← 升段/降段（可选）
│       │   └── roi.toml                       ← 搜索区域裁剪（可选）
│       │
│       ├── 1920x1080/       # 1920×1080（同上结构）
│       ├── 2048x1152/       # 2048×1152（同上，无 rank_up/down）
│       ├── 2560x1440/       # 2560×1440（同上，无 rank_up/down）
│       ├── 3200x1800/       # 3200×1800（同上，无 rank_up/down）
│       └── 3840x2160/       # 3840×2160（同上，无 rank_up/down）
│
├── themes/                  # 主题目录
│   ├── README.md            # 自定义主题制作指南
│   │
│   ├── dark/                # 暗色沉浸主题
│   │   ├── theme.toml       #   颜色 / 字体 / 标题栏配置
│   │   └── style.qss        #   Qt 样式表
│   │
│   ├── light/               # 亮色清爽主题
│   │   ├── theme.toml
│   │   └── style.qss
│   │
│   └── macaron/             # 马卡龙水彩纹理主题
│       ├── theme.toml
│       ├── style.qss
│       └── assets/          #   主题图片 + 字体
│           ├── main_bg.png        # 主窗口背景图
│           ├── settings_bg.png    # 设置弹窗背景图
│           ├── table_bg.png       # 表格背景纹理
│           ├── header_bg.png      # 表头背景
│           ├── row_header_bg.png  # 行号列背景
│           ├── statusbar_bg.png   # 状态栏背景
│           ├── panel_bg.png       # 面板背景
│           ├── corner_bg.png      # 边角装饰
│           ├── button_texture.png # 按钮纹理
│           ├── float_bg.png       # 悬浮窗背景
│           ├── title_close.png    # 关闭按钮图标
│           ├── title_min.png      # 最小化按钮图标
│           ├── *.ttf / *.otf      # 自定义字体
│           └── OFL*.txt           # 字体开源许可证
│
└── .runtime/                # 运行时依赖（请勿修改）
```

## 遇到问题？

常见问题排查请参考 [TROUBLESHOOTING.md](https://github.com/learbox/MD_Stats/blob/main/docs/TROUBLESHOOTING.md)。识别不准时优先检查模板——在对应分辨率下重新截取通常可解决。

## 免责声明

- 游戏王为 KONAMI 公司的注册商标。本工具为非官方玩家自制辅助，与 KONAMI 无任何关联，也未经其认可。
- **本软件按"原样"提供，不提供任何形式的明示或暗示担保。** 作者不对因使用本软件而产生的任何直接或间接损失承担责任，包括但不限于数据丢失、游戏封号、财产损失等。详见 `LICENSE` 文件。

## 许可证

本项目使用 MIT 协议。依赖的第三方库及其协议：

| 库 | 协议 |
|----|------|
| PySide6 | LGPL |
| opencv-python | Apache 2.0 |
| numpy | BSD-3-Clause |
| mss | MIT |
| pywin32 | PSF |
