# 分支冻结原因：feature/macos-port

本分支已被冻结，原因：

- Master Duel (Yu-Gi-Oh!) 没有 macOS 版——科乐美从未发布过。
- macOS 版 MD Stats 属于伪需求，不存在可运行的目标程序。
- 分支中的跨平台代码（capture 重构、路径兼容、字体回退等）已通过 cherry-pick 合并到 main。
- 纯 macOS 部分（Quartz/AppKit 截图、NSScreen 窗口定位）保留在本分支作为参考，不再维护。

如将来科乐美发布 Mac 版 MD，可解冻此分支继续开发。

冻结于 2026-05-25
