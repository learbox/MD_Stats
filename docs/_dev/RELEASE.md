# 发布新版本流程

## 1. 确认改动已提交

```bash
git status          # 确保核心改动已提交（忽略 .app_state.json / config.toml 本地修改）
git log --oneline   # 确认提交链完整
```

## 2. 更新文档（如有必要）

- `docs/README_release.md` — 发行包附带的使用说明（配置项、功能列表需与当前版本一致）
- `docs/PRD.md` — 仅功能变更时更新
- `README.md` — 仅项目级描述变更时更新
- `themes/README.md` — 仅主题体系变更时更新
- `docs/TROUBLESHOOTING.md` — 新增常见问题时补充
- `CHANGELOG.md` — 每次发布前按版本号追加更新条目

## 3. 更新版本号

涉及 4 个文件，均用 grep 定位后修改：

| 文件 | 搜索定位 | 修改为 |
|------|---------|--------|
| `ui/about_dialog.py` | `grep '^VERSION ='` | `VERSION = "X.Y.Z"` |
| `pyproject.toml` | `grep '^version ='`（`[project]` 段下） | `version = "X.Y.Z"` |
| `uv.lock` | `grep -A1 'name = "mdstats-py"'`，下一行 | `version = "X.Y.Z"` |
| `docs/README_release.md` | 标题行 | `# MD Stats vX.Y.Z` |

版本号规则：
- 修复 bug → Z + 1（如 1.5.3 → 1.5.4）
- 新增小功能 → Z + 1
- 大功能 / 架构变更 → Y + 1

## 4. 提交版本号并打标签

```bash
git add ui/about_dialog.py pyproject.toml uv.lock docs/README_release.md
git commit -m "X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
```

## 5. 推送

```bash
git push origin main --tags
```

推送后 GitHub Actions 自动触发构建，生成 `MDStats.zip` 和 `MDStats.exe`。

## 6. 编写 Release Notes

> AI 注意：发版时请主动为本次发布编写 Release Notes（Markdown 格式），
> 方便用户快速粘贴到 GitHub Release 输入框。

查看两个版本之间的提交：

```bash
git log v上一版本..v新版本 --oneline
```

按以下 Markdown 模板整理（直接粘贴到 GitHub Release 输入框，支持 Markdown 渲染）：

```
## 新功能
- **功能名**：简述

## 改进
- 描述

## 修复
- 描述

## 代码质量
- 内部重构描述（用户不可见，可选）

## 已知问题
- 描述（如果当前版本存在未解决的 bug 或限制，在此列出）

---

> **注意**：v1.7.x 为最终功能版本，后续仅修 bug。识别问题 99% 源于模板不匹配——请优先检查模板是否在当前分辨率下截取。
```

## 7. 创建 GitHub Release

打开 `https://github.com/learbox/MD_Stats/releases/tag/vX.Y.Z`，粘贴 Release Notes，下载 CI 构建产物并上传为附件，点击发布。

注意：不要勾选「Set as latest release」之外的标签（Pre-release 仅限测试版）。

## 速查

```bash
# 一键：提交 → 版本号 → tag → 推送
git add <files> && git commit -m "<msg>"
# 修改版本号后：
git add ui/about_dialog.py pyproject.toml uv.lock docs/README_release.md && git commit -m "X.Y.Z" && git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin main --tags
```
