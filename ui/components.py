# -*- coding: utf-8 -*-
"""UI 组件库 - 现代化设计系统 (PyQt6)。

本模块提供统一风格的 UI 组件集合，包括按钮、标签、控制器等。
所有组件遵循设计令牌系统，确保视觉一致性。

组件分类:
    - 工厂类: UIFactory（快速创建预配置组件）
    - 按钮类: IconButton, ActionButton, NavButton, FavoriteButton
    - 控制器: SegmentedControl, ScoreSelector
    - 显示类: TagCloud, PillTag, StatBadge, MetadataBar
    - 覆盖层: Toast, ShortcutOverlay

设计原则:
    - 统一的暗色主题
    - 基于 8px 栅格的间距系统
    - 响应式交互反馈
    - 无障碍友好

Example:
    使用工厂类快速创建按钮::

        btn = UIFactory.create_icon_button(
            parent=self,
            icon="⚙",
            command=self.open_settings,
            tooltip="打开设置"
        )

Author: YandeViewer Team
License: MIT
"""

from __future__ import annotations

__all__ = [
    # 工厂类
    "UIFactory",
    # 枚举
    "ButtonStyle",
    "TagType",
    # 按钮
    "IconButton",
    "ActionButton",
    "NavButton",
    "FavoriteButton",
    # 控件
    "SegmentedControl",
    "ScoreSelector",
    "TagCloud",
    "PillTag",
    "StatBadge",
    "MetadataBar",
    # 覆盖层
    "Toast",
    "ShortcutOverlay",
]

import logging
from enum import Enum, auto
from typing import (
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Set,
    Tuple,
)

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config.design_tokens import TOKENS

# =============================================================================
# 模块配置
# =============================================================================

logger = logging.getLogger(__name__)

# 设计令牌快捷引用（避免重复访问属性）
C = TOKENS.colors
S = TOKENS.spacing
T = TOKENS.typography
L = TOKENS.layout


# =============================================================================
# 枚举定义
# =============================================================================


class ButtonStyle(Enum):
    """按钮样式枚举。

    定义可用的按钮视觉风格，用于统一组件外观。

    Attributes:
        DEFAULT: 默认样式（灰色背景）
        PRIMARY: 主要操作样式（强调色背景）
        GHOST: 幽灵样式（透明背景）
        DANGER: 危险操作样式（红色背景）
        SUCCESS: 成功操作样式（绿色背景）
    """

    DEFAULT = auto()
    PRIMARY = auto()
    GHOST = auto()
    DANGER = auto()
    SUCCESS = auto()


class TagType(Enum):
    """标签类型枚举。

    用于区分不同类别的标签，每种类型对应不同的颜色。

    Attributes:
        ARTIST: 作者标签（粉红色）
        CHARACTER: 角色标签（绿色）
        COPYRIGHT: 版权标签（紫色）
        GENERAL: 通用标签（蓝色）
        META: 元数据标签（橙色）
    """

    ARTIST = "artist"
    CHARACTER = "character"
    COPYRIGHT = "copyright"
    GENERAL = "general"
    META = "meta"


# =============================================================================
# 内部工具函数
# =============================================================================


def _get_button_colors(style: ButtonStyle) -> Tuple[str, str, str]:
    """根据按钮样式获取颜色配置。

    Args:
        style: 按钮样式枚举值

    Returns:
        包含 (背景色, 前景色, 悬停色) 的元组
    """
    style_map: Dict[ButtonStyle, Tuple[str, str, str]] = {
        ButtonStyle.DEFAULT: (C.bg_surface, C.text_primary, C.bg_hover),
        ButtonStyle.PRIMARY: (C.accent, C.text_primary, C.accent_hover),
        ButtonStyle.GHOST: ("transparent", C.text_muted, C.bg_hover),
        ButtonStyle.DANGER: (C.error, C.text_primary, "#D32F2F"),
        ButtonStyle.SUCCESS: (C.success, C.text_primary, "#388E3C"),
    }
    return style_map.get(style, style_map[ButtonStyle.DEFAULT])


def _get_string_style_colors(style: str) -> Tuple[str, str, str]:
    """根据字符串样式名获取颜色配置（兼容旧版 API）。

    Args:
        style: 样式名称字符串，可选值:
            'default', 'primary', 'ghost', 'danger', 'success'

    Returns:
        包含 (背景色, 前景色, 悬停色) 的元组

    Note:
        无效的样式名将回退到 'default' 样式
    """
    style_map: Dict[str, Tuple[str, str, str]] = {
        "default": (C.bg_surface, C.text_primary, C.bg_hover),
        "primary": (C.accent, C.text_primary, C.accent_hover),
        "ghost": ("transparent", C.text_muted, C.bg_hover),
        "danger": (C.error, C.text_primary, "#D32F2F"),
        "success": (C.success, C.text_primary, "#388E3C"),
    }
    return style_map.get(style.lower(), style_map["default"])


def _validate_size(size: str, valid_sizes: Tuple[str, ...]) -> str:
    """验证尺寸参数的有效性。

    Args:
        size: 待验证的尺寸字符串
        valid_sizes: 有效尺寸值的元组

    Returns:
        验证后的尺寸字符串，无效值返回第一个有效值

    Raises:
        无，使用安全回退策略
    """
    if size not in valid_sizes:
        logger.warning(
            "无效的尺寸值 '%s'，使用默认值 '%s'",
            size,
            valid_sizes[0],
        )
        return valid_sizes[0]
    return size


# =============================================================================
# UI 工厂类
# =============================================================================


class UIFactory:
    """UI 组件工厂 - 提供快捷的组件创建方法。

    本类采用类方法设计，无需实例化即可使用。
    所有方法返回预配置的 PyQt6 组件，确保风格一致性。

    Example:
        创建带图标的按钮::

            btn = UIFactory.create_icon_button(
                parent=main_window,
                icon="🔧",
                command=lambda: print("clicked"),
                tooltip="设置",
                style="primary"
            )
    """

    @classmethod
    def create_icon_button(
        cls,
        parent: QWidget,
        icon: str,
        command: Callable[[], None],
        tooltip: str = "",
        style: str = "default",
    ) -> QPushButton:
        """创建图标按钮。

        Args:
            parent: 父组件
            icon: 图标字符（支持 Emoji 或符号）
            command: 点击时执行的回调函数
            tooltip: 悬停提示文本，默认为空
            style: 按钮样式，可选 'default'/'primary'/'ghost'/'danger'/'success'

        Returns:
            配置完成的 QPushButton 实例

        Raises:
            TypeError: 当 command 不可调用时
        """
        if not callable(command):
            raise TypeError("command 参数必须是可调用对象")

        bg, fg, hover = _get_string_style_colors(style)

        btn = QPushButton(icon, parent)
        btn.setFixedSize(L.button_height_md, L.button_height_md)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(command)

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: {L.radius_md}px;
                font-family: {T.font_icon};
                font-size: {T.size_lg}px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:pressed {{
                padding-top: 1px;
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)

        if tooltip:
            btn.setToolTip(tooltip)

        return btn

    @classmethod
    def create_action_button(
        cls,
        parent: QWidget,
        text: str,
        command: Callable[[], None],
        style: str = "primary",
        icon: str = "",
        font_size: Optional[int] = None,
    ) -> QPushButton:
        """创建操作按钮（带文本，可选图标）。

        Args:
            parent: 父组件
            text: 按钮显示文本
            command: 点击时执行的回调函数
            style: 按钮样式，默认 'primary'
            icon: 可选的前置图标字符
            font_size: 可选的字体大小（像素），默认使用设计令牌值

        Returns:
            配置完成的 QPushButton 实例
        """
        if not callable(command):
            raise TypeError("command 参数必须是可调用对象")

        # 组合显示文本
        display_text = f"{icon}  {text}" if icon else text
        btn = QPushButton(display_text, parent)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(command)

        # 样式参数
        effective_font_size = font_size if font_size else T.size_md
        padding = f"{S.sm}px {S.lg}px"
        bg, fg, hover = _get_string_style_colors(style)

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: {L.radius_md}px;
                font-family: {T.font_primary};
                font-size: {effective_font_size}px;
                font-weight: {T.weight_medium};
                padding: {padding};
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:pressed {{
                padding-top: 1px;
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)

        return btn

    @classmethod
    def create_nav_button(
        cls,
        parent: QWidget,
        icon: str,
        command: Callable[[], None],
        size: str = "md",
    ) -> QPushButton:
        """创建导航按钮（用于翻页）。

        Args:
            parent: 父组件
            icon: 方向图标字符（如 '◀' 或 '▶'）
            command: 点击时执行的回调函数
            size: 按钮尺寸，可选 'sm'/'md'/'lg'

        Returns:
            配置完成的 QPushButton 实例
        """
        size_map: Dict[str, int] = {
            "sm": L.button_height_sm,
            "md": L.button_height_md,
            "lg": L.button_height_lg,
        }
        validated_size = _validate_size(size, ("sm", "md", "lg"))
        btn_size = size_map[validated_size]

        btn = QPushButton(icon, parent)
        btn.setFixedSize(btn_size, btn_size)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(command)

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C.bg_surface};
                color: {C.text_primary};
                border: none;
                border-radius: {L.radius_md}px;
                font-family: {T.font_icon};
                font-size: {T.size_lg}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {C.bg_hover};
            }}
            QPushButton:pressed {{
                padding-top: 1px;
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)

        return btn

    @classmethod
    def create_like_button(
        cls,
        parent: QWidget,
        command: Callable[[], None],
    ) -> QPushButton:
        """创建收藏/喜欢按钮（心形图标）。

        Args:
            parent: 父组件
            command: 点击时执行的回调函数

        Returns:
            配置完成的 QPushButton 实例

        Note:
            按钮支持 'favorited' 动态属性，用于切换收藏状态样式
        """
        btn = QPushButton("♡", parent)
        btn.setFixedSize(44, 36)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(command)

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C.bg_surface};
                color: {C.text_muted};
                border: none;
                border-radius: {L.radius_md}px;
                font-family: {T.font_icon};
                font-size: {T.size_xl}px;
            }}
            QPushButton:hover {{
                background-color: {C.bg_hover};
                color: {C.accent};
            }}
            QPushButton[favorited="true"] {{
                color: {C.accent};
            }}
        """)

        return btn

    @classmethod
    def create_stat_label(
        cls,
        parent: QWidget,
        icon: str,
        value: str = "0",
        color: str = "primary",
    ) -> QLabel:
        """创建统计标签（图标 + 数值）。

        Args:
            parent: 父组件
            icon: 统计图标字符
            value: 显示的数值文本
            color: 颜色类型，可选:
                'primary', 'secondary', 'muted', 'danger',
                'success', 'warning', 'info'

        Returns:
            配置完成的 QLabel 实例
        """
        color_map: Dict[str, str] = {
            "primary": C.accent,
            "secondary": C.text_secondary,
            "muted": C.text_muted,
            "danger": C.error,
            "success": C.success,
            "warning": C.warning,
            "info": C.info,
        }
        fg = color_map.get(color.lower(), C.accent)

        label = QLabel(f"{icon} {value}", parent)
        label.setStyleSheet(f"""
            QLabel {{
                color: {fg};
                font-family: {T.font_primary};
                font-size: {T.size_sm}px;
            }}
        """)

        return label

    @classmethod
    def create_combo_box(
        cls,
        parent: QWidget,
        items: List[str],
    ) -> QComboBox:
        """创建下拉选择框。

        Args:
            parent: 父组件
            items: 选项文本列表

        Returns:
            配置完成的 QComboBox 实例
        """
        combo = QComboBox(parent)
        combo.addItems(items)
        combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {C.bg_surface};
                color: {C.text_primary};
                border: 1px solid {C.border_default};
                border-radius: {L.radius_md}px;
                padding: {S.xs}px {S.sm}px;
                font-family: {T.font_primary};
                font-size: {T.size_md}px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox::down-arrow {{
                image: none;
                width: 0px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {C.bg_surface};
                color: {C.text_primary};
                selection-background-color: {C.bg_hover};
                selection-color: {C.text_primary};
                border: 1px solid {C.border_default};
                border-radius: {L.radius_md}px;
            }}
        """)
        return combo

    @classmethod
    def create_check_box(
        cls,
        parent: QWidget,
        text: str,
        checked: bool = False,
    ) -> QCheckBox:
        """创建复选框。

        Args:
            parent: 父组件
            text: 复选框标签文本
            checked: 初始选中状态

        Returns:
            配置完成的 QCheckBox 实例
        """
        checkbox = QCheckBox(text, parent)
        checkbox.setChecked(checked)
        checkbox.setStyleSheet(f"""
            QCheckBox {{
                spacing: {S.sm}px;
                color: {C.text_primary};
                font-family: {T.font_primary};
                font-size: {T.size_md}px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {C.border_default};
                border-radius: {L.radius_sm}px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {C.accent};
                border-color: {C.accent};
            }}
            QCheckBox::indicator:hover {{
                border-color: {C.accent};
            }}
        """)
        return checkbox


# =============================================================================
# 基础按钮组件
# =============================================================================


class IconButton(QPushButton):
    """图标按钮组件 - 仅显示图标，无文字。

    适用于工具栏、操作面板等空间紧凑的场景。

    Attributes:
        无公开属性

    Example:
        创建设置按钮::

            btn = IconButton(
                icon="⚙",
                size=32,
                tooltip="设置",
                style=ButtonStyle.DEFAULT
            )
            btn.clicked.connect(self.open_settings)
    """

    def __init__(
        self,
        icon: str,
        parent: Optional[QWidget] = None,
        size: int = L.button_height_md,
        tooltip: str = "",
        style: ButtonStyle = ButtonStyle.DEFAULT,
    ) -> None:
        """初始化图标按钮。

        Args:
            icon: 图标字符（Emoji 或符号）
            parent: 父组件，可为 None
            size: 按钮尺寸（正方形边长，像素）
            tooltip: 悬停提示文本
            style: 按钮样式枚举值
        """
        super().__init__(icon, parent)

        # 参数验证
        if size <= 0:
            logger.warning("无效的按钮尺寸 %d，使用默认值", size)
            size = L.button_height_md

        self.setFixedSize(size, size)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        if tooltip:
            self.setToolTip(tooltip)

        self._apply_style(style)

    def _apply_style(self, style: ButtonStyle) -> None:
        """应用按钮样式。

        Args:
            style: 按钮样式枚举值
        """
        style_map: Dict[ButtonStyle, Tuple[str, str, str]] = {
            ButtonStyle.DEFAULT: (C.bg_surface, C.text_secondary, C.bg_hover),
            ButtonStyle.PRIMARY: (C.accent_muted, C.accent, C.accent_subtle),
            ButtonStyle.GHOST: ("transparent", C.text_muted, C.bg_surface),
            ButtonStyle.DANGER: (f"{C.error}20", C.error, f"{C.error}30"),
            ButtonStyle.SUCCESS: (f"{C.success}20", C.success, f"{C.success}30"),
        }

        bg, fg, hover = style_map.get(style, style_map[ButtonStyle.DEFAULT])

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: {L.radius_md}px;
                font-family: {T.font_icon};
                font-size: {T.size_lg}px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:pressed {{
                background-color: {hover};
                padding-top: 1px;
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)


class ActionButton(QPushButton):
    """操作按钮组件 - 支持图标 + 文字组合。

    适用于表单提交、确认操作等需要明确标识的场景。

    Example:
        创建保存按钮::

            btn = ActionButton(
                text="保存",
                icon="💾",
                style=ButtonStyle.PRIMARY
            )
    """

    def __init__(
        self,
        text: str,
        parent: Optional[QWidget] = None,
        icon: str = "",
        style: ButtonStyle = ButtonStyle.PRIMARY,
        compact: bool = False,
    ) -> None:
        """初始化操作按钮。

        Args:
            text: 按钮文本
            parent: 父组件，可为 None
            icon: 可选的前置图标字符
            style: 按钮样式枚举值
            compact: 是否使用紧凑样式（更小的内边距）
        """
        display_text = f"{icon}  {text}" if icon else text
        super().__init__(display_text, parent)

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # 根据紧凑模式选择参数
        padding = f"{S.xs}px {S.sm}px" if compact else f"{S.sm}px {S.lg}px"
        font_size = T.size_sm if compact else T.size_md
        bg, fg, hover = _get_button_colors(style)

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: {L.radius_md}px;
                font-family: {T.font_primary};
                font-size: {font_size}px;
                font-weight: {T.weight_medium};
                padding: {padding};
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:pressed {{
                padding-top: 1px;
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)


# =============================================================================
# 分段控制器
# =============================================================================


class SegmentedControl(QFrame):
    """分段控制器组件 - 用于多选或单选场景。

    类似 iOS 的分段控制器，支持多个选项的切换。

    Signals:
        selectionChanged(set): 选择变化时发射，携带当前选中键的集合

    Attributes:
        multi_select (bool): 是否允许多选

    Example:
        创建评级选择器::

            control = SegmentedControl(
                options=[
                    ("s", "安全", "#4CAF50"),
                    ("q", "问题", "#FFC107"),
                    ("e", "限制", "#F44336"),
                ],
                multi_select=True
            )
            control.selectionChanged.connect(self.on_rating_change)
    """

    selectionChanged = pyqtSignal(set)

    def __init__(
        self,
        options: List[Tuple[str, str, str]],
        parent: Optional[QWidget] = None,
        multi_select: bool = True,
    ) -> None:
        """初始化分段控制器。

        Args:
            options: 选项列表，每项为 (key, label, color) 元组
                - key: 选项唯一标识符
                - label: 显示文本
                - color: 选中时的颜色（十六进制）
            parent: 父组件
            multi_select: 是否允许多选，默认 True
        """
        super().__init__(parent)

        self.multi_select = multi_select
        self._selected: Set[str] = set()
        self._buttons: Dict[str, Tuple[QPushButton, str]] = {}

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {C.bg_surface};
                border-radius: {L.radius_md}px;
                padding: 2px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        for key, label, color in options:
            btn = self._create_segment(key, label, color)
            layout.addWidget(btn)
            self._buttons[key] = (btn, color)

    def _create_segment(
        self,
        key: str,
        label: str,
        color: str,
    ) -> QPushButton:
        """创建单个分段按钮。

        Args:
            key: 选项标识符
            label: 显示文本
            color: 选中颜色

        Returns:
            配置完成的分段按钮
        """
        btn = QPushButton(label)
        btn.setFixedSize(32, 26)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setCheckable(True)
        btn.setProperty("segment_key", key)
        btn.setProperty("segment_color", color)

        btn.setStyleSheet(self._get_segment_style(color, False))
        btn.toggled.connect(lambda checked, k=key: self._on_toggled(k, checked))

        return btn

    def _get_segment_style(self, color: str, checked: bool) -> str:
        """获取分段按钮的样式表。

        Args:
            color: 分段颜色
            checked: 是否选中状态

        Returns:
            CSS 样式表字符串
        """
        if checked:
            return f"""
                QPushButton {{
                    background-color: {color};
                    color: {C.text_primary};
                    border: none;
                    border-radius: {L.radius_sm}px;
                    font-family: {T.font_primary};
                    font-size: {T.size_sm}px;
                    font-weight: {T.weight_bold};
                }}
            """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {C.text_muted};
                border: none;
                border-radius: {L.radius_sm}px;
                font-family: {T.font_primary};
                font-size: {T.size_sm}px;
                font-weight: {T.weight_medium};
            }}
            QPushButton:hover {{
                background-color: {C.bg_hover};
                color: {color};
            }}
        """

    def _on_toggled(self, key: str, checked: bool) -> None:
        """处理分段切换事件。

        Args:
            key: 被切换的选项标识符
            checked: 新的选中状态
        """
        if self.multi_select:
            if checked:
                self._selected.add(key)
            else:
                self._selected.discard(key)
                # 多选模式下至少保留一个选中项
                if not self._selected:
                    self._selected.add(key)
                    btn, _ = self._buttons[key]
                    btn.blockSignals(True)
                    btn.setChecked(True)
                    btn.blockSignals(False)
        else:
            # 单选模式
            self._selected = {key}
            for k, (btn, _) in self._buttons.items():
                if k != key:
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)

        # 更新所有按钮样式
        for k, (btn, color) in self._buttons.items():
            btn.setStyleSheet(self._get_segment_style(color, k in self._selected))

        self.selectionChanged.emit(self._selected.copy())

    def set_selection(self, keys: Set[str]) -> None:
        """设置选中状态（不触发信号）。

        Args:
            keys: 要选中的键集合
        """
        self._selected = keys.copy()
        for k, (btn, color) in self._buttons.items():
            btn.blockSignals(True)
            btn.setChecked(k in keys)
            btn.setStyleSheet(self._get_segment_style(color, k in keys))
            btn.blockSignals(False)

    def get_selection(self) -> Set[str]:
        """获取当前选中的键集合。

        Returns:
            选中键的集合副本
        """
        return self._selected.copy()


# =============================================================================
# 收藏按钮
# =============================================================================


class FavoriteButton(QPushButton):
    """收藏按钮组件 - 心形图标，带动画效果。

    提供视觉反馈的收藏状态切换按钮。

    Example:
        使用收藏按钮::

            btn = FavoriteButton()
            btn.clicked.connect(self.toggle_favorite)
            btn.set_favorited(True)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化收藏按钮。

        Args:
            parent: 父组件
        """
        super().__init__(parent)

        self._is_favorited = False

        self.setFixedSize(44, 36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._update_style()

        # 弹跳动画配置
        self._scale_anim = QPropertyAnimation(self, b"iconSize")
        self._scale_anim.setDuration(150)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutBack)

    def _update_style(self) -> None:
        """根据当前状态更新按钮样式。"""
        if self._is_favorited:
            icon = "❤"
            bg = C.accent_muted
            fg = C.accent
            hover_bg = C.accent_subtle
        else:
            icon = "♡"
            bg = C.bg_surface
            fg = C.text_muted
            hover_bg = C.bg_hover

        self.setText(icon)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: {L.radius_md}px;
                font-size: {T.size_xl}px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: {C.accent};
            }}
        """)

    def set_favorited(self, value: bool, animate: bool = True) -> None:
        """设置收藏状态。

        Args:
            value: 是否收藏
            animate: 是否播放动画效果
        """
        if self._is_favorited == value:
            return

        self._is_favorited = value
        self._update_style()

        if animate:
            self._scale_anim.setStartValue(QSize(16, 16))
            self._scale_anim.setEndValue(QSize(20, 20))
            self._scale_anim.start()

    def is_favorited(self) -> bool:
        """获取当前收藏状态。

        Returns:
            当前是否已收藏
        """
        return self._is_favorited

    def toggle(self) -> bool:
        """切换收藏状态。

        Returns:
            切换后的新状态
        """
        self.set_favorited(not self._is_favorited)
        return self._is_favorited


# =============================================================================
# 导航按钮
# =============================================================================


class NavButton(QPushButton):
    """导航按钮组件 - 用于上一张/下一张切换。

    Example:
        创建导航按钮对::

            prev_btn = NavButton("prev")
            next_btn = NavButton("next")
    """

    # 有效的方向值
    VALID_DIRECTIONS: Tuple[str, str] = ("prev", "next")

    def __init__(
        self,
        direction: str,
        parent: Optional[QWidget] = None,
        size: int = L.button_height_md,
    ) -> None:
        """初始化导航按钮。

        Args:
            direction: 方向，必须是 'prev' 或 'next'
            parent: 父组件
            size: 按钮尺寸（正方形边长）

        Raises:
            ValueError: 当 direction 不是有效值时
        """
        if direction not in self.VALID_DIRECTIONS:
            raise ValueError(
                f"无效的方向值 '{direction}'，"
                f"必须是 {self.VALID_DIRECTIONS} 之一"
            )

        icon = "◀" if direction == "prev" else "▶"
        super().__init__(icon, parent)

        self._direction = direction
        self.setFixedSize(size, size)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # next 按钮使用主色调
        is_primary = direction == "next"
        bg = C.accent if is_primary else C.bg_surface
        fg = C.text_primary
        hover = C.accent_hover if is_primary else C.bg_hover

        # 按下时的偏移方向
        press_padding = "right" if direction == "prev" else "left"

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: {L.radius_md}px;
                font-size: {T.size_lg}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:pressed {{
                padding-{press_padding}: 2px;
            }}
            QPushButton:disabled {{
                opacity: 0.5;
            }}
        """)


# =============================================================================
# 标签云组件
# =============================================================================


class PillTag(QLabel):
    """胶囊标签组件 - 可点击的单个标签。

    Signals:
        clicked(str): 点击时发射，携带标签文本

    Attributes:
        无公开属性
    """

    clicked = pyqtSignal(str)

    # 作者标签前缀列表
    ARTIST_PREFIXES: Tuple[str, ...] = ("drawn_by_", "artist:")

    def __init__(
        self,
        text: str,
        parent: Optional[QWidget] = None,
        tag_type: TagType = TagType.GENERAL,
    ) -> None:
        """初始化胶囊标签。

        Args:
            text: 标签文本
            parent: 父组件
            tag_type: 标签类型，决定颜色
        """
        super().__init__(text, parent)

        self._tag_text = text
        self._color = self._get_color(tag_type)

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._apply_style(hovered=False)

    @staticmethod
    def _get_color(tag_type: TagType) -> str:
        """根据标签类型获取颜色。

        Args:
            tag_type: 标签类型枚举值

        Returns:
            十六进制颜色字符串
        """
        color_map: Dict[TagType, str] = {
            TagType.ARTIST: C.tag_artist,
            TagType.CHARACTER: C.tag_character,
            TagType.COPYRIGHT: C.tag_copyright,
            TagType.GENERAL: C.tag_general,
            TagType.META: C.tag_meta,
        }
        return color_map.get(tag_type, C.tag_general)

    def _apply_style(self, hovered: bool) -> None:
        """应用样式。

        Args:
            hovered: 是否处于悬停状态
        """
        if hovered:
            bg = self._color
            fg = C.bg_base
        else:
            bg = f"{self._color}20"  # 20% 透明度
            fg = self._color

        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border-radius: {L.radius_pill}px;
                font-family: {T.font_primary};
                font-size: {T.size_xs}px;
                font-weight: {T.weight_medium};
                padding: 2px {S.sm}px;
            }}
        """)

    def enterEvent(self, event) -> None:
        """鼠标进入事件处理。"""
        self._apply_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开事件处理。"""
        self._apply_style(hovered=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        """鼠标点击事件处理。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._tag_text)
        super().mousePressEvent(event)


class TagCloud(QFrame):
    """标签云容器组件 - 显示多个标签。

    自动检测标签类型并应用对应颜色。

    Signals:
        tag_clicked(str): 标签点击时发射

    Attributes:
        max_tags (int): 最大显示标签数
    """

    tag_clicked = pyqtSignal(str)

    # 作者标签前缀
    ARTIST_PREFIXES: Tuple[str, ...] = ("drawn_by_", "artist:")

    # 元数据标签集合
    META_TAGS: FrozenSet[str] = frozenset({
        "tagme",
        "highres",
        "absurdres",
        "incredibly_absurdres",
        "scan",
        "translated",
    })

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        max_tags: int = 12,
    ) -> None:
        """初始化标签云。

        Args:
            parent: 父组件
            max_tags: 最大显示标签数，超出部分显示 "+N"
        """
        super().__init__(parent)

        self.max_tags = max(1, max_tags)  # 确保至少显示 1 个
        self._tags: List[QWidget] = []

        self.setStyleSheet("background-color: transparent;")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(S.xs)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

    def _detect_type(self, tag: str) -> TagType:
        """检测标签类型。

        Args:
            tag: 标签文本

        Returns:
            标签类型枚举值
        """
        if not tag:
            return TagType.GENERAL

        tag_lower = tag.lower()

        # 检测作者标签
        for prefix in self.ARTIST_PREFIXES:
            if tag_lower.startswith(prefix):
                return TagType.ARTIST

        # 检测元数据标签
        if tag_lower in self.META_TAGS:
            return TagType.META

        # 版权标签（通常包含括号）
        if "(" in tag or "_(" in tag:
            return TagType.COPYRIGHT

        # 角色标签（首字母大写）
        if tag and tag[0].isupper():
            return TagType.CHARACTER

        return TagType.GENERAL

    def set_tags(self, tags_str: str) -> None:
        """设置标签内容。

        Args:
            tags_str: 空格分隔的标签字符串
        """
        # 清除现有标签
        self.clear()

        if not tags_str or not tags_str.strip():
            return

        # 解析并过滤空标签
        all_tags = [t for t in tags_str.split() if t]
        display_tags = all_tags[: self.max_tags]

        for tag_text in display_tags:
            tag_type = self._detect_type(tag_text)

            # 清理显示文本：移除前缀，替换下划线
            display = tag_text
            for prefix in self.ARTIST_PREFIXES:
                if display.lower().startswith(prefix):
                    display = display[len(prefix) :]
                    break
            display = display.replace("_", " ")

            pill = PillTag(display, self, tag_type)
            pill.clicked.connect(self.tag_clicked.emit)
            self._layout.addWidget(pill)
            self._tags.append(pill)

        # 显示剩余标签数量
        remaining = len(all_tags) - self.max_tags
        if remaining > 0:
            more_label = QLabel(f"+{remaining}")
            more_label.setStyleSheet(f"""
                QLabel {{
                    color: {C.text_muted};
                    font-size: {T.size_xs}px;
                    padding: 0 {S.xs}px;
                }}
            """)
            self._layout.addWidget(more_label)
            self._tags.append(more_label)

    def clear(self) -> None:
        """清除所有标签。"""
        for tag_widget in self._tags:
            tag_widget.deleteLater()
        self._tags.clear()


# =============================================================================
# 统计徽章
# =============================================================================


class StatBadge(QFrame):
    """统计徽章组件 - 图标 + 数值组合。

    Example:
        创建评分徽章::

            badge = StatBadge("★", "42", color=C.accent)
            badge.set_value("43")  # 更新数值
    """

    def __init__(
        self,
        icon: str,
        value: str = "0",
        parent: Optional[QWidget] = None,
        color: Optional[str] = None,
    ) -> None:
        """初始化统计徽章。

        Args:
            icon: 图标字符
            value: 初始显示值
            parent: 父组件
            color: 文字颜色（十六进制），默认使用次要文字色
        """
        super().__init__(parent)

        self._color = color or C.text_secondary

        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.xxs)

        self._icon_label = QLabel(icon)
        self._icon_label.setStyleSheet(f"""
            color: {self._color};
            font-family: {T.font_icon};
            font-size: {T.size_md}px;
        """)
        layout.addWidget(self._icon_label)

        self._value_label = QLabel(value)
        self._value_label.setStyleSheet(f"""
            color: {self._color};
            font-family: {T.font_mono};
            font-size: {T.size_sm}px;
            font-weight: {T.weight_medium};
        """)
        layout.addWidget(self._value_label)

    def set_value(self, value: str) -> None:
        """更新显示值。

        Args:
            value: 新的显示值
        """
        self._value_label.setText(value)

    def set_color(self, color: str) -> None:
        """更新颜色。

        Args:
            color: 新的颜色值（十六进制）
        """
        self._color = color
        self._icon_label.setStyleSheet(
            f"color: {color}; font-size: {T.size_md}px;"
        )
        self._value_label.setStyleSheet(
            f"color: {color}; font-size: {T.size_sm}px;"
        )


# =============================================================================
# Toast 通知
# =============================================================================


class Toast(QFrame):
    """Toast 浮动通知组件 - 短暂显示信息。

    Example:
        显示成功消息::

            toast = Toast(parent_window)
            toast.show_message("保存成功", "✓", style="success")
    """

    # 样式对应的默认图标
    DEFAULT_ICONS: Dict[str, str] = {
        "info": "ℹ️",
        "success": "✓",
        "warning": "⚠️",
        "error": "✗",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化 Toast 组件。

        Args:
            parent: 父组件（用于定位）
        """
        super().__init__(parent)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {C.bg_overlay};
                border-radius: {L.radius_lg}px;
                padding: {S.sm}px {S.lg}px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(S.md, S.sm, S.md, S.sm)

        self._icon = QLabel()
        self._icon.setStyleSheet(f"font-size: {T.size_lg}px;")
        layout.addWidget(self._icon)

        self._message = QLabel()
        self._message.setStyleSheet(f"""
            color: {C.text_primary};
            font-family: {T.font_primary};
            font-size: {T.size_sm}px;
        """)
        layout.addWidget(self._message)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

        self.hide()

    def show_message(
        self,
        message: str,
        icon: str = "",
        duration: int = 2000,
        style: str = "info",
    ) -> None:
        """显示通知消息。

        Args:
            message: 消息文本
            icon: 可选的图标字符，为空时使用样式默认图标
            duration: 显示时长（毫秒）
            style: 样式类型 ('info'/'success'/'warning'/'error')
        """
        # 使用提供的图标或默认图标
        display_icon = icon or self.DEFAULT_ICONS.get(style, "ℹ️")
        self._icon.setText(display_icon)
        self._message.setText(message)

        # 定位到父窗口右上角
        if self.parent():
            parent = self.parent()
            self.adjustSize()
            x = parent.width() - self.width() - S.lg
            y = S.lg
            self.move(max(0, x), max(0, y))

        self.show()
        self.raise_()

        self._timer.start(duration)

    def _fade_out(self) -> None:
        """隐藏 Toast。"""
        self.hide()


# =============================================================================
# 快捷键帮助遮罩
# =============================================================================


class ShortcutOverlay(QFrame):
    """快捷键帮助遮罩层 - 现代化沉浸式设计。

    按任意键或点击任意位置关闭。

    设计原则:
        - 视觉层次：标题 > 分组 > 条目
        - 格式塔分组：按功能聚类
        - 呼吸感：充足的留白
        - 键盘风格：模拟实体按键
    """

    # 快捷键分组配置
    SHORTCUT_GROUPS: List[Dict] = [
        {
            "title": "浏览导航",
            "icon": "🧭",
            "color": "#64B5F6",
            "shortcuts": [
                ("←", "上一张"),
                ("→", "下一张"),
                ("Space", "快速下一张"),
            ],
        },
        {
            "title": "收藏管理",
            "icon": "♥",
            "color": "#F48FB1",
            "shortcuts": [
                ("L", "收藏 / 取消"),
                ("M", "收藏夹管理"),
            ],
        },
        {
            "title": "显示控制",
            "icon": "◐",
            "color": "#81C784",
            "shortcuts": [
                ("F", "切换全屏"),
                ("R", "重新加载"),
                ("Z", "最小化窗口"),
            ],
        },
        {
            "title": "筛选与设置",
            "icon": "✦",
            "color": "#FFD54F",
            "shortcuts": [
                ("1-5", "快速分数筛选"),
                ("S", "切换浏览模式"),
                ("P", "打开设置"),
                ("B", "备份管理"),
            ],
        },
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化快捷键帮助遮罩。

        Args:
            parent: 父组件
        """
        super().__init__(parent)

        # 设置半透明深色背景
        self.setStyleSheet("""
            ShortcutOverlay {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(15, 15, 20, 0.95),
                    stop:1 rgba(25, 25, 35, 0.95)
                );
            }
        """)

        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        """构建界面布局。"""
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setContentsMargins(S.xxl, S.xxl, S.xxl, S.xxl)

        # 头部区域
        header = self._create_header()
        main_layout.addWidget(header)
        main_layout.addSpacing(S.xl)

        # 快捷键卡片网格
        cards_container = self._create_cards_grid()
        main_layout.addWidget(
            cards_container, alignment=Qt.AlignmentFlag.AlignCenter
        )
        main_layout.addSpacing(S.xl)

        # 底部提示
        footer = self._create_footer()
        main_layout.addWidget(footer)

    def _create_header(self) -> QFrame:
        """创建头部标题区域。

        Returns:
            头部容器组件
        """
        header = QFrame()
        header.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.sm)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 主标题
        title = QLabel("Keyboard Shortcuts")
        title.setFixedHeight(40)
        title.setStyleSheet(f"""
            QLabel {{
                color: {C.text_primary};
                font-family: {T.font_primary};
                font-size: 28px;
                font-weight: 300;
                letter-spacing: 4px;
                background: transparent;
            }}
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 装饰线
        line = QFrame()
        line.setFixedSize(120, 2)
        line.setStyleSheet(f"""
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 transparent,
                stop:0.2 {C.accent},
                stop:0.8 {C.accent},
                stop:1 transparent
            );
        """)
        layout.addWidget(line, alignment=Qt.AlignmentFlag.AlignCenter)

        # 副标题
        subtitle = QLabel("提升您的浏览效率")
        subtitle.setMinimumHeight(24)
        subtitle.setStyleSheet(f"""
            QLabel {{
                color: {C.text_muted};
                font-family: {T.font_primary};
                font-size: {T.size_sm}px;
                letter-spacing: 2px;
                background: transparent;
            }}
        """)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        return header

    def _create_cards_grid(self) -> QFrame:
        """创建快捷键卡片网格。

        Returns:
            卡片网格容器
        """
        container = QFrame()
        container.setStyleSheet("background: transparent;")

        grid_layout = QHBoxLayout(container)
        grid_layout.setSpacing(S.lg)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        # 分两列布局
        left_column = QVBoxLayout()
        left_column.setSpacing(S.lg)

        right_column = QVBoxLayout()
        right_column.setSpacing(S.lg)

        for i, group in enumerate(self.SHORTCUT_GROUPS):
            card = self._create_shortcut_card(group)
            if i % 2 == 0:
                left_column.addWidget(card)
            else:
                right_column.addWidget(card)

        grid_layout.addLayout(left_column)
        grid_layout.addLayout(right_column)

        return container

    def _create_shortcut_card(self, group: Dict) -> QFrame:
        """创建单个快捷键分组卡片。

        Args:
            group: 分组配置字典

        Returns:
            卡片组件
        """
        card = QFrame()
        card.setFixedWidth(280)
        card.setObjectName("shortcutCard")

        color = group.get("color", C.accent)

        card.setStyleSheet(f"""
            QFrame#shortcutCard {{
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: {L.radius_lg}px;
            }}
            QFrame#shortcutCard:hover {{
                background-color: rgba(255, 255, 255, 0.05);
                border-color: {color}40;
            }}
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(S.md + 4, S.md + 4, S.md + 4, S.md + 4)
        layout.setSpacing(S.sm)

        # 卡片头部
        header = self._create_card_header(group["icon"], group["title"], color)
        layout.addWidget(header)

        # 分隔线
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {color}30; border: none;")
        layout.addWidget(separator)
        layout.addSpacing(S.xs)

        # 快捷键列表
        for key, desc in group["shortcuts"]:
            row = self._create_shortcut_row(key, desc, color)
            layout.addWidget(row)

        return card

    def _create_card_header(
        self,
        icon: str,
        title: str,
        color: str,
    ) -> QFrame:
        """创建卡片头部。

        Args:
            icon: 图标字符
            title: 标题文本
            color: 主题色

        Returns:
            头部组件
        """
        header = QFrame()
        header.setStyleSheet("background: transparent; border: none;")
        header.setMinimumHeight(28)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.sm)

        # 图标
        icon_label = QLabel(icon)
        icon_label.setFixedSize(24, 24)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 16px;
                background: transparent;
                border: none;
            }}
        """)
        layout.addWidget(icon_label)

        # 标题
        title_label = QLabel(title)
        title_label.setMinimumHeight(24)
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-family: {T.font_primary};
                font-size: {T.size_md}px;
                font-weight: {T.weight_medium};
                background: transparent;
                border: none;
            }}
        """)
        layout.addWidget(title_label)
        layout.addStretch()

        return header

    def _create_shortcut_row(
        self,
        key: str,
        desc: str,
        accent_color: str,
    ) -> QFrame:
        """创建单行快捷键条目。

        Args:
            key: 按键文本
            desc: 功能描述
            accent_color: 强调色

        Returns:
            行组件
        """
        row = QFrame()
        row.setMinimumHeight(32)
        row.setStyleSheet("background: transparent; border: none;")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(S.md)

        # 键盘按键样式
        key_label = QLabel(key)
        key_label.setFixedHeight(26)
        key_label.setMinimumWidth(48)
        key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        key_label.setStyleSheet(f"""
            QLabel {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(60, 60, 70, 0.8),
                    stop:1 rgba(40, 40, 50, 0.8)
                );
                color: {C.text_primary};
                font-family: {T.font_mono};
                font-size: {T.size_sm}px;
                font-weight: {T.weight_medium};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
            }}
        """)
        layout.addWidget(key_label)

        # 描述文本
        desc_label = QLabel(desc)
        desc_label.setFixedHeight(24)
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {C.text_secondary};
                font-family: {T.font_primary};
                font-size: {T.size_sm}px;
                background: transparent;
                border: none;
            }}
        """)
        layout.addWidget(desc_label)
        layout.addStretch()

        return row

    def _create_footer(self) -> QFrame:
        """创建底部提示区域。

        Returns:
            底部组件
        """
        footer = QFrame()
        footer.setMinimumHeight(60)
        footer.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.sm)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 关闭提示
        hint_container = QFrame()
        hint_container.setFixedHeight(32)
        hint_container.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(255, 255, 255, 0.05);
                border-radius: {L.radius_pill}px;
            }}
        """)

        hint_layout = QHBoxLayout(hint_container)
        hint_layout.setContentsMargins(S.md, 0, S.md, 0)
        hint_layout.setSpacing(S.sm)
        hint_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ESC 按键
        esc_label = QLabel("ESC")
        esc_label.setFixedSize(36, 20)
        esc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        esc_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 0.1);
                color: {C.text_muted};
                font-family: {T.font_mono};
                font-size: {T.size_xs}px;
                border-radius: 4px;
            }}
        """)
        hint_layout.addWidget(esc_label)

        # 提示文本
        hint_text = QLabel("或点击任意位置关闭")
        hint_text.setFixedHeight(20)
        hint_text.setStyleSheet(f"""
            QLabel {{
                color: {C.text_muted};
                font-family: {T.font_primary};
                font-size: {T.size_xs}px;
                background: transparent;
            }}
        """)
        hint_layout.addWidget(hint_text)

        layout.addWidget(
            hint_container, alignment=Qt.AlignmentFlag.AlignCenter
        )

        # 版本信息
        version_label = QLabel("Yande.re Viewer · Made with ♥")
        version_label.setFixedHeight(18)
        version_label.setStyleSheet(f"""
            QLabel {{
                color: rgba(255, 255, 255, 0.2);
                font-family: {T.font_primary};
                font-size: 10px;
                letter-spacing: 1px;
                background: transparent;
            }}
        """)
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        return footer

    def showEvent(self, event) -> None:
        """显示事件处理 - 填满父窗口。"""
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().showEvent(event)

    def keyPressEvent(self, event) -> None:
        """按键事件处理 - 任意键关闭。"""
        self.hide()
        event.accept()

    def mousePressEvent(self, event) -> None:
        """鼠标点击事件处理 - 任意点击关闭。"""
        self.hide()
        event.accept()


# =============================================================================
# 元数据显示条
# =============================================================================


class MetadataBar(QFrame):
    """元数据显示条组件 - 显示图片信息。

    显示内容包括：帖子 ID、评分、分辨率、文件大小。

    Example:
        更新元数据::

            bar = MetadataBar()
            bar.update_data(
                post_id=12345,
                score=42,
                width=1920,
                height=1080,
                file_size=2048000
            )
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化元数据显示条。

        Args:
            parent: 父组件
        """
        super().__init__(parent)

        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.md)

        # ID 标签（次要信息）
        self._id_label = QLabel()
        self._id_label.setStyleSheet(f"""
            color: {C.text_muted};
            font-family: {T.font_mono};
            font-size: {T.size_xs}px;
        """)
        layout.addWidget(self._id_label)

        self._add_separator(layout)

        # 分数标签（重要信息）
        self._score_label = QLabel()
        self._score_label.setStyleSheet(f"""
            color: {C.accent};
            font-family: {T.font_mono};
            font-size: {T.size_sm}px;
            font-weight: bold;
        """)
        layout.addWidget(self._score_label)

        self._add_separator(layout)

        # 分辨率标签（重要信息）
        self._resolution_label = QLabel()
        self._resolution_label.setStyleSheet(f"""
            color: {C.text_primary};
            font-family: {T.font_mono};
            font-size: {T.size_sm}px;
            font-weight: {T.weight_medium};
        """)
        layout.addWidget(self._resolution_label)

        self._add_separator(layout)

        # 文件大小标签（次要信息）
        self._size_label = QLabel()
        self._size_label.setStyleSheet(f"""
            color: {C.text_muted};
            font-family: {T.font_mono};
            font-size: {T.size_xs}px;
        """)
        layout.addWidget(self._size_label)

        # 已保存标记
        self._saved_badge = QLabel("💾")
        self._saved_badge.setStyleSheet(f"font-size: {T.size_md}px;")
        self._saved_badge.hide()
        layout.addWidget(self._saved_badge)

        layout.addStretch()

    @staticmethod
    def _add_separator(layout: QHBoxLayout) -> None:
        """添加分隔符到布局。

        Args:
            layout: 目标布局
        """
        sep = QLabel("│")
        sep.setStyleSheet(f"color: {C.border_default};")
        layout.addWidget(sep)

    def update_data(
        self,
        post_id: int,
        score: int,
        width: int,
        height: int,
        file_size: int,
        is_saved: bool = False,
    ) -> None:
        """更新显示数据。

        Args:
            post_id: 帖子 ID
            score: 评分
            width: 图片宽度（像素）
            height: 图片高度（像素）
            file_size: 文件大小（字节）
            is_saved: 是否已保存到本地
        """
        self._id_label.setText(f"#{post_id}")
        self._score_label.setText(f"★ {score}")
        self._resolution_label.setText(f"{width}×{height}")

        # 格式化文件大小
        size_mb = file_size / 1024 / 1024
        self._size_label.setText(f"{size_mb:.1f} MB")

        self._saved_badge.setVisible(is_saved)


# =============================================================================
# 分数选择器
# =============================================================================


class ScoreSelector(QFrame):
    """分数阈值选择器组件 - 按钮组样式。

    Signals:
        valueChanged(int): 值改变时发射，携带新的阈值

    Attributes:
        OPTIONS: 可选的分数阈值列表
    """

    valueChanged = pyqtSignal(int)

    # 预定义的分数阈值选项
    OPTIONS: List[Tuple[int, str]] = [
        (0, "All"),
        (5, "5+"),
        (15, "15+"),
        (30, "30+"),
        (50, "50+"),
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化分数选择器。

        Args:
            parent: 父组件
        """
        super().__init__(parent)

        self._value = 0
        self._buttons: Dict[int, QPushButton] = {}

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {C.bg_surface};
                border-radius: {L.radius_md}px;
                padding: 2px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        # 前置图标
        icon = QLabel("★")
        icon.setStyleSheet(f"""
            color: {C.text_muted};
            font-size: {T.size_sm}px;
            padding: 0 {S.xs}px;
        """)
        layout.addWidget(icon)

        # 创建选项按钮
        for value, label in self.OPTIONS:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setMinimumWidth(32)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda _, v=value: self._select(v))

            self._buttons[value] = btn
            layout.addWidget(btn)

        self._update_styles()

    def _select(self, value: int) -> None:
        """选择指定值。

        Args:
            value: 要选择的阈值
        """
        if self._value == value:
            return

        self._value = value
        self._update_styles()
        self.valueChanged.emit(value)

    def _update_styles(self) -> None:
        """更新所有按钮的样式。"""
        for val, btn in self._buttons.items():
            is_selected = val == self._value

            if is_selected:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {C.accent};
                        color: {C.text_primary};
                        border: none;
                        border-radius: {L.radius_sm}px;
                        font-size: {T.size_xs}px;
                        font-weight: bold;
                        padding: 0 {S.xs}px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {C.text_muted};
                        border: none;
                        border-radius: {L.radius_sm}px;
                        font-size: {T.size_xs}px;
                        padding: 0 {S.xs}px;
                    }}
                    QPushButton:hover {{
                        background-color: {C.bg_hover};
                        color: {C.text_secondary};
                    }}
                """)

    def set_value(self, value: int) -> None:
        """设置当前值（不触发信号）。

        Args:
            value: 要设置的阈值

        Note:
            如果传入的值不在有效选项中，将记录警告并忽略
        """
        if value not in self._buttons:
            logger.warning("无效的分数阈值: %d", value)
            return
        self._value = value
        self._update_styles()

    def get_value(self) -> int:
        """获取当前选中的阈值。

        Returns:
            当前阈值
        """
        return self._value