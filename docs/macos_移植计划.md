# macOS 移植计划

## 现状

整个项目在 Windows 上运行良好，但以下模块依赖 Windows API，需要重构为跨平台。

## 需要改动的文件

### 1. `src/capture.py` — 窗口定位与截图（最大工作量）

**现状**：全部用 `pywin32`（`win32gui`）操作 Windows 窗口。

**方案**：用抽象层隔离平台差异。

```python
# capture_win.py    — Windows 实现（现有逻辑移过来）
# capture_mac.py    — macOS 实现（新建）
# capture.py        — 入口，自动选择平台实现
```

Windows API → macOS 等效：

| Windows (`pywin32`) | macOS (`Quartz`/`AppKit`) | 说明 |
|---------------------|--------------------------|------|
| `win32gui.EnumWindows(callback, lParam)` | `Quartz.CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)` | 枚举所有可见窗口 |
| `win32gui.GetWindowText(hwnd)` | `window_info.get("kCGWindowName", "")` | 窗口标题 |
| `win32gui.IsWindowVisible(hwnd)` | 窗口列表本身就是可见的，无需额外判断 | |
| `win32gui.IsIconic(hwnd)` | macOS 无"最小化"概念（只有隐藏），检测窗口是否在 Dock 中 | |
| `win32gui.GetClientRect(hwnd)` | `Quartz.CGRectGetWidth/Height(bounds)` | 窗口渲染区域 |
| `win32gui.ClientToScreen(hwnd, (0,0))` | `bounds.origin.x, bounds.origin.y` | 客户区屏幕坐标 |
| `win32gui.FindWindow` | 遍历 `CGWindowListCopyWindowInfo` 结果按标题匹配 | |

**截图**：`mss` 库本身跨平台（Windows 用 DirectX，macOS 用 CoreGraphics），不需要改。只需要提供正确的屏幕坐标区域。

**需要安装的依赖**：`pyobjc-framework-Quartz`（macOS 窗口信息查询）

### 2. `ui/main_window.py` — DWM 阴影/圆角 + Steam 启动

**现状**：
- `_apply_dwm_style()` — 调用 Windows DWM API 加阴影和圆角
- `_on_start()` — `os.startfile("steam://rungameid/1449850")`

**方案**：

| 功能 | Windows | macOS |
|------|---------|-------|
| 窗口阴影 | DWM `DwmExtendFrameIntoClientArea` | macOS 无边框窗口自动有阴影，什么都不做 |
| 窗口圆角 | `DwmSetWindowAttribute(33, 2)` | macOS 窗口默认圆角，什么都不做 |
| Steam 启动 | `os.startfile("steam://...")` | `subprocess.Popen(["open", "steam://rungameid/1449850"])` |

实现：`_apply_dwm_style()` 改名 `_apply_native_style()`，内部 `if os.name == "nt"` 判断。

### 3. `ui/config_dialog.py` 和 `ui/about_dialog.py` — DWM 圆角

两个弹窗各有一个 `_apply_dwm()` 方法。同上，非 Windows 时直接 return。

### 4. `ui/theme_manager.py` — macOS 原生样式的特殊处理

macOS 无边框窗口的标题栏区域可能需要额外留白（避免和系统菜单栏冲突），具体看实际效果。

### 5. 项目依赖

`pyproject.toml` 中 `pywin32` 需要标记为 Windows only：
```toml
dependencies = [
    ...
    "pywin32>=306; sys_platform == 'win32'",
    "pyobjc-framework-Quartz; sys_platform == 'darwin'",
]
```

## 不需要改动的部分

- **OpenCV** — 纯 Python + numpy，跨平台
- **PySide6** — Qt 官方跨平台
- **mss** — 截图库跨平台
- **主题系统** — 纯 Python 文件读写
- **CSV / 配置** — 纯 Python
- **stats_worker** — 只依赖 capture 模块

## 无法测试的问题

目前没有 macOS 设备，以下情况无法验证：

1. **窗口枚举 API** — `CGWindowListCopyWindowInfo` 返回的数据结构和 Windows `EnumWindows` 不同，字段名和返回值需要实测
2. **截图坐标** — macOS 的坐标系和 Windows 不同（原点在左下而非左上），需要验证 `mss` 对区域截图的坐标处理
3. **全屏游戏检测** — Master Duel 在全屏模式下是否仍然能被 `CGWindowListCopyWindowInfo` 枚举到
4. **字体渲染** — macOS 上 `font_family` 回退栈的实际效果
5. **权限** — macOS 可能需要用户授权"屏幕录制"权限才能截图

## 实现顺序

1. 抽象出 `capture_win.py` / `capture_mac.py`（纯函数，无类）
2. `capture.py` 改为平台分发入口
3. 修改 `main_window.py` / `config_dialog.py` / `about_dialog.py` 的平台判断
4. 更新 `pyproject.toml` 依赖
5. 找有 Mac 的朋友帮忙测试
