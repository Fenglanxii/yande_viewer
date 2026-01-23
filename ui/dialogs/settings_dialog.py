"""设置对话框模块。

本模块提供用户设置界面的完整实现，包括筛选、性能和界面设置。
支持实时预览功能，用户修改设置时可立即看到效果。

Example:
    基本使用示例::

        dialog = SettingsDialog(parent, current_settings)
        dialog.preview_requested.connect(preview_handler)
        dialog.settings_saved.connect(save_handler)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_settings = dialog.get_settings()

Note:
    本模块依赖 PyQt6 和 config.design_tokens 模块。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QRadioButton,
    QCheckBox,
    QLineEdit,
    QSlider,
    QButtonGroup,
    QScrollArea,
    QWidget,
    QSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor

if TYPE_CHECKING:
    from config.user_settings import UserSettings

logger = logging.getLogger("YandeViewer.UI.SettingsDialog")


# ============================================================================
# 设计令牌导入
# ============================================================================

def _get_tokens() -> Optional[Any]:
    """安全获取设计令牌。

    Returns:
        设计令牌对象，如果导入失败则返回 None。
    """
    try:
        from config.design_tokens import TOKENS
        return TOKENS
    except ImportError:
        logger.warning("设计令牌模块不可用，使用默认样式")
        return None


def _get_settings_classes() -> Tuple[Optional[type], ...]:
    """安全获取设置类。

    Returns:
        包含 (UserSettings, FilterSettings, PerformanceSettings, UISettings) 的元组，
        导入失败的类将为 None。
    """
    try:
        from config.user_settings import (
            UserSettings,
            FilterSettings,
            PerformanceSettings,
            UISettings,
        )
        return UserSettings, FilterSettings, PerformanceSettings, UISettings
    except ImportError:
        logger.error("无法导入用户设置类")
        return None, None, None, None


TOKENS = _get_tokens()
UserSettings, FilterSettings, PerformanceSettings, UISettings = _get_settings_classes()


# ============================================================================
# 常量定义
# ============================================================================

SCORE_OPTIONS: List[Tuple[int, str]] = [
    (0, "不限"),
    (5, "≥5"),
    (10, "≥10"),
    (15, "≥15"),
    (20, "≥20"),
    (30, "≥30"),
    (50, "≥50"),
]
"""预设分数选项列表，每项包含 (分数值, 显示标签)。"""

RATING_CONFIGS: List[Tuple[str, str, str, str]] = [
    ("s", "Safe", "rating_safe_bg", "rating_safe_text"),
    ("q", "Questionable", "rating_questionable_bg", "rating_questionable_text"),
    ("e", "Explicit", "rating_explicit_bg", "rating_explicit_text"),
]
"""评级配置列表，每项包含 (键名, 标签, 背景色属性, 文字色属性)。"""


# ============================================================================
# 样式工厂
# ============================================================================

@dataclass
class DialogStyleFactory:
    """对话框样式工厂。

    集中管理所有样式生成，便于维护和主题切换。

    Attributes:
        colors: 颜色配置对象。
        typography: 排版配置对象。
        layout: 布局配置对象。
    """

    colors: Any
    typography: Any
    layout: Any

    def label(self) -> str:
        """生成标签样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            color: {self.colors.text_primary};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_sm}px;
        """

    def section_title(self) -> str:
        """生成分组标题样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            color: {self.colors.accent};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_md}px;
            font-weight: bold;
        """

    def panel(self) -> str:
        """生成面板样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            QFrame {{
                background-color: {self.colors.bg_surface};
                border-radius: {self.layout.radius_md}px;
                padding: 15px;
            }}
        """

    def checkbox(self) -> str:
        """生成复选框样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            QCheckBox {{
                color: {self.colors.text_primary};
                font-size: {self.typography.size_sm}px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {self.colors.border_default};
                border-radius: 3px;
                background-color: {self.colors.bg_base};
            }}
            QCheckBox::indicator:checked {{
                background-color: {self.colors.accent};
                border-color: {self.colors.accent};
            }}
        """

    def radio_button(self) -> str:
        """生成单选按钮样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            QRadioButton {{
                color: {self.colors.text_primary};
                font-size: {self.typography.size_xs}px;
            }}
            QRadioButton::indicator {{
                width: 12px;
                height: 12px;
                border: 1px solid {self.colors.border_default};
                border-radius: 6px;
                background-color: {self.colors.bg_base};
            }}
            QRadioButton::indicator:checked {{
                background-color: {self.colors.accent};
                border-color: {self.colors.accent};
            }}
        """

    def button(self, variant: str = "default") -> str:
        """生成按钮样式。

        Args:
            variant: 按钮变体类型，支持 "primary"、"default"、"danger"。

        Returns:
            CSS 样式字符串。
        """
        variants = {
            "primary": (self.colors.accent, self.colors.accent_hover),
            "default": (self.colors.bg_surface, self.colors.bg_hover),
            "danger": (self.colors.error, "#D32F2F"),
        }
        bg, hover = variants.get(variant, variants["default"])

        return f"""
            QPushButton {{
                background-color: {bg};
                color: {self.colors.text_primary};
                border: none;
                border-radius: {self.layout.radius_md}px;
                padding: 8px 16px;
                font-weight: 500;
                min-height: {self.layout.button_height_sm}px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:disabled {{
                background-color: #555555;
                color: #888888;
            }}
        """

    def slider(self) -> str:
        """生成滑动条样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            QSlider::groove:horizontal {{
                background: {self.colors.slider_track};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {self.colors.accent};
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {self.colors.accent_hover};
            }}
            QSlider::sub-page:horizontal {{
                background: {self.colors.slider_track_active};
                border-radius: 3px;
            }}
        """

    def line_edit(self) -> str:
        """生成输入框样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            QLineEdit {{
                background-color: #333333;
                color: {self.colors.text_primary};
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: {self.typography.size_sm}px;
            }}
            QLineEdit:focus {{
                background-color: #3D3D3D;
            }}
            QLineEdit:disabled {{
                background-color: #252525;
                color: {self.colors.text_secondary};
            }}
        """

    def rating_chip(self, bg_color: str, text_color: str) -> str:
        """生成评级切换按钮样式。

        Args:
            bg_color: 选中时的背景颜色。
            text_color: 选中时的文字颜色。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {self.colors.text_secondary};
                border: 1px solid {self.colors.border_default};
                border-radius: 12px;
                padding: 4px 12px;
                font-size: {self.typography.size_sm}px;
            }}
            QPushButton:checked {{
                background-color: {bg_color};
                color: {text_color};
                border-color: {text_color};
            }}
            QPushButton:hover {{
                border-color: {text_color};
            }}
        """

    def scrollbar(self) -> str:
        """生成滚动条样式。

        Returns:
            CSS 样式字符串。
        """
        return """
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 4px 2px;
            }
            QScrollBar::handle:vertical {
                background: #555555;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #777777;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """

    def spinbox(self) -> str:
        """生成数字调节框样式。

        Returns:
            CSS 样式字符串。
        """
        return f"""
            QSpinBox {{
                background-color: #333333;
                color: {self.colors.text_primary};
                border: none;
                border-radius: 4px;
                padding: 2px 6px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 16px;
                background-color: {self.colors.bg_surface};
                border-radius: 2px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background-color: {self.colors.bg_hover};
            }}
        """


# ============================================================================
# 设置对话框
# ============================================================================

class SettingsDialog(QDialog):
    """设置对话框。

    提供完整的用户设置界面，支持实时预览功能。

    Attributes:
        original_settings: 打开对话框时的原始设置（用于取消时恢复）。
        current_settings: 当前编辑中的设置。

    Signals:
        preview_requested: 请求预览设置变更时发射，携带 UserSettings 对象。
        settings_saved: 设置保存成功时发射，携带 UserSettings 对象。

    Example:
        创建并使用设置对话框::

            dialog = SettingsDialog(parent, current_settings)
            dialog.preview_requested.connect(on_preview)
            dialog.settings_saved.connect(on_save)
            dialog.exec()
    """

    # 信号定义
    preview_requested = pyqtSignal(object)
    settings_saved = pyqtSignal(object)

    # 对话框尺寸常量
    DIALOG_WIDTH: int = 500
    DIALOG_HEIGHT: int = 600

    # 预览防抖延迟（毫秒）
    PREVIEW_DEBOUNCE_MS: int = 200

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        settings: Optional[Any] = None,
    ) -> None:
        """初始化设置对话框。

        Args:
            parent: 父窗口，可选。
            settings: UserSettings 实例，如果为 None 则使用默认设置。

        Raises:
            RuntimeError: 当 UserSettings 类不可用且未提供 settings 参数时。
        """
        super().__init__(parent)

        # 设置验证和初始化
        if settings is None:
            if UserSettings is not None:
                settings = UserSettings()
            else:
                logger.error("UserSettings 类不可用，无法创建对话框")
                self.reject()
                return

        self.original_settings = settings
        self.current_settings = (
            settings.copy() if hasattr(settings, "copy") else settings
        )

        # 初始化样式工厂
        self.styles: Optional[DialogStyleFactory] = None
        if TOKENS is not None:
            self.styles = DialogStyleFactory(
                TOKENS.colors,
                TOKENS.typography,
                TOKENS.layout,
            )
        else:
            logger.warning("TOKENS 不可用，将使用备用样式")

        # 控件引用字典
        self._controls: Dict[str, Any] = {}
        self._preview_timer: Optional[QTimer] = None

        # 窗口基本设置
        self.setWindowTitle("⚙️ 设置")
        self.setFixedSize(self.DIALOG_WIDTH, self.DIALOG_HEIGHT)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        if TOKENS is not None:
            self.setStyleSheet(f"background-color: {TOKENS.colors.bg_base};")

        # 构建 UI
        self._setup_ui()
        self._connect_preview_signals()

        # 居中显示
        self._center_on_parent()

        logger.debug("SettingsDialog 初始化完成")

    def _center_on_parent(self) -> None:
        """将对话框居中显示在父窗口上。"""
        parent = self.parent()
        if parent is not None:
            geo = parent.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

    def _setup_ui(self) -> None:
        """构建用户界面。"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 12)

        # 标题
        self._create_title(main_layout)

        # 滚动区域
        scroll = self._create_scroll_area()
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(16)
        container_layout.setContentsMargins(0, 0, 8, 0)

        # 筛选设置区域
        self._create_section_title(container_layout, "🎯 筛选设置")
        self._create_filter_panel(container_layout)

        # 性能设置区域
        self._create_section_title(container_layout, "⚡ 性能设置")
        self._create_performance_panel(container_layout)

        # 界面设置区域
        self._create_section_title(container_layout, "🎨 界面设置")
        self._create_ui_panel(container_layout)

        container_layout.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # 按钮栏
        self._create_button_bar(main_layout)

    def _create_title(self, layout: QVBoxLayout) -> None:
        """创建对话框标题。

        Args:
            layout: 父布局。
        """
        title = QLabel("⚙️ 设置")

        if TOKENS is not None:
            title.setStyleSheet(f"""
                QLabel {{
                    color: {TOKENS.colors.text_primary};
                    font-family: {TOKENS.typography.font_icon};
                    font-size: {TOKENS.typography.size_lg}px;
                    font-weight: bold;
                }}
            """)
        else:
            title.setStyleSheet("font-size: 15px; font-weight: bold;")

        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

    def _create_scroll_area(self) -> QScrollArea:
        """创建滚动区域。

        Returns:
            配置好的 QScrollArea 实例。
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        style = "QScrollArea { border: none; background-color: transparent; }"
        if self.styles is not None:
            style += self.styles.scrollbar()

        scroll.setStyleSheet(style)
        return scroll

    def _create_section_title(self, layout: QVBoxLayout, title: str) -> None:
        """创建分组标题。

        Args:
            layout: 父布局。
            title: 标题文本。
        """
        label = QLabel(title)

        if self.styles is not None:
            label.setStyleSheet(self.styles.section_title())
        else:
            label.setStyleSheet("font-weight: bold;")

        layout.addWidget(label)

    def _create_filter_panel(self, layout: QVBoxLayout) -> None:
        """创建筛选设置面板。

        Args:
            layout: 父布局。
        """
        panel = QFrame()
        if self.styles is not None:
            panel.setStyleSheet(self.styles.panel())

        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(10)

        # 分数选项
        self._create_score_section(panel_layout)

        # 自定义分数
        self._create_custom_score_section(panel_layout)

        # 评级过滤
        self._create_rating_section(panel_layout)

        # 高分优先
        self._create_high_first_option(panel_layout)

        layout.addWidget(panel)

    def _create_score_section(self, layout: QVBoxLayout) -> None:
        """创建分数选择区域。

        Args:
            layout: 父布局。
        """
        score_label = QLabel("最低分数:")
        if self.styles is not None:
            score_label.setStyleSheet(self.styles.label())
        layout.addWidget(score_label)

        # 分数按钮组
        score_frame = QFrame()
        score_frame.setStyleSheet("background-color: transparent;")
        score_layout = QHBoxLayout(score_frame)
        score_layout.setContentsMargins(0, 0, 0, 0)
        score_layout.setSpacing(10)

        self._controls["score_group"] = QButtonGroup(self)
        self._controls["score_buttons"] = {}

        current_score = getattr(self.original_settings.filter, "min_score", 0)

        for score, label in SCORE_OPTIONS:
            rb = QRadioButton(label)
            if self.styles is not None:
                rb.setStyleSheet(self.styles.radio_button())
            rb.setMinimumWidth(45)

            if score == current_score:
                rb.setChecked(True)

            self._controls["score_group"].addButton(rb, score)
            self._controls["score_buttons"][score] = rb
            score_layout.addWidget(rb)

        score_layout.addStretch()
        layout.addWidget(score_frame)

    def _create_custom_score_section(self, layout: QVBoxLayout) -> None:
        """创建自定义分数区域。

        Args:
            layout: 父布局。
        """
        frame = QFrame()
        frame.setStyleSheet("background-color: transparent;")
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(8)

        current_score = getattr(self.original_settings.filter, "min_score", 0)
        is_custom = current_score not in [s for s, _ in SCORE_OPTIONS]

        # 复选框
        cb = QCheckBox("自定义:")
        cb.setChecked(is_custom)
        if self.styles is not None:
            cb.setStyleSheet(self.styles.checkbox())
        self._controls["custom_score_cb"] = cb
        frame_layout.addWidget(cb)

        # 输入框
        entry = QLineEdit()
        entry.setFixedWidth(60)
        entry.setFixedHeight(28)
        entry.setPlaceholderText("0-100")
        entry.setEnabled(is_custom)

        if self.styles is not None:
            entry.setStyleSheet(self.styles.line_edit())

        if is_custom:
            entry.setText(str(current_score))

        self._controls["custom_score_entry"] = entry
        frame_layout.addWidget(entry)
        frame_layout.addStretch()

        layout.addWidget(frame)

        # 连接信号
        cb.stateChanged.connect(self._on_custom_score_toggle)

    def _create_rating_section(self, layout: QVBoxLayout) -> None:
        """创建评级过滤区域。

        Args:
            layout: 父布局。
        """
        label = QLabel("评级过滤:")
        if self.styles is not None:
            label.setStyleSheet(self.styles.label())
        layout.addWidget(label)

        frame = QFrame()
        frame.setStyleSheet("background-color: transparent;")
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(10)

        self._controls["rating_buttons"] = {}
        current_ratings = getattr(
            self.original_settings.filter, "ratings", {"s", "q", "e"}
        )

        for key, label_text, bg_attr, text_attr in RATING_CONFIGS:
            btn = QPushButton(label_text)
            btn.setCheckable(True)
            btn.setChecked(key in current_ratings)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setFixedHeight(28)

            if self.styles is not None and TOKENS is not None:
                bg_color = getattr(TOKENS.colors, bg_attr, "#333333")
                text_color = getattr(TOKENS.colors, text_attr, "#FFFFFF")
                btn.setStyleSheet(self.styles.rating_chip(bg_color, text_color))

            self._controls["rating_buttons"][key] = btn
            frame_layout.addWidget(btn)

        frame_layout.addStretch()
        layout.addWidget(frame)

    def _create_high_first_option(self, layout: QVBoxLayout) -> None:
        """创建高分优先选项。

        Args:
            layout: 父布局。
        """
        cb = QCheckBox("高分优先显示 (分数≥10的内容优先)")
        cb.setChecked(
            getattr(self.original_settings.filter, "high_score_first", True)
        )

        if self.styles is not None:
            cb.setStyleSheet(self.styles.checkbox())

        self._controls["high_first_cb"] = cb
        layout.addWidget(cb)

    def _create_performance_panel(self, layout: QVBoxLayout) -> None:
        """创建性能设置面板。

        Args:
            layout: 父布局。
        """
        panel = QFrame()
        if self.styles is not None:
            panel.setStyleSheet(self.styles.panel())

        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(12)

        perf = self.original_settings.performance

        # 预加载数量
        row, slider = self._create_slider_row(
            "预加载数量:",
            5,
            30,
            getattr(perf, "preload_count", 15),
        )
        self._controls["preload_slider"] = slider
        panel_layout.addWidget(row)

        # 图片缓存
        row, slider = self._create_slider_row(
            "图片缓存:",
            20,
            100,
            getattr(perf, "max_image_cache", 50),
        )
        self._controls["cache_slider"] = slider
        panel_layout.addWidget(row)

        # 下载线程
        row, slider = self._create_slider_row(
            "下载线程:",
            1,
            5,
            getattr(perf, "download_workers", 3),
        )
        self._controls["workers_slider"] = slider
        panel_layout.addWidget(row)

        # 加载超时
        row, slider = self._create_slider_row(
            "加载超时(秒):",
            5,
            30,
            getattr(perf, "load_timeout", 15),
        )
        self._controls["timeout_slider"] = slider
        panel_layout.addWidget(row)

        layout.addWidget(panel)

    def _create_slider_row(
        self,
        label_text: str,
        min_val: int,
        max_val: int,
        current: int,
    ) -> Tuple[QFrame, QSlider]:
        """创建滑动条行组件。

        Args:
            label_text: 标签文本。
            min_val: 最小值。
            max_val: 最大值。
            current: 当前值。

        Returns:
            包含 (行容器, 滑动条控件) 的元组。
        """
        # 确保当前值在有效范围内
        current = max(min_val, min(max_val, current))

        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        # 标签
        label = QLabel(label_text)
        label.setFixedWidth(100)
        if self.styles is not None:
            label.setStyleSheet(self.styles.label())
        row_layout.addWidget(label)

        # 最小值标签
        min_label = QLabel(str(min_val))
        min_label.setFixedWidth(20)
        min_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        if TOKENS is not None:
            min_label.setStyleSheet(
                f"color: {TOKENS.colors.text_secondary}; font-size: 11px;"
            )
        row_layout.addWidget(min_label)

        # 滑动条
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(current)
        if self.styles is not None:
            slider.setStyleSheet(self.styles.slider())
        row_layout.addWidget(slider, 1)

        # 最大值标签
        max_label = QLabel(str(max_val))
        max_label.setFixedWidth(20)
        if TOKENS is not None:
            max_label.setStyleSheet(
                f"color: {TOKENS.colors.text_secondary}; font-size: 11px;"
            )
        row_layout.addWidget(max_label)

        # 当前值显示
        value_label = QLabel(str(current))
        value_label.setFixedWidth(45)
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if TOKENS is not None:
            value_label.setStyleSheet(f"""
                color: {TOKENS.colors.value_display};
                font-weight: bold;
                background-color: {TOKENS.colors.bg_surface};
                border-radius: 4px;
                padding: 2px 4px;
            """)

        # 值变化时更新显示
        slider.valueChanged.connect(lambda v: value_label.setText(str(v)))
        row_layout.addWidget(value_label)

        return row, slider

    def _create_ui_panel(self, layout: QVBoxLayout) -> None:
        """创建界面设置面板。

        Args:
            layout: 父布局。
        """
        panel = QFrame()
        if self.styles is not None:
            panel.setStyleSheet(self.styles.panel())

        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(10)

        ui = self.original_settings.ui

        # 显示已保存标记
        cb = QCheckBox("显示已保存标记")
        cb.setChecked(getattr(ui, "show_saved_badge", True))
        if self.styles is not None:
            cb.setStyleSheet(self.styles.checkbox())
        self._controls["show_badge_cb"] = cb
        panel_layout.addWidget(cb)

        # 高分高亮
        self._create_highlight_section(panel_layout, ui)

        layout.addWidget(panel)

    def _create_highlight_section(self, layout: QVBoxLayout, ui: Any) -> None:
        """创建高分高亮设置区域。

        Args:
            layout: 父布局。
            ui: UI 设置对象。
        """
        frame = QFrame()
        frame.setStyleSheet("background-color: transparent;")
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(8)

        # 复选框
        cb = QCheckBox("高分高亮显示")
        cb.setChecked(getattr(ui, "show_score_highlight", True))
        if self.styles is not None:
            cb.setStyleSheet(self.styles.checkbox())
        self._controls["show_highlight_cb"] = cb
        frame_layout.addWidget(cb)

        # 阈值标签
        label1 = QLabel("(阈值:")
        if TOKENS is not None:
            label1.setStyleSheet(
                f"color: {TOKENS.colors.text_secondary}; font-size: 12px;"
            )
        frame_layout.addWidget(label1)

        # 阈值输入
        spinbox = QSpinBox()
        spinbox.setRange(1, 100)
        spinbox.setValue(getattr(ui, "high_score_threshold", 10))
        spinbox.setFixedWidth(55)
        spinbox.setEnabled(cb.isChecked())

        if self.styles is not None:
            spinbox.setStyleSheet(self.styles.spinbox())

        self._controls["threshold_spinbox"] = spinbox
        frame_layout.addWidget(spinbox)

        label2 = QLabel(")")
        if TOKENS is not None:
            label2.setStyleSheet(
                f"color: {TOKENS.colors.text_secondary}; font-size: 12px;"
            )
        frame_layout.addWidget(label2)

        frame_layout.addStretch()
        layout.addWidget(frame)

        # 联动：复选框状态改变时更新 spinbox 的启用状态
        cb.stateChanged.connect(
            lambda s: spinbox.setEnabled(s == Qt.CheckState.Checked.value)
        )

    def _create_button_bar(self, layout: QVBoxLayout) -> None:
        """创建底部按钮栏。

        Args:
            layout: 父布局。
        """
        frame = QFrame()
        frame.setStyleSheet("background-color: transparent;")
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(0, 15, 0, 10)

        # 恢复默认按钮
        reset_btn = QPushButton("恢复默认")
        reset_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self.styles is not None:
            reset_btn.setStyleSheet(self.styles.button("default"))
        reset_btn.clicked.connect(self._reset_defaults)
        frame_layout.addWidget(reset_btn)

        frame_layout.addStretch()

        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self.styles is not None:
            cancel_btn.setStyleSheet(self.styles.button("default"))
        cancel_btn.clicked.connect(self.reject)
        frame_layout.addWidget(cancel_btn)

        frame_layout.addSpacing(8)

        # 保存按钮
        save_btn = QPushButton("保存并应用")
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self.styles is not None:
            save_btn.setStyleSheet(self.styles.button("primary"))
        save_btn.clicked.connect(self._save)
        frame_layout.addWidget(save_btn)

        layout.addWidget(frame)

    def _on_custom_score_toggle(self, state: int) -> None:
        """处理自定义分数切换事件。

        Args:
            state: 复选框状态值。
        """
        is_checked = state == Qt.CheckState.Checked.value
        entry = self._controls.get("custom_score_entry")

        if entry is not None:
            entry.setEnabled(is_checked)

            if is_checked:
                entry.setFocus()
                entry.selectAll()

                # 取消预设按钮选中
                group = self._controls.get("score_group")
                if group is not None:
                    group.setExclusive(False)
                    for btn in self._controls.get("score_buttons", {}).values():
                        btn.setChecked(False)
                    group.setExclusive(True)
            else:
                entry.clear()

    def _connect_preview_signals(self) -> None:
        """连接所有预览相关的信号。"""
        # 创建防抖定时器
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._emit_preview)

        def schedule_preview() -> None:
            """调度预览更新。"""
            if self._preview_timer is not None:
                self._preview_timer.start(self.PREVIEW_DEBOUNCE_MS)

        # 连接评级按钮信号
        for btn in self._controls.get("rating_buttons", {}).values():
            btn.toggled.connect(schedule_preview)

        # 连接滑块信号
        slider_keys = [
            "preload_slider",
            "cache_slider",
            "workers_slider",
            "timeout_slider",
        ]
        for key in slider_keys:
            slider = self._controls.get(key)
            if slider is not None:
                slider.valueChanged.connect(schedule_preview)

        # 连接复选框信号
        checkbox_keys = ["high_first_cb", "show_badge_cb", "show_highlight_cb"]
        for key in checkbox_keys:
            cb = self._controls.get(key)
            if cb is not None:
                cb.stateChanged.connect(schedule_preview)

        # 连接输入框信号
        entry = self._controls.get("custom_score_entry")
        if entry is not None:
            entry.textChanged.connect(schedule_preview)

        spinbox = self._controls.get("threshold_spinbox")
        if spinbox is not None:
            spinbox.valueChanged.connect(schedule_preview)

    def _emit_preview(self) -> None:
        """发射预览信号。"""
        self.current_settings = self._collect_settings()
        self.preview_requested.emit(self.current_settings)

    def _collect_settings(self) -> Any:
        """收集当前所有设置值。

        Returns:
            包含所有设置的 UserSettings 对象。
        """
        if any(cls is None for cls in [FilterSettings, PerformanceSettings, UISettings]):
            logger.warning("设置类不完整，返回原始设置")
            return self.original_settings

        # 获取分数设置
        min_score = self._get_min_score()

        # 获取评级设置
        ratings = {
            k
            for k, btn in self._controls.get("rating_buttons", {}).items()
            if btn.isChecked()
        }
        if not ratings:
            ratings = {"s", "q", "e"}  # 默认全选

        # 构建筛选设置
        high_first_cb = self._controls.get("high_first_cb")
        filter_settings = FilterSettings(
            min_score=min_score,
            ratings=ratings,
            high_score_first=(
                high_first_cb.isChecked() if high_first_cb else True
            ),
        )

        # 构建性能设置
        perf_settings = PerformanceSettings(
            preload_count=self._get_slider_value("preload_slider", 15),
            max_image_cache=self._get_slider_value("cache_slider", 50),
            download_workers=self._get_slider_value("workers_slider", 3),
            load_timeout=self._get_slider_value("timeout_slider", 15),
        )

        # 构建界面设置
        show_badge_cb = self._controls.get("show_badge_cb")
        show_highlight_cb = self._controls.get("show_highlight_cb")
        threshold_spinbox = self._controls.get("threshold_spinbox")

        ui_settings = UISettings(
            show_saved_badge=(
                show_badge_cb.isChecked() if show_badge_cb else True
            ),
            show_score_highlight=(
                show_highlight_cb.isChecked() if show_highlight_cb else True
            ),
            high_score_threshold=(
                threshold_spinbox.value() if threshold_spinbox else 10
            ),
        )

        return UserSettings(
            filter=filter_settings,
            performance=perf_settings,
            ui=ui_settings,
        )

    def _get_min_score(self) -> int:
        """获取当前最低分数设置。

        Returns:
            最低分数值。
        """
        custom_cb = self._controls.get("custom_score_cb")
        if custom_cb is not None and custom_cb.isChecked():
            try:
                entry = self._controls.get("custom_score_entry")
                if entry is not None:
                    text = entry.text().strip()
                    if text:
                        value = int(text)
                        return max(0, min(100, value))
            except ValueError:
                logger.debug("无效的自定义分数输入")
            return 0

        group = self._controls.get("score_group")
        if group is not None:
            checked_id = group.checkedId()
            if checked_id != -1:
                return checked_id

        return 0

    def _get_slider_value(self, key: str, default: int) -> int:
        """安全获取滑块值。

        Args:
            key: 控件键名。
            default: 默认值。

        Returns:
            滑块当前值或默认值。
        """
        slider = self._controls.get(key)
        if slider is not None and hasattr(slider, "value"):
            return slider.value()
        return default

    def _reset_defaults(self) -> None:
        """恢复所有设置为默认值。"""
        if UserSettings is None:
            logger.warning("UserSettings 类不可用，无法重置")
            return

        defaults = UserSettings()

        # 重置分数选择
        score_buttons = self._controls.get("score_buttons", {})
        default_score = defaults.filter.min_score
        if default_score in score_buttons:
            score_buttons[default_score].setChecked(True)

        custom_cb = self._controls.get("custom_score_cb")
        if custom_cb is not None:
            custom_cb.setChecked(False)

        entry = self._controls.get("custom_score_entry")
        if entry is not None:
            entry.setEnabled(False)
            entry.clear()

        # 重置评级选择
        for k, btn in self._controls.get("rating_buttons", {}).items():
            btn.setChecked(k in defaults.filter.ratings)

        # 重置其他控件
        control_defaults = [
            ("high_first_cb", defaults.filter.high_score_first),
            ("preload_slider", defaults.performance.preload_count),
            ("cache_slider", defaults.performance.max_image_cache),
            ("workers_slider", defaults.performance.download_workers),
            ("timeout_slider", defaults.performance.load_timeout),
            ("show_badge_cb", defaults.ui.show_saved_badge),
            ("show_highlight_cb", defaults.ui.show_score_highlight),
            ("threshold_spinbox", defaults.ui.high_score_threshold),
        ]

        for key, value in control_defaults:
            control = self._controls.get(key)
            if control is None:
                continue

            if isinstance(control, QCheckBox):
                control.setChecked(value)
            elif isinstance(control, (QSlider, QSpinBox)):
                control.setValue(value)

        # 更新阈值 spinbox 的启用状态
        spinbox = self._controls.get("threshold_spinbox")
        highlight_cb = self._controls.get("show_highlight_cb")
        if spinbox is not None and highlight_cb is not None:
            spinbox.setEnabled(highlight_cb.isChecked())

        logger.debug("设置已重置为默认值")

    def reject(self) -> None:
        """取消对话框并恢复原始设置。"""
        self.preview_requested.emit(self.original_settings)
        super().reject()

    def _save(self) -> None:
        """保存当前设置。"""
        final_settings = self._collect_settings()
        self.settings_saved.emit(final_settings)
        logger.info("设置已保存")
        self.accept()

    def get_settings(self) -> Any:
        """获取当前设置。

        Returns:
            当前的 UserSettings 实例。
        """
        return self.current_settings