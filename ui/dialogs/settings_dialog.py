"""设置对话框模块。

提供用户设置界面的完整实现，支持实时预览。
采用棱角分明的矩形设计风格。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QCheckBox,
    QLineEdit,
    QSlider,
    QButtonGroup,
    QScrollArea,
    QWidget,
    QSpinBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor, QIntValidator

from ui.widgets.switch_widget import SwitchWidget
from ui.styles.dialog_styles import DialogStyleFactory

if TYPE_CHECKING:
    from config.user_settings import UserSettings

logger = logging.getLogger("YandeViewer.UI.SettingsDialog")


# ============================================================================
# 设计令牌导入（模块级只读常量）
# ============================================================================


def _get_tokens() -> Optional[Any]:
    """安全获取设计令牌。"""
    try:
        from config.design_tokens import TOKENS

        return TOKENS
    except ImportError:
        logger.warning("设计令牌模块不可用，使用默认样式")
        return None


TOKENS: Final[Optional[Any]] = _get_tokens()


# ============================================================================
# 常量
# ============================================================================

SCORE_OPTIONS: Final[list[tuple[int, str]]] = [
    (0, "不限"),
    (5, "≥5"),
    (10, "≥10"),
    (15, "≥15"),
    (20, "≥20"),
    (30, "≥30"),
    (50, "≥50"),
]

RATING_CONFIGS: Final[list[tuple[str, str, str, str]]] = [
    ("s", "Safe", "rating_safe_bg", "rating_safe_text"),
    ("q", "Questionable", "rating_questionable_bg", "rating_questionable_text"),
    ("e", "Explicit", "rating_explicit_bg", "rating_explicit_text"),
]


# ============================================================================
# 工具函数
# ============================================================================


def _safe_attr(obj: Any, attr: str, default: Any = None) -> Any:
    """安全属性访问，obj 为 None 时直接返回默认值。"""
    if obj is None:
        return default
    return getattr(obj, attr, default)


def _clamp(value: int, min_val: int, max_val: int) -> int:
    """将 value 限制在 [min_val, max_val] 内。"""
    return max(min_val, min(max_val, value))


# ============================================================================
# 数据结构定义
# ============================================================================


@dataclass
class _DialogControls:
    """所有需要后续读取的控件引用，类型明确。"""

    score_group: Optional[QButtonGroup] = None
    score_buttons: dict[int, QPushButton] = field(default_factory=dict)
    custom_score_cb: Optional[QCheckBox] = None
    custom_score_entry: Optional[QLineEdit] = None
    rating_buttons: dict[str, QPushButton] = field(default_factory=dict)
    high_first_switch: Optional[SwitchWidget] = None
    preload_slider: Optional[QSlider] = None
    cache_slider: Optional[QSlider] = None
    workers_slider: Optional[QSlider] = None
    timeout_slider: Optional[QSlider] = None
    show_badge_switch: Optional[SwitchWidget] = None
    show_highlight_switch: Optional[SwitchWidget] = None
    threshold_spinbox: Optional[QSpinBox] = None


@dataclass(frozen=True)
class SliderSpec:
    """滑块配置规格。"""

    label: str
    min_val: int
    max_val: int
    default: int
    key: str  # 对应 _DialogControls 的属性名
    hint: str


# 性能面板滑块配置
PERF_SLIDERS: Final[list[SliderSpec]] = [
    SliderSpec(
        "预加载数量",
        5,
        30,
        15,
        "preload_slider",
        "推荐 15，调高可提升翻页流畅度，但会增加内存占用",
    ),
    SliderSpec(
        "缓存图片", 20, 100, 50, "cache_slider", "推荐 50，适合大多数设备使用"
    ),
    SliderSpec(
        "下载并发", 1, 5, 3, "workers_slider", "推荐 3，网络较好时可适当调高"
    ),
    SliderSpec(
        "超时时间",
        5,
        30,
        15,
        "timeout_slider",
        "推荐 15 秒，网络较慢时建议提高到 20 秒以上",
    ),
]


# ============================================================================
# 设置对话框
# ============================================================================


class SettingsDialog(QDialog):
    """设置对话框，支持实时预览。

    Signals:
        preview_requested: 请求预览设置变更，携带 UserSettings。
        settings_saved: 设置保存完成，携带 UserSettings。
    """

    preview_requested = pyqtSignal(object)
    settings_saved = pyqtSignal(object)

    DIALOG_WIDTH: int = 500
    DIALOG_HEIGHT: int = 660
    PREVIEW_DEBOUNCE_MS: int = 200
    PAGE_H_MARGIN: int = 20
    PAGE_V_MARGIN: int = 16
    SECTION_SPACING: int = 18
    ITEM_SPACING: int = 8
    SLIDER_ITEM_SPACING: int = 10

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        settings: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)

        # 懒加载设置类
        from config.user_settings import (
            UserSettings as _UserSettings,
            FilterSettings as _FilterSettings,
            PerformanceSettings as _PerformanceSettings,
            UISettings as _UISettings,
        )

        self._UserSettings = _UserSettings
        self._FilterSettings = _FilterSettings
        self._PerformanceSettings = _PerformanceSettings
        self._UISettings = _UISettings

        if settings is None:
            settings = _UserSettings()
        if settings is None:
            logger.error("UserSettings 类不可用")
            QTimer.singleShot(0, self.reject)
            return

        self.original_settings = settings
        self.current_settings = (
            settings.copy() if hasattr(settings, "copy") else settings
        )

        # 预提取常用属性，避免深层 _safe_attr 链
        self._orig_filter = _safe_attr(settings, "filter")
        self._orig_perf = _safe_attr(settings, "performance")
        self._orig_ui = _safe_attr(settings, "ui")

        # 样式工厂
        self.styles: Optional[DialogStyleFactory] = None
        if TOKENS is not None:
            self.styles = DialogStyleFactory(
                TOKENS.colors, TOKENS.typography, TOKENS.layout
            )

        # 控件引用（类型安全）
        self._controls: _DialogControls = _DialogControls()
        self._preview_timer: Optional[QTimer] = None

        self.setWindowTitle("设置")
        self.setFixedSize(self.DIALOG_WIDTH, self.DIALOG_HEIGHT)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        if TOKENS is not None:
            self.setStyleSheet(f"background-color: {TOKENS.colors.bg_base};")

        self._setup_ui()
        self._connect_preview_signals()
        self._center_on_parent()

        logger.debug("SettingsDialog 初始化完成")

    # ── 生命周期 ──────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cleanup()
        super().closeEvent(event)

    def _cleanup(self) -> None:
        """释放定时器等资源。"""
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None

        # 停止所有 SwitchWidget 动画
        for attr_name in (
            "high_first_switch",
            "show_badge_switch",
            "show_highlight_switch",
        ):
            sw = getattr(self._controls, attr_name, None)
            if sw is not None and hasattr(sw, "stop_animation"):
                sw.stop_animation()

    def _center_on_parent(self) -> None:
        parent = self.parent()
        if parent is not None:
            try:
                geo = parent.geometry()
                x = geo.x() + (geo.width() - self.width()) // 2
                y = geo.y() + (geo.height() - self.height()) // 2
                self.move(x, y)
            except Exception:
                logger.debug("居中定位失败", exc_info=True)

    # ── UI 构建 ───────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(
            self.PAGE_H_MARGIN,
            self.PAGE_V_MARGIN,
            self.PAGE_H_MARGIN,
            self.PAGE_V_MARGIN,
        )

        self._build_title(root)

        scroll = self._build_scroll_area()
        container = QWidget()
        body = QVBoxLayout(container)
        body.setSpacing(self.SECTION_SPACING)
        body.setContentsMargins(0, 0, 4, 0)

        self._build_section_header(body, "筛选设置", "控制显示内容的范围与排序")
        self._build_filter_panel(body)

        self._build_section_header(body, "性能设置", "影响加载速度与内存占用")
        self._build_performance_panel(body)

        self._build_section_header(body, "界面设置", "调整显示与提示方式")
        self._build_ui_panel(body)

        body.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll)

        self._build_button_bar(root)

    # ── 标题 ──────────────────────────────────────────────────

    def _build_title(self, layout: QVBoxLayout) -> None:
        title = QLabel("设置")
        if self.styles:
            title.setStyleSheet(self.styles.page_title())
        else:
            title.setStyleSheet(
                "font-size: 15px; font-weight: 600; color: #E0E0E0;"
            )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setContentsMargins(0, 0, 0, 4)
        layout.addWidget(title)

    # ── 滚动区域 ──────────────────────────────────────────────

    def _build_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # 合并为一次 setStyleSheet 调用
        style = (
            "QScrollArea { border: none; background-color: transparent; } "
            "QWidget { background-color: transparent; }"
        )
        if self.styles:
            style += self.styles.scrollbar()
        scroll.setStyleSheet(style)

        return scroll

    # ── 分组标题 ──────────────────────────────────────────────

    def _build_section_header(
        self, layout: QVBoxLayout, title: str, desc: str
    ) -> None:
        header = QFrame()
        header.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 6, 0, 2)
        h.setSpacing(8)

        # 竖色条
        bar = QFrame()
        bar.setFixedSize(3, 28)
        accent = TOKENS.colors.accent if TOKENS else "#E84393"
        bar.setStyleSheet(
            f"background-color: {accent}; border: none; border-radius: 0px;"
        )
        h.addWidget(bar)

        # 文字列
        col = QWidget()
        col.setStyleSheet("background: transparent;")
        col_l = QVBoxLayout(col)
        col_l.setContentsMargins(0, 0, 0, 0)
        col_l.setSpacing(2)

        t = QLabel(title)
        if self.styles:
            t.setStyleSheet(self.styles.section_title())
        else:
            t.setStyleSheet(
                "font-weight: 700; font-size: 12px; color: #E0E0E0;"
            )
        col_l.addWidget(t)

        d = QLabel(desc)
        if self.styles:
            d.setStyleSheet(self.styles.section_desc())
        else:
            d.setStyleSheet("color: #888; font-size: 10px;")
        col_l.addWidget(d)

        h.addWidget(col)
        h.addStretch()
        layout.addWidget(header)

    # ── 辅助：面板内分隔线 ────────────────────────────────────

    @staticmethod
    def _make_separator() -> QFrame:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.04);")
        return sep

    # ================================================================
    # 筛选设置面板
    # ================================================================

    def _build_filter_panel(self, layout: QVBoxLayout) -> None:
        panel = QFrame()
        panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        if self.styles:
            panel.setStyleSheet(self.styles.panel())

        p = QVBoxLayout(panel)
        p.setSpacing(14)

        self._build_score_chips(p)
        self._build_custom_score(p)

        p.addWidget(self._make_separator())
        p.addSpacing(2)

        self._build_rating_chips(p)
        p.addWidget(self._make_separator())

        self._build_high_first_switch(p)

        layout.addWidget(panel)

    # ── 分数选择 ──────────────────────────────────────────────

    def _build_score_chips(self, layout: QVBoxLayout) -> None:
        label = QLabel("最低分数门槛")
        if self.styles:
            label.setStyleSheet(self.styles.param_title())
        layout.addWidget(label)

        self._controls.score_group = QButtonGroup(self)
        current = _safe_attr(self._orig_filter, "min_score", 0)

        rows = (SCORE_OPTIONS[:4], SCORE_OPTIONS[4:])

        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        wrapper_l = QVBoxLayout(wrapper)
        wrapper_l.setContentsMargins(0, 0, 0, 0)
        wrapper_l.setSpacing(4)

        for row in rows:
            rw = QWidget()
            rw.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(6)

            for score, text in row:
                btn = QPushButton(text)
                btn.setCheckable(True)
                btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                if self.styles:
                    btn.setStyleSheet(self.styles.score_chip())
                if score == current:
                    btn.setChecked(True)

                self._controls.score_group.addButton(btn, score)
                self._controls.score_buttons[score] = btn
                rl.addWidget(btn)

            rl.addStretch()
            wrapper_l.addWidget(rw)

        layout.addWidget(wrapper)

    # ── 自定义分数 ────────────────────────────────────────────

    def _build_custom_score(self, layout: QVBoxLayout) -> None:
        current = _safe_attr(self._orig_filter, "min_score", 0)
        preset_scores = [s for s, _ in SCORE_OPTIONS]
        is_custom = current not in preset_scores

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        cb = QCheckBox("自定义分数")
        cb.setChecked(is_custom)
        if self.styles:
            cb.setStyleSheet(self.styles.checkbox_with_check())
        self._controls.custom_score_cb = cb
        rl.addWidget(cb)

        entry = QLineEdit()
        entry.setFixedWidth(50)
        entry.setFixedHeight(24)
        entry.setPlaceholderText("0-100")
        entry.setEnabled(is_custom)
        entry.setValidator(QIntValidator(0, 100, self))
        if self.styles:
            entry.setStyleSheet(self.styles.line_edit())
        if is_custom:
            entry.setText(str(current))
        self._controls.custom_score_entry = entry
        rl.addWidget(entry)

        rl.addStretch()
        layout.addWidget(row)

        cb.stateChanged.connect(self._on_custom_score_toggle)

    # ── 评级过滤 ──────────────────────────────────────────────

    def _build_rating_chips(self, layout: QVBoxLayout) -> None:
        label = QLabel("内容评级")
        if self.styles:
            label.setStyleSheet(self.styles.param_title())
        layout.addWidget(label)

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        current_ratings = _safe_attr(
            self._orig_filter, "ratings", {"s", "q", "e"}
        )

        for key, text, bg_attr, txt_attr in RATING_CONFIGS:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(key in current_ratings)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            btn.setMinimumHeight(28)

            if self.styles and TOKENS:
                bg = getattr(TOKENS.colors, bg_attr, "#333")
                tc = getattr(TOKENS.colors, txt_attr, "#FFF")
                btn.setStyleSheet(self.styles.rating_chip(bg, tc))

            self._controls.rating_buttons[key] = btn
            rl.addWidget(btn)

        rl.addStretch()
        layout.addWidget(row)
        layout.addSpacing(4)

    # ── 高分优先 ──────────────────────────────────────────────

    def _build_high_first_switch(self, layout: QVBoxLayout) -> None:
        self._build_switch_row(
            layout,
            title="优先显示高分内容",
            hint="优先排列高分图片，不影响筛选范围",
            checked=_safe_attr(self._orig_filter, "high_score_first", True),
            key="high_first_switch",
        )

    # ================================================================
    # 性能设置面板
    # ================================================================

    def _build_performance_panel(self, layout: QVBoxLayout) -> None:
        panel = QFrame()
        if self.styles:
            panel.setStyleSheet(self.styles.panel())

        p = QVBoxLayout(panel)
        p.setSpacing(self.SLIDER_ITEM_SPACING)

        for i, spec in enumerate(PERF_SLIDERS):
            self._build_slider_item(p, spec)
            if i < len(PERF_SLIDERS) - 1:
                p.addWidget(self._make_separator())

        layout.addWidget(panel)

    def _build_slider_item(self, layout: QVBoxLayout, spec: SliderSpec) -> None:
        """构建滑块项。"""
        # 从 original_settings.performance 获取实际值
        perf_val_map = {
            "preload_slider": _safe_attr(
                self._orig_perf, "preload_count", spec.default
            ),
            "cache_slider": _safe_attr(
                self._orig_perf, "max_image_cache", spec.default
            ),
            "workers_slider": _safe_attr(
                self._orig_perf, "download_workers", spec.default
            ),
            "timeout_slider": _safe_attr(
                self._orig_perf, "load_timeout", spec.default
            ),
        }
        current = _clamp(
            perf_val_map.get(spec.key, spec.default), spec.min_val, spec.max_val
        )

        box = QWidget()
        box.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(3)

        # 行1：名称 + 值徽章
        hdr = QWidget()
        hdr.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        name = QLabel(spec.label)
        if self.styles:
            name.setStyleSheet(self.styles.param_title())
        hl.addWidget(name)
        hl.addStretch()

        val_label = QLabel(str(current))
        val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.styles:
            val_label.setStyleSheet(self.styles.value_badge())
        hl.addWidget(val_label)
        bl.addWidget(hdr)

        # 行2：min + slider + max
        sr = QWidget()
        sr.setStyleSheet("background: transparent;")
        sl = QHBoxLayout(sr)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)

        lo = QLabel(str(spec.min_val))
        lo.setFixedWidth(20)
        lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if TOKENS:
            lo.setStyleSheet(
                f"color: {TOKENS.colors.text_muted}; "
                f"font-size: {TOKENS.typography.size_xs}px;"
            )
        sl.addWidget(lo)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(spec.min_val, spec.max_val)
        slider.setValue(current)
        if self.styles:
            slider.setStyleSheet(self.styles.slider())
        sl.addWidget(slider, 1)

        hi = QLabel(str(spec.max_val))
        hi.setFixedWidth(20)
        hi.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if TOKENS:
            hi.setStyleSheet(
                f"color: {TOKENS.colors.text_muted}; "
                f"font-size: {TOKENS.typography.size_xs}px;"
            )
        sl.addWidget(hi)
        bl.addWidget(sr)

        slider.valueChanged.connect(lambda v, lb=val_label: lb.setText(str(v)))

        # 行3：提示
        h = QLabel(spec.hint)
        if self.styles:
            h.setStyleSheet(self.styles.hint_text())
        bl.addWidget(h)

        layout.addWidget(box)

        # 设置控件引用
        setattr(self._controls, spec.key, slider)

    # ================================================================
    # 界面设置面板
    # ================================================================

    def _build_ui_panel(self, layout: QVBoxLayout) -> None:
        panel = QFrame()
        if self.styles:
            panel.setStyleSheet(self.styles.panel())

        p = QVBoxLayout(panel)
        p.setSpacing(self.ITEM_SPACING)

        self._build_switch_row(
            p,
            title="显示已保存标记",
            hint="在已下载的图片上显示保存标识",
            checked=_safe_attr(self._orig_ui, "show_saved_badge", True),
            key="show_badge_switch",
        )
        p.addWidget(self._make_separator())
        self._build_highlight_section(p)

        layout.addWidget(panel)

    # ── Switch 行（通用） ─────────────────────────────────────

    def _build_switch_row(
        self,
        layout: QVBoxLayout,
        title: str,
        hint: str,
        checked: bool,
        key: str,
    ) -> None:
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        txt = QWidget()
        txt.setStyleSheet("background: transparent;")
        tl = QVBoxLayout(txt)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(1)

        t = QLabel(title)
        if self.styles:
            t.setStyleSheet(self.styles.param_title())
        tl.addWidget(t)

        h = QLabel(hint)
        if self.styles:
            h.setStyleSheet(self.styles.hint_text())
        tl.addWidget(h)

        rl.addWidget(txt)
        rl.addStretch()

        sw = SwitchWidget(checked=checked)
        setattr(self._controls, key, sw)
        rl.addWidget(sw)

        layout.addWidget(row)

    # ── 高分高亮（含子设置） ──────────────────────────────────

    def _build_highlight_section(self, layout: QVBoxLayout) -> None:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)

        # 主开关
        main_row = QWidget()
        main_row.setStyleSheet("background: transparent;")
        ml = QHBoxLayout(main_row)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)

        txt = QWidget()
        txt.setStyleSheet("background: transparent;")
        tl = QVBoxLayout(txt)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(1)

        t = QLabel("高分高亮")
        if self.styles:
            t.setStyleSheet(self.styles.param_title())
        tl.addWidget(t)

        h = QLabel("突出显示高评分内容")
        if self.styles:
            h.setStyleSheet(self.styles.hint_text())
        tl.addWidget(h)

        ml.addWidget(txt)
        ml.addStretch()

        sw = SwitchWidget(
            checked=_safe_attr(self._orig_ui, "show_score_highlight", True)
        )
        self._controls.show_highlight_switch = sw
        ml.addWidget(sw)
        cl.addWidget(main_row)

        # 子设置（阈值）
        sub = QWidget()
        sub.setStyleSheet("background: transparent;")
        sub_l = QHBoxLayout(sub)
        sub_l.setContentsMargins(20, 0, 0, 0)
        sub_l.setSpacing(4)

        enabled = sw.isChecked()

        lbl1 = QLabel("分数 ≥")
        if self.styles:
            lbl1.setStyleSheet(self.styles.sub_text())
        lbl1.setEnabled(enabled)
        sub_l.addWidget(lbl1)

        spinbox = QSpinBox()
        spinbox.setRange(1, 100)
        spinbox.setValue(
            _safe_attr(self._orig_ui, "high_score_threshold", 10)
        )
        spinbox.setFixedWidth(48)
        spinbox.setFixedHeight(22)
        spinbox.setEnabled(enabled)
        if self.styles:
            spinbox.setStyleSheet(self.styles.spinbox())
        self._controls.threshold_spinbox = spinbox
        sub_l.addWidget(spinbox)

        lbl2 = QLabel("时突出显示")
        if self.styles:
            lbl2.setStyleSheet(self.styles.sub_text())
        lbl2.setEnabled(enabled)
        sub_l.addWidget(lbl2)

        sub_l.addStretch()
        cl.addWidget(sub)

        # 联动
        sw.toggled.connect(spinbox.setEnabled)
        sw.toggled.connect(lbl1.setEnabled)
        sw.toggled.connect(lbl2.setEnabled)

        layout.addWidget(container)

    # ================================================================
    # 按钮栏
    # ================================================================

    def _build_button_bar(self, layout: QVBoxLayout) -> None:
        # 渐变分隔线
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:0, "
            "stop:0 transparent, "
            "stop:0.15 rgba(255, 255, 255, 0.08), "
            "stop:0.85 rgba(255, 255, 255, 0.08), "
            "stop:1 transparent);"
        )
        layout.addSpacing(8)
        layout.addWidget(sep)
        layout.addSpacing(10)

        bar = QFrame()
        bar.setStyleSheet("background: transparent;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)

        reset = QPushButton("恢复默认")
        reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self.styles:
            reset.setStyleSheet(self.styles.button("ghost"))
        reset.clicked.connect(self._reset_defaults)
        bl.addWidget(reset)

        bl.addStretch()

        cancel = QPushButton("取消")
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self.styles:
            cancel.setStyleSheet(self.styles.button("secondary"))
        cancel.clicked.connect(self.reject)
        bl.addWidget(cancel)

        save = QPushButton("保存并应用")
        save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self.styles:
            save.setStyleSheet(self.styles.button("primary"))
        save.clicked.connect(self._save)
        bl.addWidget(save)

        layout.addWidget(bar)

    # ================================================================
    # 信号处理
    # ================================================================

    def _on_custom_score_toggle(self, state: int) -> None:
        # 使用 bool(state) 替代不可靠的 enum 比较
        is_checked = bool(state)
        entry = self._controls.custom_score_entry
        group = self._controls.score_group

        if entry is not None:
            entry.setEnabled(is_checked)

        if is_checked:
            # 取消所有预设
            if group is not None:
                group.setExclusive(False)
                for btn in self._controls.score_buttons.values():
                    btn.setChecked(False)
                group.setExclusive(True)
            if entry is not None:
                entry.setFocus()
                entry.selectAll()
        else:
            # 回到默认「不限」
            btn_0 = self._controls.score_buttons.get(0)
            if btn_0 is not None:
                btn_0.setChecked(True)
            if entry is not None:
                entry.clear()

    def _on_rating_toggled(self, key: str, checked: bool) -> None:
        """防止取消最后一个评级。"""
        if checked:
            return

        buttons = self._controls.rating_buttons
        # 确保非空
        assert buttons, "rating_buttons 不应为空"

        others = any(b.isChecked() for k, b in buttons.items() if k != key)
        if not others:
            btn = buttons.get(key)
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)

    def _connect_preview_signals(self) -> None:
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._emit_preview)

        def schedule() -> None:
            if self._preview_timer is not None:
                self._preview_timer.start(self.PREVIEW_DEBOUNCE_MS)

        # 评级按钮
        for key, btn in self._controls.rating_buttons.items():
            btn.toggled.connect(schedule)
            btn.toggled.connect(
                lambda c, k=key: self._on_rating_toggled(k, c)
            )

        # 滑块
        for key in (
            "preload_slider",
            "cache_slider",
            "workers_slider",
            "timeout_slider",
        ):
            s = getattr(self._controls, key, None)
            if s is not None:
                s.valueChanged.connect(schedule)

        # Switch
        for key in (
            "high_first_switch",
            "show_badge_switch",
            "show_highlight_switch",
        ):
            sw = getattr(self._controls, key, None)
            if sw is not None:
                sw.toggled.connect(schedule)

        # 自定义分数
        if self._controls.custom_score_cb is not None:
            self._controls.custom_score_cb.stateChanged.connect(schedule)
        if self._controls.custom_score_entry is not None:
            self._controls.custom_score_entry.textChanged.connect(schedule)

        if self._controls.threshold_spinbox is not None:
            self._controls.threshold_spinbox.valueChanged.connect(schedule)

    def _emit_preview(self) -> None:
        try:
            self.current_settings = self._collect_settings()
            self.preview_requested.emit(self.current_settings)
        except Exception:
            logger.debug("预览设置收集失败", exc_info=True)

    # ================================================================
    # 设置收集
    # ================================================================

    def _collect_settings(self) -> Any:
        min_score = self._get_min_score()
        ratings = {
            k for k, b in self._controls.rating_buttons.items() if b.isChecked()
        }
        if not ratings:
            ratings = {"s", "q", "e"}

        hf = self._controls.high_first_switch
        try:
            fs = self._FilterSettings(
                min_score=min_score,
                ratings=ratings,
                high_score_first=hf.isChecked() if hf else True,
            )

            ps = self._PerformanceSettings(
                preload_count=self._slider_val("preload_slider", 15),
                max_image_cache=self._slider_val("cache_slider", 50),
                download_workers=self._slider_val("workers_slider", 3),
                load_timeout=self._slider_val("timeout_slider", 15),
            )

            badge_sw = self._controls.show_badge_switch
            hl_sw = self._controls.show_highlight_switch
            th_sp = self._controls.threshold_spinbox

            us = self._UISettings(
                show_saved_badge=badge_sw.isChecked() if badge_sw else True,
                show_score_highlight=hl_sw.isChecked() if hl_sw else True,
                high_score_threshold=th_sp.value() if th_sp else 10,
            )

            return self._UserSettings(filter=fs, performance=ps, ui=us)
        except Exception:
            logger.error("构建设置对象失败", exc_info=True)
            return self.original_settings

    def _get_min_score(self) -> int:
        cb = self._controls.custom_score_cb
        if cb is not None and cb.isChecked():
            entry = self._controls.custom_score_entry
            if entry is not None:
                text = entry.text().strip()
                if text:
                    try:
                        return _clamp(int(text), 0, 100)
                    except (ValueError, TypeError):
                        pass
            return 0

        group = self._controls.score_group
        if group is not None:
            cid = group.checkedId()
            if cid != -1:
                return cid

        return 0

    def _slider_val(self, key: str, default: int) -> int:
        s = getattr(self._controls, key, None)
        if s is not None and hasattr(s, "value"):
            return s.value()
        return default

    # ================================================================
    # 重置默认
    # ================================================================

    def _reset_defaults(self) -> None:
        try:
            d = self._UserSettings()
        except Exception:
            logger.error("创建默认设置失败", exc_info=True)
            return

        # 分数
        btns = self._controls.score_buttons
        ds = _safe_attr(self._orig_filter, "min_score", 0)
        if ds in btns:
            btns[ds].setChecked(True)

        if self._controls.custom_score_cb is not None:
            self._controls.custom_score_cb.setChecked(False)
        if self._controls.custom_score_entry is not None:
            self._controls.custom_score_entry.setEnabled(False)
            self._controls.custom_score_entry.clear()

        # 评级
        dr = _safe_attr(self._orig_filter, "ratings", {"s", "q", "e"})
        for k, btn in self._controls.rating_buttons.items():
            btn.setChecked(k in dr)

        # 滑块
        dp = _safe_attr(d, "performance")
        for key, attr, fallback in (
            ("preload_slider", "preload_count", 15),
            ("cache_slider", "max_image_cache", 50),
            ("workers_slider", "download_workers", 3),
            ("timeout_slider", "load_timeout", 15),
        ):
            s = getattr(self._controls, key, None)
            if s is not None:
                s.setValue(_safe_attr(dp, attr, fallback))

        # Switch
        df = _safe_attr(d, "filter")
        du = _safe_attr(d, "ui")
        for key, obj, attr, fallback in (
            ("high_first_switch", df, "high_score_first", True),
            ("show_badge_switch", du, "show_saved_badge", True),
            ("show_highlight_switch", du, "show_score_highlight", True),
        ):
            sw = getattr(self._controls, key, None)
            if sw is not None:
                sw.setChecked(_safe_attr(obj, attr, fallback))

        # 阈值
        sp = self._controls.threshold_spinbox
        if sp is not None:
            sp.setValue(_safe_attr(du, "high_score_threshold", 10))
            hl = self._controls.show_highlight_switch
            if hl is not None:
                sp.setEnabled(hl.isChecked())

        logger.debug("设置已重置为默认值")

    # ================================================================
    # 保存 / 取消
    # ================================================================

    def reject(self) -> None:
        self._cleanup()
        try:
            self.preview_requested.emit(self.original_settings)
        except RuntimeError:
            logger.debug("reject 时预览信号发送失败", exc_info=True)
        super().reject()

    def _save(self) -> None:
        final = self._collect_settings()
        self.settings_saved.emit(final)
        logger.info("设置已保存")
        self._cleanup()
        self.accept()

    def get_settings(self) -> Any:
        return self.current_settings