# EXE 打包说明

本文档分两种构建方式：**手动本地打包**（推荐 CI 不可用时使用）和 **CI 自动打包**（日常使用）。

## 前置条件

- Python ≥ 3.11
- uv（Python 依赖管理器和虚拟环境管理器）

## 方式一：手动本地打包

### 1. 编译 .ui 文件

修改 `main_window.ui` 后，必须重新编译为 Python 代码。`pyside6-uic`（Qt User Interface Compiler）将 XML 界面文件转为纯 Python 代码，避免运行时 XML 解析开销。

```bash
.venv/Scripts/pyside6-uic.exe ui/main_window.ui -o ui/main_window_ui.py
```

### 2. 同步依赖

```bash
uv sync --frozen
```

`--frozen` 严格按 `uv.lock` 中的精确版本安装，确保本地和 CI 构建结果一致。

### 3. 执行打包

```bash
.venv/Scripts/pyinstaller.exe main.py \
  --name MDStats \
  --icon app_icon.ico \
  --noconsole \
  --noupx \
  --contents-directory .runtime \
  --noconfirm
```

各参数含义：

| 参数 | 作用 |
|------|------|
| `--name MDStats` | EXE 文件名 |
| `--icon app_icon.ico` | 程序图标 |
| `--noconsole` | 不弹出命令行窗口 |
| `--noupx` | 不使用 UPX 压缩（兼容性更好） |
| `--contents-directory .runtime` | 依赖文件放在 `.runtime/` 目录 |
| `--noconfirm` | 自动覆盖旧产物，不询问 |

打包产物在 `dist/MDStats/`：
- `MDStats.exe` — 主程序
- `.runtime/` — 运行时依赖（PySide6、OpenCV、numpy 等）

### 4. 组装发布目录

`themes/`、`csv/`、`resource/`、`config.toml` 等放在 EXE 同级目录，不打包进 EXE，方便用户自行修改。

```bash
mkdir -p dist/release
cp dist/MDStats/MDStats.exe dist/release/
cp -r dist/MDStats/.runtime dist/release/
cp -r themes dist/release/
cp -r csv dist/release/
cp -r resource dist/release/
cp config.toml dist/release/
cp .app_state.json dist/release/
cp docs/README_release.md dist/release/README.md
```

### 5. 打包 ZIP

```bash
cd dist/release
.venv/Scripts/python.exe -c "
import zipfile, os
with zipfile.ZipFile('../MDStats-vX.Y.Z.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('.'):
        for f in files:
            fp = os.path.join(root, f)
            if f.endswith('.pyc') or '__pycache__' in fp:
                continue
            arcname = os.path.relpath(fp, '.')
            zf.write(fp, arcname)
"
```

将 `vX.Y.Z` 替换为实际版本号。

## 方式二：CI 自动打包（推荐）

本地只需打 tag 推送，GitHub Actions 自动完成编译、打包、组装、创建 Release。

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

CI 工作流文件：`.github/workflows/release.yml`。推送 tag 后到 `https://github.com/learbox/mdstats_py/actions` 查看进度。完成后在 Releases 页面出现草稿，检查 ZIP 内容无误后手动点击 Publish release 发布。

如果 CI 未触发（如网络问题），改为手动本地打包上传。

## 发布包结构

```
MDStats-vX.Y.Z.zip
└── MDStats/
    ├── MDStats.exe              # 主程序
    ├── .runtime/                # 运行时依赖（PyInstaller 生成）
    ├── config.toml              # 配置文件
    ├── .app_state.json          # 窗口状态持久化
    ├── csv/                     # 对战数据
    ├── resource/templates/      # 模板图片
    ├── themes/                  # 主题目录（用户可自定义）
    └── README.md                # 用户说明
```

## ⚠ 重要警告

- **`main_window_ui.py` 是 pyside6-uic 自动生成的编译产物，严禁直接修改！**
  你、AI、任何人如果直接改这个文件，所有改动会在下次运行 `pyside6-uic` 编译 .ui 时**被彻底覆盖、无法恢复**。要改界面请打开 `main_window.ui`（Qt Designer），改完后再重新编译 `main_window_ui.py`。`main_window.py` 中 import 的行上方也有一条相同的中文警告，确保你或任何 AI 助手编辑代码时第一眼就能看到。

- `main_window.ui` 是源文件，仅用于开发和重新编译，**不需要**放入 EXE 包中。

- `themes/`、`csv/`、`resource/` 不打包进 EXE，用户可自行修改。

- 打包前确认 `ui/about_dialog.py` 中的 `VERSION` 已更新。

- CI 和本地打包前都应执行 `uv sync --frozen`，确保依赖版本一致。
