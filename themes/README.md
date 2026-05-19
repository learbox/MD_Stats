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
    ├── main_bg.png     # 主窗口背景图
    ├── panel_bg.png    # 面板背景图
    ├── table_bg.png    # 表格背景图
    ├── header_bg.png   # 表头背景图
    ├── button_texture.png  # 按钮纹理
    ├── statusbar_bg.png    # 状态栏背景图
    ├── app_icon.png        # 程序图标
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

**背景图片**：全部可选，`file = ""` 时用纯色填充

| 配置项 | 对应软件位置 | 建议尺寸 | 模式建议 |
|--------|------------|---------|---------|
| main_bg | 主窗口全幅背景 | 1100×700 | stretch |
| panel_bg | 顶部控制栏 + 底部按钮面板 | 1100×50 | stretch |
| table_bg | 统计表格 + 对战记录表格 | 1080×480 | stretch |
| header_bg | 表格列标题栏 | 1080×32 | stretch |
| button_bg | 按钮表面纹理 | 32×32 | tile |
| statusbar_bg | 底部状态栏 | 1100×30 | stretch |

图片模式：
- `stretch` — 拉伸填充整个控件
- `tile` — 小图循环平铺（适合纹理）
- `center` — 原图居中不缩放

### [colors] — 颜色体系

颜色值支持：`#RRGGBB`（十六进制）、`rgba(r,g,b,a)`（半透明）、`transparent`

#### 基础颜色（27 个）

| 颜色 key | 说明 |
|----------|------|
| main_bg | 窗口 / 主区域底色 |
| widget_bg | 输入框、表格主体背景色 |
| alt_row_bg | 表格交替行背景 |
| statusbar_bg | 底部状态栏背景 |
| text_primary | 正文、标签、按钮文字 |
| text_secondary | 辅助说明、状态栏消息 |
| text_disabled | 禁用状态文字 |
| table_text | 表格内文字颜色 |
| border | 默认边框 |
| border_hover | 鼠标悬停时的边框 |
| border_focus | 输入框获得焦点时的边框 |
| border_disabled | 禁用状态边框 |
| hover_bg | 鼠标悬停时控件的背景 |
| pressed_bg | 按钮按下时的背景 |
| selection_bg | 表格 / 下拉框选中项背景 |
| win | 手动按钮阶段 2（胜）的颜色 |
| lose | 手动按钮阶段 2（负）的颜色 |
| coin | 手动按钮阶段 0（硬币）的颜色 |
| turn | 手动按钮阶段 1（先后攻）的颜色 |
| start_bg | "启动" 按钮的颜色 |
| warning_bg | "终止等待" 按钮的颜色 |
| muted_bg | 辅助 / 弱化按钮的颜色 |
| splitter | 分割器拖拽手柄颜色 |
| splitter_hover | 分割器手柄悬停颜色 |
| header_accent | 表头底部 2px 装饰线颜色 |
| combo_bg | 下拉框背景色 |
| combo_border | 下拉框边框色 |
| msgbox_bg | 消息弹窗背景色 |

#### 细粒度控件配色（21 个）

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

## 纯色主题 vs 图片纹理主题

- **纯色主题**（如 dark / light）：`[assets.images]` 中所有 `file = ""`，完全依赖 `[colors]` 中的纯色
- **图片纹理主题**（如 macaron）：`[assets.images]` 中填入实际图片文件名，QSS 会自动用 `border-image` 覆盖纯色背景

两种主题共用同一份 `style.qss` 模板，差异完全由 `theme.toml` 控制。

## 注意事项

- `style.qss` 文件直接复制内置主题的即可，除非你需要深度定制
- `theme.toml` 中未定义的 key 会自动回退到内置默认值（亮色主题），不会崩溃
- 颜色值必须带引号，如 `main_bg = "#f5f6fa"`
- 图片放在 `assets/` 下，建议 PNG 格式
- 标题栏图标命名固定为 `app_icon.png`、`title_min.png`、`title_close.png`，缺失时会自动用矢量绘制
