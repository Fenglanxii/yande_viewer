"""
设计令牌系统。

统一管理所有视觉变量，包括：
- 颜色 (ColorTokens)
- 间距 (Spacing)
- 字体 (Typography)
- 布局 (Layout)
- 动画 (Animation)

这些令牌是不可变的（frozen dataclass），确保在运行时不会被意外修改。

Example
-------
>>> from config import TOKENS, C, S, T, L, A
>>> background = C.bg_base
>>> accent = C.accent
>>> padding = S.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class ColorTokens:
    """
    颜色令牌。

    所有颜色值使用十六进制格式（#RRGGBB）。

    命名规范
    --------
    - bg_* : 背景色
    - text_* : 文字色
    - rating_* : 评级相关色
    - tag_* : 标签色

    Attributes
    ----------
    bg_base : str
        主背景色（最深）
    bg_surface : str
        表面背景色
    accent : str
        主强调色
    """

    # 基础背景色
    bg_base: str = "#1E1E1E"
    bg_surface: str = "#2D2D30"
    bg_hover: str = "#3E3E42"
    bg_elevated: str = "#252526"
    bg_overlay: str = "#2A2A2A"

    # 文字色
    text_primary: str = "#FFFFFF"
    text_secondary: str = "#CCCCCC"
    text_muted: str = "#AAAAAA"

    # 强调色
    accent: str = "#E91E63"
    accent_hover: str = "#C2185B"
    accent_muted: str = "#D81B60"
    accent_subtle: str = "#AD1457"
    primary_hover: str = "#C2185B"

    # 边框色
    border_default: str = "#454545"
    border_subtle: str = "#3A3A3A"

    # 语义色
    error: str = "#F44336"
    warning: str = "#FF9800"
    success: str = "#4CAF50"
    success_muted: str = "#388E3C"
    info: str = "#2196F3"

    # 评级颜色
    rating_safe: str = "#4CAF50"
    rating_questionable: str = "#FFC107"
    rating_explicit: str = "#F44336"

    # 评级颜色（低饱和度版本，适用于背景）
    rating_safe_bg: str = "#1B3D2F"
    rating_safe_text: str = "#7FD4A8"
    rating_questionable_bg: str = "#3D2E1B"
    rating_questionable_text: str = "#D4A87F"
    rating_explicit_bg: str = "#3D1B1B"
    rating_explicit_text: str = "#D47F7F"

    # 滑动条颜色
    slider_track: str = "#404040"
    slider_track_active: str = "#E91E63"

    # 其他
    value_display: str = "#EEEEEE"

    # 标签颜色
    tag_artist: str = "#BA68C8"
    tag_character: str = "#4FC3F7"
    tag_copyright: str = "#81C784"
    tag_general: str = "#FFB74D"
    tag_meta: str = "#B0BEC5"

    def get_rating_colors(self, rating: str) -> Tuple[str, str]:
        """
        获取评级对应的背景色和文字色。

        Parameters
        ----------
        rating : str
            评级标识，可选值: 's'(safe), 'q'(questionable), 'e'(explicit)

        Returns
        -------
        tuple of str
            (背景色, 文字色) 元组
        """
        mapping = {
            "s": (self.rating_safe_bg, self.rating_safe_text),
            "q": (self.rating_questionable_bg, self.rating_questionable_text),
            "e": (self.rating_explicit_bg, self.rating_explicit_text),
        }
        return mapping.get(rating.lower(), (self.bg_surface, self.text_primary))

    def get_tag_color(self, tag_type: str) -> str:
        """
        获取标签类型对应的颜色。

        Parameters
        ----------
        tag_type : str
            标签类型: 'artist', 'character', 'copyright', 'general', 'meta'

        Returns
        -------
        str
            颜色值
        """
        mapping = {
            "artist": self.tag_artist,
            "character": self.tag_character,
            "copyright": self.tag_copyright,
            "general": self.tag_general,
            "meta": self.tag_meta,
        }
        return mapping.get(tag_type.lower(), self.text_secondary)


@dataclass(frozen=True)
class Spacing:
    """
    间距系统。

    基于 4px 基准的间距阶梯。

    Attributes
    ----------
    xxs : int
        极小间距 (2px)
    xs : int
        超小间距 (4px)
    sm : int
        小间距 (8px)
    md : int
        中间距 (12px)
    lg : int
        大间距 (16px)
    xl : int
        超大间距 (24px)
    xxl : int
        极大间距 (32px)
    xxxl : int
        超极大间距 (48px)
    """

    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    xxxl: int = 48

    def scale(self, multiplier: float) -> int:
        """
        基于中等间距进行缩放。

        Parameters
        ----------
        multiplier : float
            缩放倍数

        Returns
        -------
        int
            缩放后的间距值
        """
        return int(self.md * multiplier)


@dataclass(frozen=True)
class Typography:
    """
    字体系统。

    包含字体族、字号和字重的定义。

    Attributes
    ----------
    font_primary : str
        主要字体族
    font_mono : str
        等宽字体族
    size_md : int
        中等字号 (13px)
    weight_normal : int
        正常字重 (400)
    """

    # 字体族
    font_primary: str = "'Segoe UI', 'Microsoft YaHei UI', sans-serif"
    font_mono: str = "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace"
    font_icon: str = "'Segoe Fluent Icons', 'Segoe UI Emoji'"

    # 字号
    size_xs: int = 10
    size_sm: int = 11
    size_md: int = 13
    size_lg: int = 15
    size_xl: int = 18
    size_xxl: int = 24

    # 字重
    weight_normal: int = 400
    weight_medium: int = 500
    weight_bold: int = 600

    # 兼容旧版别名
    @property
    def font_xs(self) -> int:
        """兼容旧版：使用 size_xs 代替。"""
        return self.size_xs

    @property
    def font_sm(self) -> int:
        """兼容旧版：使用 size_sm 代替。"""
        return self.size_sm

    @property
    def font_md(self) -> int:
        """兼容旧版：使用 size_md 代替。"""
        return self.size_md

    @property
    def font_lg(self) -> int:
        """兼容旧版：使用 size_lg 代替。"""
        return self.size_lg

    @property
    def font_xl(self) -> int:
        """兼容旧版：使用 size_xl 代替。"""
        return self.size_xl

    @property
    def font_xxl(self) -> int:
        """兼容旧版：使用 size_xxl 代替。"""
        return self.size_xxl


@dataclass(frozen=True)
class Layout:
    """
    布局尺寸。

    定义各种 UI 元素的标准尺寸。

    Attributes
    ----------
    toolbar_height : int
        工具栏高度 (48px)
    button_height_md : int
        中等按钮高度 (36px)
    radius_md : int
        中等圆角 (6px)
    """

    # 区域高度
    toolbar_height: int = 48
    statusbar_height: int = 72
    helpbar_height: int = 28

    # 按钮尺寸
    button_height_sm: int = 28
    button_height_md: int = 36
    button_height_lg: int = 44
    button_min_width: int = 44

    # 图标尺寸
    icon_size_sm: int = 16
    icon_size_md: int = 20
    icon_size_lg: int = 24

    # 圆角
    radius_sm: int = 4
    radius_md: int = 6
    radius_lg: int = 8
    radius_xl: int = 12
    radius_pill: int = 999


@dataclass(frozen=True)
class Animation:
    """
    动画时长配置。

    所有时长单位为毫秒（ms）。

    Attributes
    ----------
    instant : int
        即时响应 (50ms)
    fast : int
        快速动画 (150ms)
    normal : int
        正常动画 (250ms)
    slow : int
        慢速动画 (400ms)
    """

    instant: int = 50
    fast: int = 150
    normal: int = 250
    slow: int = 400

    # 兼容旧版别名
    @property
    def duration_fast(self) -> int:
        """兼容旧版：使用 fast 代替。"""
        return self.fast

    @property
    def duration_normal(self) -> int:
        """兼容旧版：使用 normal 代替。"""
        return self.normal

    @property
    def duration_slow(self) -> int:
        """兼容旧版：使用 slow 代替。"""
        return self.slow


@dataclass(frozen=True)
class DesignTokens:
    """
    设计令牌聚合类。

    包含所有设计令牌的顶级容器。

    Attributes
    ----------
    colors : ColorTokens
        颜色令牌
    spacing : Spacing
        间距令牌
    typography : Typography
        字体令牌
    layout : Layout
        布局令牌
    animation : Animation
        动画令牌
    """

    colors: ColorTokens = field(default_factory=ColorTokens)
    spacing: Spacing = field(default_factory=Spacing)
    typography: Typography = field(default_factory=Typography)
    layout: Layout = field(default_factory=Layout)
    animation: Animation = field(default_factory=Animation)

    # 快捷访问
    @property
    def space_xs(self) -> int:
        """快捷访问：极小间距。"""
        return self.spacing.xs

    @property
    def space_sm(self) -> int:
        """快捷访问：小间距。"""
        return self.spacing.sm

    @property
    def space_md(self) -> int:
        """快捷访问：中间距。"""
        return self.spacing.md

    @property
    def space_lg(self) -> int:
        """快捷访问：大间距。"""
        return self.spacing.lg

    @property
    def space_xl(self) -> int:
        """快捷访问：超大间距。"""
        return self.spacing.xl


# =============================================================================
# 全局单例
# =============================================================================

TOKENS = DesignTokens()