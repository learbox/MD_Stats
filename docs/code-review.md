# 代码审查报告

## 🔴 必须修复

- [x] **1. Bug：`_unlock_deck()` 设置了错误的按钮文本** — `ui/main_window.py:1006` — 解锁后应显示"锁定卡组"，而非"修改卡组"
- [x] **2. 死代码：`_is_dark_theme()` 定义后从未调用** — `ui/main_window.py:273` — 已删除
- [x] **3. 死代码：两个 QSS 工具函数从未调用** — `src/theme_loader.py:336-367` — `_inject_qss_property()` / `_remove_qss_property()` 已删除
- [x] **4. 死代码：重复的空注释区块** — `ui/main_window.py:1363` — 已删除
- [x] **5. `pyproject.toml` `requires-python = ">=3.14"` 不切实际** — `pyproject.toml:4` — 改为 `>=3.11`
- [x] **6. `add_record()` 静默数据丢失风险** — `src/recorder.py:186` — 新增映射验证 + warning 日志

## 🟡 建议修复

- [x] **7. 重复的窗口最小化检测代码** — `src/stats_worker.py:158/179` — 提取为 `_handle_pause()` 方法
- [x] **8. 不一致的睡眠方式** — `src/stats_worker.py:115 vs 244` — 统一为 `_skip()`
- [x] **9. `_STATE_MAP` 每次调用时重新创建** — `src/stats_worker.py:260` — 提升为类属性 `_STAGE_MAP`
- [x] **10. `__init__` 与 `_on_reload_config` 主题应用逻辑大量重复** — `ui/main_window.py` — 提取 `_apply_theme_to_widgets()`，`_on_reload_config` 已复用
- [ ] **11. 重复的 `EnumWindows` 调用** — `src/capture.py:131/146/169` — 涉及 stats_worker 重构，暂缓
- [x] **12. `_build_theme()` 中无效的二次替换** — `src/theme_loader.py:278-279` — 已删除
- [x] **13. 函数命名混淆** — `src/detector.py:121/140` — `_load_from_disk` → `_read_template_file`，`_load_template` → `_get_cached_template`
- [x] **14. 硬编码字体 5 处重复** — `src/theme_loader.py` — 提取为 `_DEFAULT_FONT` 常量
- [x] **15. `pyproject.toml` 不必要的 `==` 版本锁** — `pyproject.toml:7-8` — 改为 `>=`
- [x] **16. `STATS_COLUMNS` 与 `compute_stats()` 输出顺序不一致** — `src/recorder.py` — 已对齐
- [ ] **17. `.get()` 多处传入重复的复杂默认值** — `ui/main_window.py` — 影响较小，暂缓

## 🟢 可选改进

- [ ] **18. `capture_screen()` 中 `monitor_index` 语义令人困惑** — `src/capture.py:246` — 需深入重构，暂缓
- [x] **19. `load_config()` 返回裸 `dict`** — `src/config.py:60` — 改为 `dict[str, Any]`
- [x] **20. 魔法数字缺少文档** — `ui/main_window.py` — `_BORDER_WIDTH`、定时器间隔加注释
- [ ] **21. 过多 `# type: ignore` 注释** — 全项目约 60 条 — 需逐条审查，工作量大
- [x] **22. `_on_about()` f-string 构建 HTML** — 已用 `html.escape()` 转义纯文本值
- [x] **23. `defaultdict` 延迟导入不符合惯例** — `src/recorder.py:279` — 移至模块顶层
- [x] **24. `@staticmethod` 装饰器不一致** — `ui/main_window.py` — `_lighter`/`_darker` 已有装饰器
- [ ] **25. `main_window.py` 过长（1464 行）** — 建议拆出 `ThemeManager`，可后续处理
- [x] **26. `add_record()` 和 `compute_stats()` 参数类型为裸 `list`** — 已有完整类型注解，误报
