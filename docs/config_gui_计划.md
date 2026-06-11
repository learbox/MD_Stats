# 配置 GUI 化实现计划

## 目标

用 Qt 设置弹窗取代 `config.toml` 手动编辑，提升用户体验。主界面"编辑配置"+"重新载入配置"合并为一个"设置"按钮。

## 架构

```
点击"设置" →
  ConfigDialog(QDialog)
    ├── 自定义标题栏 (复用 TitleBar 模式)
    ├── QTabWidget
    │   ├── [识别]     — 截图间隔、匹配阈值
    │   ├── [外观]     — 主题、窗口尺寸
    │   ├── [剪贴板]   — 竖排开关、范围、列选择
    │   ├── [悬浮窗]   — 尺寸/颜色/透明度/字体/行选择/主题背景
    │   └── [数据]     — 卡组预设、按日期分文件
    ├── 预览区（右侧或底部）
    └── [取消] [确定]
          │        └→ 写 config.toml + _on_reload_config()
          └→ 丢弃修改，关闭弹窗
```

## 文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `ui/config_dialog.ui` | 源文件 | Qt Designer 布局 |
| `ui/config_dialog_ui.py` | 编译产物 | pyside6-uic 生成，禁止手改 |
| `ui/config_dialog.py` | 逻辑 | ConfigDialog 类，读写 config.toml |
| `ui/main_window.ui` | 修改 | btn_edit_config + btn_reload_config → btn_settings |
| `ui/main_window_ui.py` | 重新编译 | |
| `ui/main_window.py` | 修改 | 替换两个旧按钮，新增 _on_settings 方法 |
| `themes/*/theme.toml` | 新增 | settings_bg 图片 key（可选） |

## 标签页详细设计

### Tab 1：识别 (`[detection]`)

```
┌─ 识别 ──────────────────────────────────────┐
│                                              │
│  截图间隔:  [0.3] 秒  (QDoubleSpinBox)        │
│             └─ 范围 0.1 ~ 10.0，步长 0.1      │
│                                              │
│  匹配阈值:  [0.80]     (QDoubleSpinBox)        │
│             └─ 范围 0.0 ~ 1.0，步长 0.05      │
│                                              │
│  注: 阈值越高越不容易误识别，但可能漏识别       │
└──────────────────────────────────────────────┘
```

### Tab 2：外观 (`[window]` + `[appearance]`)

```
┌─ 外观 ──────────────────────────────────────┐
│                                              │
│  主题:  [macaron  ▾]  (QComboBox)             │
│         扫描 themes/ 文件夹自动填充            │
│                                              │
│  窗口宽度:  [1300] px  (QSpinBox, 100~5000)   │
│  窗口高度:  [700]  px  (QSpinBox, 100~5000)   │
│                                              │
│  [重置窗口位置] 按钮 — 清掉 .app_state.json    │
│                                               │
└──────────────────────────────────────────────┘
```

主题下拉打开时扫描 `themes/`，如果为空显示 `"(内置亮色)"` 且禁用。

### Tab 3：剪贴板 (`[clipboard]`)

```
┌─ 剪贴板 ─────────────────────────────────────┐
│                                              │
│  格式:  ◉ 横排 TSV    ○ 竖排 key: value       │
│         (QRadioButton)                        │
│                                              │
│  范围:  ◉ 当前卡组    ○ 全部卡组               │
│                                              │
│  要复制的列:                                  │
│  ┌────────────┐  →  ┌────────────┐            │
│  │ 先攻次数    │     │ 卡组        │           │
│  │ 后攻次数    │  ←  │ 对局数      │           │
│  │ ...        │     │ 胜/负       │           │
│  └────────────┘  ↑↓ └────────────┘            │
│    (可选)            (已选, 可排序)            │
└──────────────────────────────────────────────┘
```

### Tab 4：悬浮窗 (`[floating_window]`)

```
┌─ 悬浮窗 ────────────────────────────────────┐
│                                              │
│  尺寸:  宽 [250] × 高 [300]  (QSpinBox×2)    │
│                                              │
│  背景:  [████████] (色块按钮)                 │
│         点击弹出系统取色器                     │
│         透明度: [━━━━●━━━] 50%  (QSlider)     │
│                                              │
│  ☐ 使用主题背景图 (use_theme_bg)              │
│     勾选后 bg_color 仅作兜底                  │
│                                              │
│  文字:  [████████] (色块按钮 + 取色器)         │
│        字号: [20]  (QSpinBox, 8~72)           │
│        字体: [Microsoft YaHei     ▾]          │
│               (QFontComboBox)                 │
│                                              │
│  显示数据行: (同剪贴板的 双列 + 排序)          │
│                                              │
│  ┌── 预览区 ──────────────────────────┐      │
│  │  炎兽                                │      │
│  │  对局数                    15        │      │
│  │  胜/负                  10 / 5      │      │
│  │  综合胜率                66.7%      │      │
│  └────────────────────────────────────┘      │
└──────────────────────────────────────────────┘
```

预览区用 `QTableWidget(4×2)` 或 `QGridLayout` 拼 QLabel，字体色块实时跟配置变。

### Tab 5：数据 (`[opponent_decks]` + `[recorder]`)

```
┌─ 数据 ───────────────────────────────────────┐
│                                              │
│  对方卡组预设:                                │
│  ┌──────────────┐                             │
│  │ 炎兽          │  [添加]  输入框 + 按钮       │
│  │ 闪刀姬        │  [删除]  选中后删除          │
│  │ 烙印          │                             │
│  │ 白银城        │                             │
│  └──────────────┘                             │
│                                              │
│  ☐ 按日期分文件 (daily_files)                 │
│                                              │
└──────────────────────────────────────────────┘
```

## 输入控件选型总结

| config key | 控件 | 验证 |
|-----------|------|------|
| interval | QDoubleSpinBox (0.1~10, step 0.1) | 自动防非数字 |
| confidence_threshold | QDoubleSpinBox (0.0~1.0, step 0.05) | 自动防非数字 |
| theme | QComboBox | 扫描填充，只读可选 |
| width/height | QSpinBox (100~5000) | 自动防非数字 |
| vertical_layout | QRadioButton (横排/竖排) | 互斥，无非法值 |
| scope | QRadioButton (当前/全部) | 互斥，无非法值 |
| columns/rows | 双列 QListWidget + →←↑↓ | 只能选已有条目 |
| bg_color/text_color | QPushButton 色块 + QColorDialog | 系统取色器 |
| opacity | QSlider (0~100) + 数值标签 | 滑块无非法值 |
| font_size | QSpinBox (8~72) | 自动防非数字 |
| font_family | QFontComboBox | 只显示系统已装字体 |
| presets | QListWidget + 添加/删除 | trim 空字符串 |
| use_theme_bg | QCheckBox | 布尔值 |
| daily_files | QCheckBox | 布尔值 |

## 主题集成

弹窗 `#configDialog` 用全局 QSS 规则（同主窗口的 `QPushButton`、`QComboBox` 等），背景纯色用 `{{color.widget_bg}}`。主题可选新增 `settings_bg` 图片。

弹窗标题栏文字和按钮图标跟随主题，复用现有 `TitleBar` 的 `reload_style` 模式。

## 主界面改动

1. `main_window.ui`: 删除 `btn_edit_config`、`btn_reload_config`，新增 `btn_settings`
2. `main_window.py`:
   - 删除 `_on_edit_config`、`_on_reload_config` 方法签名（逻辑移入 ConfigDialog）
   - 新增 `_on_settings` → `ConfigDialog(self._config, self).exec()`
   - `_disable_bottom_buttons` / `_enable_bottom_buttons` 管理 `btn_settings`
   - `_on_reload_config` 保留为 ConfigDialog 调用的公共方法

## config.toml 读写

- `ConfigDialog.__init__`: 读取 `config.toml` → 填入各控件
- `ConfigDialog._on_save`: 从控件取值 → 构建 TOML 结构 → `tomllib` 不加就直接写字典 → 用自定义函数写回文件（保留注释和格式，或用简单方式重新生成）

简单方案：不保留原注释，用 `tomllib` 或手动生成的格式写回。不影响功能。注释只存在于代码 docstring 和 README，用户不会看到原始文件。

## 实现顺序

1. `config_dialog.ui` — Qt Designer 画界面
2. `config_dialog_ui.py` — 编译
3. `config_dialog.py` — 逻辑（读写、双列控件、预览）
4. `main_window.ui` — 改按钮
5. `main_window_ui.py` — 重新编译
6. `main_window.py` — 添加 _on_settings
7. 主题文件 — 可选新增 settings_bg
8. 测试

## 注意事项

- 旧 `_on_edit_config` 和 `_on_reload_config` 逻辑不能丢——核心重载逻辑保留
- 双列 QListWidget 需要自定义 widget（QListWidget + 4 个 QPushButton 箭头）
- 预览区不需要实时更新主窗口，仅在弹窗内显示静态示例
- 卡组预设空字符串需过滤
- 主题下拉打开时如果 themes/ 为空则禁用
