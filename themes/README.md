# 主题制作指南

创建一个自定义主题只需 **修改 `theme.toml` 配置** + **放入图片/字体资源**，无需编写任何 QSS 样式代码。

## 快速开始

1. 在 `themes/` 下新建一个文件夹（如 `themes/my-theme/`）
2. 复制任一内置主题的 `theme.toml` 和 `style.qss` 到你的文件夹
3. 在 `config.toml` 中设置 `theme = "my-theme"`
4. 修改 `theme.toml` 中的颜色值 → 启动即可看到效果

## 文件夹结构

```
themes/my-theme/
├── theme.toml          # 主题配置（颜色、字体、图片、标题栏）
├── style.qss           # QSS 样式模板（无需修改，直接复制内置主题的）
└── assets/             # 资源文件（可选）
    ├── main_bg.png         # 主窗口背景图
    ├── panel_bg.png        # 面板背景图
    ├── table_bg.png        # 表格背景图
    ├── header_bg.png       # 表头背景图
    ├── row_header_bg.png   # 行号列表头背景图
    ├── corner_bg.png       # 表格左上角交叉按钮背景图
    ├── button_texture.png  # 按钮纹理
    ├── statusbar_bg.png    # 状态栏背景图
    ├── float_bg.png        # 悬浮窗背景图（可选）
    ├── settings_bg.png     # 设置弹窗背景图（可选）
    ├── title_min.png       # 最小化按钮图标
    ├── title_close.png     # 关闭按钮图标
    └── MyFont.ttf          # 自定义字体文件
```

## theme.toml 配置说明

### [meta] — 主题信息

```toml
[meta]
name = "我的主题"   # 主题显示名称
```

### [titlebar] — 标题栏外观

| 字段 | 类型 | 说明 |
|------|------|------|
| height | 整数 | 标题栏高度（像素），默认 36 |
| icon_size | 整数 | 图标显示尺寸（像素），默认 20 |
| text_color | 颜色 | 标题文字颜色 |
| text_size | 整数 | 标题文字字号 |
| text_font | 字符串 | 标题字体栈（可选，空则用全局字体） |
| text_shadow | 颜色 | 标题文字阴影颜色（可选，空则不启用） |
| btn_hover_bg | 颜色 | 最小化按钮悬停背景色 |
| btn_close_hover | 颜色 | 关闭按钮悬停背景色 |

### [assets] — 字体和图片

**字体**（两种方式可同时用）：

方式一：使用系统已安装的字体
```toml
font_family = "Microsoft YaHei"
```

方式二：使用 assets/ 下的 TTF 字体文件（无需安装）
```toml
font_family = '"My Custom Font", "Microsoft YaHei"'

[[assets.fonts]]
file   = "MyCustomFont.ttf"    # assets/ 下的字体文件名
family = "My Custom Font"      # 加载后的字体族名（填到 font_family 中）
```

**背景图片**：全部可选，`file = ""` 时用纯色填充。stretch 模式会自动拉伸适配控件，无需精确尺寸。

| 配置项 | 对应软件位置 | 推荐尺寸 | 模式 | 内置参考（macaron） |
|--------|------------|---------|------|---------------------|
| main_bg | 主窗口全幅背景 | 1560×1000 | stretch | 1573×1000 |
| panel_bg | 顶部控制栏 + 底部按钮面板 | 1760×260 | stretch | 1764×265 |
| table_bg | 统计表格 + 对战记录表格 | 1860×810 | stretch | 1855×810 |
| header_bg | 表格列标题栏 | 1920×220 | stretch | 1928×224 |
| row_header_bg | 行号列表头栏 | 340×3000 | stretch | 336×2992 |
| corner_bg | 表格左上角交叉按钮 | 1024×1024 | stretch | 1024×1024 |
| button_bg | 按钮表面纹理 | 64×64 | tile | 64×64 |
| statusbar_bg | 底部状态栏 | 2050×160 | stretch | 2055×158 |
| float_bg | 悬浮窗背景图（可选） | 250×330 | stretch | - |
| settings_bg | 设置弹窗背景图（可选） | 680×560 | stretch | - |

图片模式：
- `stretch` — 拉伸填充整个控件
- `tile` — 小图循环平铺（适合纹理）
- `center` — 原图居中不缩放

### [colors] — 颜色体系

颜色值支持：`#RRGGBB`（十六进制）、`rgba(r,g,b,a)`（半透明）、`transparent`

#### 背景层次

| 颜色 key | 说明 |
|----------|------|
| main_bg | 窗口 / 主区域底色 |
| widget_bg | 输入框、表格主体背景色 |
| alt_row_bg | 表格交替行背景 |
| statusbar_bg | 底部状态栏背景 |

#### 文字颜色

| 颜色 key | 说明 |
|----------|------|
| text_primary | 正文、标签、按钮文字 |
| text_secondary | 辅助说明、状态栏消息 |
| text_disabled | 禁用状态文字 |
| table_text | 表格内文字颜色 |

#### 边框颜色

| 颜色 key | 说明 |
|----------|------|
| border | 默认边框 |
| border_hover | 鼠标悬停时的边框 |
| border_focus | 输入框获得焦点时的边框 |
| border_disabled | 禁用状态边框 |

#### 交互状态

| 颜色 key | 说明 |
|----------|------|
| hover_bg | 鼠标悬停时控件的背景 |
| pressed_bg | 按钮按下时的背景 |
| selection_bg | 表格 / 下拉框选中项背景 |

#### 语义色

| 颜色 key | 说明 |
|----------|------|
| win | 手动按钮阶段 2（胜）的颜色 |
| lose | 手动按钮阶段 2（负）的颜色 |
| coin | 手动按钮阶段 0（硬币）的颜色 |
| turn | 手动按钮阶段 1（先后攻）的颜色 |
| start_bg | "启动" 按钮的颜色 |
| warning_bg | "终止等待" 按钮的颜色 |
| muted_bg | 辅助 / 弱化按钮的颜色 |

#### 分割器与装饰

| 颜色 key | 说明 |
|----------|------|
| splitter | 分割器拖拽手柄颜色 |
| splitter_hover | 分割器手柄悬停颜色 |
| header_accent | 表头底部 2px 装饰线颜色 |

#### 下拉框与弹窗

| 颜色 key | 说明 |
|----------|------|
| combo_bg | 下拉框背景色 |
| combo_border | 下拉框边框色 |
| msgbox_bg | 消息弹窗背景色 |

#### 细粒度控件配色

| 颜色 key | 对应控件 |
|----------|---------|
| button_bg / button_border | QPushButton 默认背景 / 边框 |
| button_hover_bg | QPushButton 鼠标悬停背景 |
| button_pressed_bg | QPushButton 鼠标按下背景 |
| button_disabled_bg | QPushButton 禁用状态背景 |
| input_bg | QLineEdit 默认背景 |
| input_focus_bg | QLineEdit 获得焦点背景 |
| input_disabled_bg | QLineEdit 禁用背景 |
| table_grid | 表格网格线颜色 |
| table_alt_bg | 表格交替行背景（alternate-background-color） |
| table_item_bg | 单元格默认背景 |
| table_item_alt_bg | 交替行单元格背景 |
| table_selection_bg | 表格选中行背景 |
| header_v_bg / header_v_border | 垂直表头背景 / 边框 |
| corner_bg / corner_border | 表格左上角按钮背景 / 边框 |
| scrollbar_handle | 滚动条滑块颜色 |
| scrollbar_handle_hover | 滚动条滑块悬停颜色 |
| combo_body_bg | 下拉框本体背景 |
| combo_list_bg | 下拉框弹出列表背景 |

## 字体

主题可以嵌入自定义字体文件（`.ttf`、`.otf`、`.ttc`），放在 `assets/` 目录下，在 `theme.toml` 中配置即可。字体只需注册一次（`[[assets.fonts]]`），然后在 `font_family` 里按优先级引用。

macaron 主题内置了两款 OFL 协议的开源字体：

| 字体 | 风格 | 协议 |
|------|------|------|
| Yozai | 悠哉，松驰手写（主字体） | OFL 1.1 |
| DymonShouXieTi | 呆萌手写体，圆润可爱 | OFL 1.1 |
| LXGW WenKai | 霞鹜文楷，温润手写 | OFL 1.1 |

OFL（SIL Open Font License）允许免费使用、嵌入、再分发，但字体文件本身不得单独售卖。使用 OFL 字体时，需要将许可证文件一并放入 `assets/`。

## 纯色主题 vs 图片纹理主题

- **纯色主题**（如 dark / light）：`[assets.images]` 中所有 `file = ""`，完全依赖 `[colors]` 中的纯色
- **图片纹理主题**（如 macaron）：`[assets.images]` 中填入实际图片文件名，QSS 会自动用 `border-image` 覆盖纯色背景

两种主题共用同一份 `style.qss` 模板，差异完全由 `theme.toml` 控制。

## 用 AI 生成主题

如果你不懂配色也没关系，把这项工作交给 AI。以下是完整流程：

### 第 1 步：确定风格

先想清楚你想要什么感觉，用几个关键词描述即可。例如：

- "赛博朋克，霓虹紫和青色，暗色背景"
- "森林系，墨绿和米白，清新自然"
- "复古像素风，8-bit 配色，暖色调"
- "海洋深蓝渐变，珊瑚点缀，沉稳宁静"

不确定也没关系，直接让 AI 帮你发散：

> 我想为 MD Stats 做一个自定义主题，你能推荐 5 种风格方案吗？每种方案给出风格关键词、主色调和适用场景。

### 第 2 步：确定配色

有三种方式让 AI 帮你定配色：

**方式 A：文字描述风格**

> 请根据以下风格描述，为 MD Stats 生成完整的 theme.toml 颜色配置：
>
> 风格：【你的风格关键词】
>
> 要求：
> - 所有颜色值使用 #RRGGBB 格式，必须带引号
> - 背景色要分层：main_bg 最深，widget_bg 次之，statusbar_bg 可以再深一些
> - 文字色在深色背景上要保证可读性，浅色背景同理
> - 语义色（win/lose/coin/turn）要直观：胜=绿，负=红，硬币=金，先后攻=蓝
> - 边框色要比背景色略亮，hover 时再亮一些
> - 输出完整的 [colors] 部分，包含所有 key

**方式 B：从参考图提取配色**

找到一张你喜欢的风格图片（壁纸、UI 截图、摄影作品等），发给 AI：

> 这张图片的风格我很喜欢，请从中提取配色，生成 MD Stats 的 theme.toml [colors] 配置。
> 要求：
> - 背景色从图片的暗部区域取
> - 文字色从图片的亮部区域取
> - 语义色和强调色从图片中有辨识度的色彩取
> - 所有颜色使用 #RRGGBB 格式，必须带引号
> - 输出完整的 [colors] 部分

**方式 C：让 AI 生成预览图再提取配色**

如果你连参考图都没有，可以让 AI 先生成一张风格预览图，再从图上提取配色：

> 请生成一张桌面应用 UI 的风格预览图：暗色调，赛博朋克风格，霓虹紫和青色点缀。
> 然后从这张图中提取配色，生成 MD Stats 的 theme.toml [colors] 配置。
> 所有颜色使用 #RRGGBB 格式，必须带引号。

### 第 3 步：制作背景图片（可选）

纯色主题到此就完成了。如果你想要图片纹理主题（像 macaron 那样），可以让 AI 根据配色生成素材图：

> 请根据以下配色方案，为 MD Stats 生成背景图片：
> - main_bg.png：1100×700，主窗口全幅背景，风格：【你的风格】
> - panel_bg.png：1100×50，顶部和底部面板条
> - table_bg.png：1080×480，表格背景，要比面板略浅
> - header_bg.png：1080×32，表头栏
> - row_header_bg.png：32×480，行号栏
> - corner_bg.png：32×32，左上角按钮
> - button_texture.png：64×64，按钮纹理，可无缝平铺
> - statusbar_bg.png：1100×30，底部状态栏
>
> 配色：main_bg=#0d0221, widget_bg=#150535, ...

生成后把图片放到 `assets/` 目录，然后在 `theme.toml` 的 `[assets.images]` 中填入文件名。

**从一张大图切分**：如果你让 AI 生成了一张完整的主窗口风格图，也可以让 AI 按上述尺寸切分：

> 请将这张图片按以下尺寸切分，分别保存：
> - main_bg.png：1100×700（整张图）
> - panel_bg.png：取顶部 50px 高度
> - table_bg.png：取中间 480px 高度
> - header_bg.png：取表格顶部 32px
> - statusbar_bg.png：取底部 30px
> - row_header_bg.png：取左侧 32px 宽，高 480px
> - corner_bg.png：取左上角 32×32

切分后在 `[assets.images]` 中填入对应文件名即可。

### 第 4 步：用 AI 更新 theme.toml 颜色

拿到 AI 生成的配色后，让它直接写入文件：

> 把以下颜色配置更新到 themes/my-theme/theme.toml 的 [colors] 部分，保留原有注释和分组结构，只替换颜色值：
>
> 【粘贴 AI 生成的配色】

或者你手动复制粘贴也行——`theme.toml` 的 `[colors]` 部分每个 key 都有注释，对应替换即可。

### 第 5 步：验证效果

1. 确认 `config.toml` 中 `theme = "my-theme"`
2. 启动程序查看效果
3. 如果不满意，把截图发给 AI 并描述哪里需要调整，比如"背景太暗了""按钮颜色太跳"，让 AI 修改后重新替换

### 完整示例

**从零开始，用 AI 制作一个赛博朋克主题：**

```
你：我想做一个"赛博朋克风格"的主题，深紫和霓虹青为主

AI：以下是完整配色方案：
    main_bg = "#0d0221"
    widget_bg = "#150535"
    ...

你：把这套配色更新到 themes/cyberpunk/theme.toml

AI：（直接修改文件，保留注释结构）
```

## 注意事项

- `style.qss` 文件直接复制内置主题的即可，除非你需要深度定制
- `theme.toml` 中未定义的 key 会自动回退到内置默认值（亮色主题），不会崩溃
- 颜色值必须带引号，如 `main_bg = "#f5f6fa"`
- 图片放在 `assets/` 下，建议 PNG 格式
- 标题栏图标命名固定为 `title_min.png`、`title_close.png`，缺失时会自动用矢量绘制
