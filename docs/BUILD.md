# EXE 打包说明

## 前置条件

- Python ≥ 3.11
- PyInstaller（项目 venv 中已安装）
- uv（可选，用于同步依赖）

## 打包步骤

### 1. 编译 .ui 文件

修改 `main_window.ui` 后，必须重新编译为 Python：

```bash
.venv/Scripts/pyside6-uic.exe ui/main_window.ui -o ui/main_window_ui.py
```

### 2. 同步依赖

```bash
uv sync
```

### 3. 执行打包

```bash
pyinstaller main.py --name MDStats --icon app_icon.ico --noconsole --noupx --contents-directory .runtime --noconfirm
```

或直接用 uv：

```bash
uv run --with 'pyinstaller>=6.10,<7' pyinstaller main.py --name MDStats --icon app_icon.ico --noconsole --noupx --contents-directory .runtime --noconfirm
```

打包产物在 `dist/MDStats/` 目录。`main_window_ui.py` 会被 PyInstaller 自动检测并打包。

### 4. 组装发布目录

themes、csv、resource、config 等需要放在 exe 同级目录（不打包进 exe），以便用户自行修改。

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

### 5. 打包为 ZIP

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

## 发布包结构

```
MDStats/
├── MDStats.exe              # 主程序
├── .runtime/                # 运行时依赖（PyInstaller 生成）
├── config.toml              # 配置文件
├── .app_state.json          # 窗口状态持久化
├── csv/                     # 对战数据
├── resource/templates/      # 模板图片
├── themes/                  # 主题目录（用户可自定义）
└── README.md                # 用户说明（来自 docs/README_release.md）
```

## 注意事项

- `themes/`、`csv/`、`resource/` 不打包进 exe，用户可自行修改
- **`main_window_ui.py` 是 pyside6-uic 自动生成的编译产物，严禁手改。** 任何 AI 或人工对它的修改都会在下次编译 .ui 时被覆盖。所有界面修改必须在 `main_window.ui`（Qt Designer）中进行，然后重新编译
- `main_window.ui` 是源文件，仅用于开发和重新编译，**不需要**放入 exe 包中
- 打包前确认 `ui/meta.py` 中的版本号已更新
