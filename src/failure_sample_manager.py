"""最佳失败样本管理器 — 自动保留最接近成功的失败样本。

================================================================================
设计目的
================================================================================

当以下情况发生时，识别结果可能长期低于阈值导致识别失败：
    - 游戏更新导致字体/UI 变化
    - 模板素材失效
    - ROI 偏移
    - 分辨率兼容问题

由于开发者通常无法复现用户环境，因此需要保留最有价值的失败样本，
便于后续分析与模板更新。

================================================================================
核心算法
================================================================================

每个识别项（target）在单轮（一局对局）内独立维护 Top-1 失败样本：

    置信度区间:
        0.0 ─── record_threshold ─── match_threshold ─── 1.0
           │  区间A（忽略）  │   区间B（保存最佳）  │ 区间C（成功）│

    consider() 的 4 个分支（详见 PRD §8）:
        分支1: confidence >= threshold → 阶段内成功，删除本阶段失败样本
        分支2: confidence < record_threshold → 低于记录下限，忽略
        分支3: 不优于当前最佳 → 忽略
        分支4: 首次记录或更优 → 先写新文件，再删旧文件

================================================================================
线程安全
================================================================================

StatsWorker 和 RankWorker 运行在不同线程中，共用同一个管理器实例。
所有涉及缓存读写和文件操作的方法都通过 threading.Lock 保护。

================================================================================
文件存储
================================================================================

目录: screenshots/debug/
格式: {target}_{confidence:.2f}_{YYYYMMDD}_{HHMMSS}.png + .toml

每个 target 仅保留一个文件（磁盘上最多一个 PNG + 一个 TOML）。
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.config import get_project_root, load_config
from src import logger as _log
from ui.about_dialog import VERSION


# =============================================================================
# FailureSampleManager — 线程安全的最佳失败样本管理器
# =============================================================================

class FailureSampleManager:
    """管理失败样本的保存、替换和清理。

    什么是"失败样本"？
        当识别置信度不够高、没达到"识别成功"的门槛，但又离成功很接近时，
        这张截图就是一份"失败样本"。它可以帮助开发者分析为什么识别失败，
        是因为字体变了？UI 布局变了？还是模板本身需要更新？

    两个线程共用同一个实例：
        - StatsWorker: 三阶段检测（8 个 target）
        - RankWorker: 段位图标检测（2 个 target）

    工作流程示例（以硬币检测为例）：
        用户设置 threshold=0.80, offset=0.10 → record_threshold=0.70

        采样1: coin_win 匹配置信度 = 0.72
               → 0.72 在 [0.70, 0.80) 区间内（"接近成功"）
               → 保存截图 + TOML 到 screenshots/debug/coin_win_0.72_xxx.png

        采样2: coin_win = 0.75
               → 比 0.72 更接近成功 → 删除旧的 0.72 文件，保存新的 0.75

        采样3: coin_win = 0.88
               → 0.88 >= 0.80，识别成功！
               → 删除 0.75 的失败样本（既然最终识别成功了，临时失败没有诊断价值）

    属性:
        _enabled   — 是否启用（来自 config.toml [debug].save_failure_samples）
        _offset    — 置信度偏移量（来自 config.toml [debug].failure_sample_offset）
        _best      — 内存缓存 {target: (confidence, file_stem)}
        _lock      — 线程锁
        _debug_dir — screenshots/debug/ 目录路径
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """初始化管理器，从 config.toml 读取设置。

        Args:
            config: 配置字典。为 None 时自动调用 load_config() 加载。
        """
        if config is None:
            config = load_config()
        dbg = config.get("debug", {})
        self._enabled: bool = dbg.get("save_failure_samples", False)
        self._offset: float = dbg.get("failure_sample_offset", 0.10)

        # 内存缓存：{target: (confidence, file_stem)}
        # 生命周期 = 一轮对局，clear_cache() 清空
        self._best: dict[str, tuple[float, str]] = {}

        # 线程锁：保护 _best 和文件操作
        self._lock = threading.Lock()

        # 输出目录
        self._debug_dir: Path = get_project_root() / "screenshots" / "debug"

    # =========================================================================
    # 公开接口
    # =========================================================================

    def is_enabled(self) -> bool:
        """检查功能是否启用（供调用方在循环外快速判断，避免不必要开销）。"""
        return self._enabled

    def consider(
        self,
        target: str,
        confidence: float,
        screenshot: np.ndarray,
        threshold: float,
        extra_meta: dict[str, Any] | None = None,
    ) -> None:
        """提交一次检测结果，内部判断是否需要保存/替换/删除失败样本。

        这是管理器的核心方法。每次截图+识别后都要调用一次，
        告诉管理器"某个识别项的匹配置信度是多少"。
        管理器内部自动判断应该保存、替换、删除还是忽略。

        线程安全：内部持有 _lock，两个线程同时调用也不会冲突。

        Args:
            target: 识别项名称。
                    三阶段检测用: coin_win, coin_lose, turn_first, turn_second,
                                result_win, result_lose, rank_up, rank_down
                    段位检测用: my_rank_icon, opponent_rank_icon
            confidence: 本次匹配置信度 (0.0~1.0)。
                        注意：这是该 target 自己的分数，不是所有模板的最高分。
                        例如调用 consider("coin_lose", 0.18) 时传 0.18 而不是 0.72。
            screenshot: 完整游戏截图（BGR 格式 numpy 数组）。
                        保留整张截图而不是裁剪 ROI，便于定位 UI 整体变化。
            threshold: 当前识别阈值。
                       三阶段检测用 detection.confidence_threshold（默认 0.80），
                       段位图标用 rank_detection.confidence_threshold（默认 0.70）。
            extra_meta: 额外元数据字典，会写入同名的 .toml 文件。可包含：
                all_scores       — {模板名: 分数}，所有候选模板的匹配分
                matched_template — 实际匹配到的模板文件名
                roi_name         — ROI 配置段名，如 "coin"
                roi              — 本次使用的 ROI 坐标 [x, y, w, h]
                roi_source       — ROI 来源: "preset"（预设）/ "fullscreen"（全图兜底）
                client_size      — 游戏窗口客户区尺寸，如 "1920x1080"
                window_rect      — 窗口屏幕坐标，如 "0,0,1920,1080"
                tier_detected    — （段位图标专用）列投影识别到的等级 I~V
                tier_score       — （段位图标专用）等级识别置信度
        """
        # 功能关闭时静默跳过（调用方无需关心开关状态）
        if not self._enabled:
            return

        record_threshold = threshold - self._offset

        with self._lock:
            # ═══════════════════════════════════════════════════════
            # 分支 1: 阶段内识别成功 → 删除本阶段失败样本
            # ═══════════════════════════════════════════════════════
            if confidence >= threshold:
                if target in self._best:
                    old_stem = self._best[target][1]
                    self._safe_unlink(old_stem + ".png")
                    self._safe_unlink(old_stem + ".toml")
                    del self._best[target]
                    _log.write("SCRN",
                               f"已删除诊断截图: {target} ({confidence:.2f}>={threshold:.2f} 识别恢复)")
                return

            # ═══════════════════════════════════════════════════════
            # 分支 2: 低于记录下限 → 忽略
            # ═══════════════════════════════════════════════════════
            if confidence < record_threshold:
                return

            # ═══════════════════════════════════════════════════════
            # 分支 3: 不优于本阶段当前最佳 → 忽略
            # ═══════════════════════════════════════════════════════
            if target in self._best:
                if confidence <= self._best[target][0]:
                    return

            # ═══════════════════════════════════════════════════════
            # 分支 4: 首次记录或优于本阶段最佳 → 保存
            # ═══════════════════════════════════════════════════════

            # 查磁盘上有无该 target 的旧文件（上一轮残留）
            old_disk_stem = self._find_existing_file(target)

            # 查缓存中有无本阶段旧记录
            old_cache_stem = self._best[target][1] if target in self._best else None

            # 4.1 先写新文件（防崩溃：先写新再删旧）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_stem = f"{target}_{confidence:.2f}_{timestamp}"

            # 保存 PNG
            png_saved = self._save_png(screenshot, new_stem)
            if not png_saved:
                return  # PNG 保存失败（磁盘满等），不继续

            # 保存 TOML
            self._save_toml(target, confidence, threshold, record_threshold,
                            new_stem, extra_meta)

            # 4.2 更新内存
            old_conf = self._best[target][0] if target in self._best else None
            self._best[target] = (confidence, new_stem)

            # 4.3 最后删旧文件（先写新再删旧，崩溃时至少保留一个）
            for stem in [old_cache_stem, old_disk_stem]:
                if stem and stem != new_stem:
                    self._safe_unlink(self._debug_dir / f"{stem}.png")
                    self._safe_unlink(self._debug_dir / f"{stem}.toml")

            if old_cache_stem or old_disk_stem:
                prev = f"{old_conf:.2f}" if old_conf is not None else "?"
                _log.write("SCRN",
                           f"已更新诊断截图: {target} ({prev}→{confidence:.2f})")
            else:
                _log.write("SCRN",
                           f"已保存诊断截图: {target} ({confidence:.2f}/{threshold:.2f})")

    def clear_cache(self) -> None:
        """一轮结束时调用。清空内存缓存，磁盘文件不动。

        线程安全：内部持有 _lock。
        """
        with self._lock:
            self._best.clear()

    # =========================================================================
    # 内部辅助方法
    # =========================================================================

    def _find_existing_file(self, target: str) -> str | None:
        """扫描 debug/ 目录，查找该 target 的已有文件（上一轮残留）。

        文件名格式为 {target}_{confidence}_{timestamp}.png，
        通过前缀匹配定位。

        Args:
            target: 识别项名称。

        Returns:
            文件 stem（不含扩展名）或 None。
        """
        try:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        prefix = target + "_"
        for png_path in self._debug_dir.glob(f"{prefix}*.png"):
            return png_path.stem  # 返回不带扩展名的文件名
        return None

    def _save_png(self, screenshot: np.ndarray, stem: str) -> bool:
        """保存完整游戏截图为 PNG。

        使用 cv2.imencode + write_bytes 避免中文路径问题。

        Args:
            screenshot: BGR 格式 numpy 数组。
            stem: 文件名（不含扩展名）。

        Returns:
            True 表示保存成功，False 表示失败。
        """
        try:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            _log.write("SCRN", f"无法创建 debug 目录，失败样本保存已降级")
            return False

        filepath = self._debug_dir / f"{stem}.png"

        # 确保内存连续（OpenCV 要求）
        src = screenshot.copy() if not screenshot.flags['C_CONTIGUOUS'] else screenshot

        success, buf = cv2.imencode('.png', src)
        if not success:
            _log.write("SCRN", f"失败样本 PNG 编码失败: {stem}")
            return False

        try:
            filepath.write_bytes(buf.tobytes())
            return True
        except OSError as e:
            _log.write("SCRN", f"失败样本 PNG 写入失败: {stem} ({e})")
            return False

    def _save_toml(
        self,
        target: str,
        confidence: float,
        threshold: float,
        record_threshold: float,
        stem: str,
        extra_meta: dict[str, Any] | None,
    ) -> None:
        """保存失败样本的 TOML 元数据文件。

        Args:
            target: 识别项名称。
            confidence: 本次匹配置信度。
            threshold: 当前识别阈值。
            record_threshold: 记录下限。
            stem: 文件名（不含扩展名）。
            extra_meta: 额外元数据字典。
        """
        filepath = self._debug_dir / f"{stem}.toml"
        meta = self._build_metadata(target, confidence, threshold,
                                     record_threshold, extra_meta)
        lines = self._format_toml(meta)
        try:
            filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            _log.write("SCRN", f"失败样本 TOML 写入失败: {stem} ({e})")

    @staticmethod
    def _build_metadata(
        target: str,
        confidence: float,
        threshold: float,
        record_threshold: float,
        extra_meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """构建 TOML 元数据字典。

        包含通用字段（所有 target）+ 可选专用字段（段位图标等）。
        """
        meta: dict[str, Any] = {
            "target": target,
            "confidence": round(confidence, 4),
            "threshold": round(threshold, 4),
            "record_threshold": round(record_threshold, 4),
            "version": VERSION,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        if extra_meta:
            # 匹配到的模板名
            if "matched_template" in extra_meta:
                meta["matched_template"] = extra_meta["matched_template"]

            # 所有候选模板的匹配分数
            if "all_scores" in extra_meta:
                meta["all_scores"] = {
                    k: round(v, 4) for k, v in extra_meta["all_scores"].items()
                }

            # ROI 信息
            if "roi_name" in extra_meta:
                meta["roi_name"] = extra_meta["roi_name"]
            if "roi" in extra_meta:
                meta["roi"] = extra_meta["roi"]
            if "roi_source" in extra_meta:
                meta["roi_source"] = extra_meta["roi_source"]

            # 窗口/分辨率信息
            if "client_size" in extra_meta:
                meta["client_size"] = extra_meta["client_size"]
            if "window_rect" in extra_meta:
                meta["window_rect"] = extra_meta["window_rect"]

            # 段位图标专用字段
            if "tier_detected" in extra_meta:
                meta["tier_detected"] = extra_meta["tier_detected"]
            if "tier_score" in extra_meta:
                meta["tier_score"] = round(extra_meta["tier_score"], 4)

        return meta

    @staticmethod
    def _format_toml(meta: dict[str, Any]) -> list[str]:
        """将元数据字典格式化为带注释的 TOML 文本。

        每个字段附带中文注释，方便开发者直接打开文件查看诊断信息。
        """
        # 每个字段对应的中文注释
        _COMMENTS: dict[str, str] = {
            "target":           "识别项名称",
            "confidence":       "本次匹配置信度 (0~1)",
            "threshold":        "识别成功阈值 (>= 此值视为成功)",
            "record_threshold": "记录下限 (阈值 − 偏移量)，匹配度低于此值不记录",
            "matched_template": "最佳匹配的模板文件路径",
            "roi_name":         "ROI 配置段名",
            "roi":              "本次使用的 ROI 坐标 [x, y, w, h]",
            "roi_source":       'ROI 来源: "preset"=预设 / "fullscreen"=全图兜底',
            "client_size":      "游戏窗口客户区尺寸 (宽x高)",
            "window_rect":      "窗口屏幕坐标 (多显示器 DPI 排查)",
            "version":          "软件版本号",
            "time":             "保存时间",
            "tier_detected":    "列投影识别到的等级 (I~V，仅段位图标)",
            "tier_score":       "等级识别置信度 (仅段位图标)",
        }

        lines: list[str] = [
            "# ============================================================",
            "# 最佳失败样本元数据 — 由 MD Stats 自动生成",
            "#",
            '# 这个文件记录了识别「接近成功」但未达阈值的一次检测。',
            "# 可用于排查以下问题：",
            "#   • 游戏更新导致字体/UI 变化",
            "#   • 模板素材失效",
            "#   • ROI 偏移",
            "#   • 分辨率兼容问题",
            "# ============================================================",
            "",
        ]

        # 分组输出，组间空行分隔
        # 每组只在至少有一个非空字段时才显示
        _GROUPS: list[tuple[str, list[str]]] = [
            ("识别结果", ["target", "confidence", "threshold", "record_threshold",
                          "matched_template"]),
            ("搜索区域", ["roi_name", "roi", "roi_source"]),
            ("运行环境", ["client_size", "window_rect", "version", "time"]),
            ("段位等级（仅段位图标）", ["tier_detected", "tier_score"]),
        ]

        for group_name, keys in _GROUPS:
            written = False
            for key in keys:
                if key in meta:
                    val = meta[key]
                    # 跳过空值（仅当值为非空字符串/非空列表/非零数值时才显示）
                    if isinstance(val, str) and not val:
                        continue
                    if isinstance(val, list) and not val:
                        continue

                    if not written:
                        lines.append(f"# ---- {group_name} ----")
                        written = True
                    comment = _COMMENTS.get(key, "")
                    if isinstance(val, bool):
                        lines.append(f"{key} = {str(val).lower()}  # {comment}")
                    elif isinstance(val, str):
                        lines.append(f'{key} = "{val}"  # {comment}')
                    elif isinstance(val, (int, float)):
                        lines.append(f"{key} = {val}  # {comment}")
                    elif isinstance(val, list):
                        lines.append(f"{key} = {val}  # {comment}")
            if written:
                lines.append("")

        # [all_scores] 子表
        if "all_scores" in meta:
            lines.append("# ---- 所有候选模板匹配分数 ----")
            lines.append("# 健康的识别：正确模板高分、其他模板低分（差距大 = 区分度高）")
            lines.append("# 需排查：两个模板分数接近——说明模板区分度不够，考虑重新截取")
            lines.append("# 需排查：全部模板分数都很低——整体环境问题（分辨率/素材失效）")
            lines.append("[all_scores]")
            for k, v in meta["all_scores"].items():
                lines.append(f"{k} = {v}")
            lines.append("")

        return lines

    @staticmethod
    def _safe_unlink(path: str | Path) -> None:
        """安全删除文件，文件不存在时静默跳过。

        用户手动删除 debug/ 下的文件、程序崩溃后残留、
        或其他进程占用文件时都不会因此崩溃。
        """
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass  # 文件被占用时静默跳过
