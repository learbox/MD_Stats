# 模板图片说明

本目录存放用于图像识别的模板图片。请从 Master Duel 游戏画面中截取 UI 元素，按游戏渲染分辨率放入对应的子目录。

## 目录结构

```
templates/
├── rankicons/              # 段位图标源素材（不分分辨率，RGBA 格式）
│   ├── img_rankicon_01_l.png  → 新手
│   ├── img_rankicon_02_l.png  → 青铜
│   ├── img_rankicon_03_l.png  → 白银
│   ├── img_rankicon_04_l.png  → 黄金
│   ├── img_rankicon_05_l.png  → 铂金
│   ├── img_rankicon_06_l.png  → 钻石
│   ├── img_rankicon_07_l.png  → 大师
│   ├── img_rankicon_crown_l.png
│   ├── img_rateicon_01_l.png  → 巅峰
│   └── rank_positions.toml  # 段位图标位置缓存（自动生成）
├── 1920x1080/              ← 1080p 分辨率模板
│   ├── coin_win.png
│   ├── coin_lose.png
│   ├── rank_up.png         ← 升段标识（可选）
│   ├── rank_down.png       ← 降段标识（可选）
│   ├── go_first.png
│   ├── go_second.png
│   ├── victory.png
│   └── defeat.png
├── 2560x1440/              ← 1440p 分辨率模板
│   └── ...
└── 3840x2160/              ← 4K 分辨率模板
    └── ...
```

- 子目录命名规则：`{宽}x{高}`（仅数字和小写 `x`，不含空格）
- 程序根据 Master Duel 窗口客户区尺寸自动选择对应子目录
- 子目录必须存在且包含全部 6 张必选模板，否则启动时状态栏会显示警告
- `rank_up.png` 和 `rank_down.png` 是可选的，缺失时不阻止检测启动
- `rankicons/` 目录不存在时，段位检测静默跳过，不影响其他功能

## 识别流程

程序分三个阶段依次检测：

> 阶段 1 — 硬币输赢（同时检测段位升降） → 阶段 2 — 先后攻 → 阶段 3 — 对局胜负

## 模板文件清单

每个分辨率子目录需要 **6 张必选 + 2 张可选**：

| # | 文件名 | 说明 | 必选 |
|---|--------|------|:---:|
| 1 | `coin_win.png` | 赢硬币标识 — 抛硬币后显示"赢得硬币选择权"的 UI 元素 | ✅ |
| 2 | `coin_lose.png` | 输硬币标识 — 抛硬币后显示"对手获得硬币选择权"的 UI 元素 | ✅ |
| 3 | `go_first.png` | 先攻标识 — 硬币结果确定后显示"先攻"的 UI 元素 | ✅ |
| 4 | `go_second.png` | 后攻标识 — 硬币结果确定后显示"后攻"的 UI 元素 | ✅ |
| 5 | `victory.png` | 胜利标识 — 对局结束时显示胜利的 UI 元素 | ✅ |
| 6 | `defeat.png` | 失败标识 — 对局结束时显示失败的 UI 元素 | ✅ |
| 7 | `rank_up.png` | 升段标识 — 硬币画面中显示段位上升的 UI 元素 | ❌ |
| 8 | `rank_down.png` | 降段标识 — 硬币画面中显示段位下降的 UI 元素 | ❌ |

## 段位图标源素材（需自行准备）

> **⚠️ 因版权原因，仓库不包含 `rankicons/` 下的图片文件。** 使用段位检测功能前，需自行从游戏资源包中提取。

### 如何获取

1. 下载 [AssetRipper](https://github.com/AssetRipper/AssetRipper)（开源 Unity 资源提取工具）
2. 用 AssetRipper 打开 Master Duel 安装目录下的资源文件
3. 搜索并导出以下 9 张段位图标（290×290 RGBA PNG，文件名通常带 `_l` 后缀）：

| 文件名 | 对应段位 |
|--------|---------|
| `img_rankicon_01_l.png` | 新手 |
| `img_rankicon_02_l.png` | 青铜 |
| `img_rankicon_03_l.png` | 白银 |
| `img_rankicon_04_l.png` | 黄金 |
| `img_rankicon_05_l.png` | 铂金 |
| `img_rankicon_06_l.png` | 钻石 |
| `img_rankicon_07_l.png` | 大师 |
| `img_rateicon_01_l.png` | 巅峰 |
| `img_rankicon_crown_l.png` | （可选） |

4. 将提取的图片放入 `resource/templates/rankicons/`（文件夹已创建）

### 其他说明

- 格式：RGBA 32 位（带透明通道），290×290 像素
- 用途：段位检测模块通过采样截图实际背景色，将 RGBA 合成到背景上后进行模板匹配
- **缺失不影响主流程**：图片不全或文件夹为空时，段位检测静默跳过，不弹窗、不报错
- `rankicons/rank_positions.toml`：首次检测到段位图标后自动生成的位置缓存，下次启动加载可加速检测

## 注意事项

- 模板必须在目标分辨率下截取，不同分辨率下 UI 像素大小不同
- 截取的是客户区（游戏实际渲染画面），不含标题栏。全屏模式和窗口模式下客户区尺寸相同（均为渲染分辨率）
- 支持的图片格式：PNG、JPG、JPEG、BMP
- 模板匹配使用归一化相关系数（`TM_CCOEFF_NORMED`），阈值在 `config.toml` 中配置（默认 `0.8`）
