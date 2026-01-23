# -*- coding: utf-8 -*-
"""备份恢复对话框模块。

本模块提供数据备份和恢复功能的用户界面，支持高 DPI 显示、
跨平台字体渲染及完善的错误处理。

主要特性:
    - 跨平台 CJK 字体支持 (Windows/macOS/Linux)
    - 高 DPI 自适应缩放
    - Emoji 正确渲染
    - 完善的错误处理和日志记录

Example:
    基本用法::

        from ui.dialogs.backup_dialog import BackupRestoreDialog

        dialog = BackupRestoreDialog(parent=main_window)
        dialog.backup_completed.connect(on_backup_done)
        dialog.restore_completed.connect(on_restore_done)
        dialog.exec()

Note:
    本模块依赖 PyQt6，请确保已正确安装。

License:
    MIT License
"""

from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional, Set

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from core.download_manager import DownloadManager
    from utils.backup_manager import BackupManager

# 模块级日志器
logger = logging.getLogger("YandeViewer.UI.BackupDialog")


# ============================================================
# 设计令牌 (Design Tokens)
# ============================================================


@dataclass(frozen=True)
class ColorTokens:
    """颜色设计令牌（暗色主题）。

    使用 frozen=True 确保实例不可变，保证线程安全。

    Attributes:
        bg_base: 基础背景色。
        bg_surface: 表面背景色。
        bg_elevated: 提升层背景色。
        bg_hover: 悬停状态背景色。
        bg_pressed: 按下状态背景色。
        text_primary: 主要文字颜色。
        text_secondary: 次要文字颜色。
        text_muted: 弱化文字颜色。
        text_disabled: 禁用状态文字颜色。
        info: 信息色。
        info_hover: 信息色悬停状态。
        info_pressed: 信息色按下状态。
        success: 成功色。
        success_hover: 成功色悬停状态。
        success_pressed: 成功色按下状态。
        warning: 警告色。
        warning_bg: 警告背景色。
        error: 错误色。
        border: 边框颜色。
        border_hover: 边框悬停颜色。
    """

    # 背景色
    bg_base: str = "#1E1E1E"
    bg_surface: str = "#2D2D30"
    bg_elevated: str = "#333337"
    bg_hover: str = "#3E3E42"
    bg_pressed: str = "#1A1A1A"

    # 文字色
    text_primary: str = "#FFFFFF"
    text_secondary: str = "#CCCCCC"
    text_muted: str = "#9D9D9D"
    text_disabled: str = "#666666"

    # 语义色
    info: str = "#2196F3"
    info_hover: str = "#1976D2"
    info_pressed: str = "#1565C0"
    success: str = "#4CAF50"
    success_hover: str = "#43A047"
    success_pressed: str = "#388E3C"
    warning: str = "#FF9800"
    warning_bg: str = "rgba(255, 152, 0, 0.12)"
    error: str = "#F44336"

    # 边框色
    border: str = "#3E3E42"
    border_hover: str = "#5A5A5E"


@dataclass(frozen=True)
class SpacingTokens:
    """间距设计令牌（基于 4px 网格）。

    所有间距值均为像素单位。

    Attributes:
        xxs: 超小间距 (2px)。
        xs: 极小间距 (4px)。
        sm: 小间距 (8px)。
        md: 中等间距 (12px)。
        lg: 大间距 (16px)。
        xl: 超大间距 (20px)。
        xxl: 极大间距 (24px)。
        xxxl: 最大间距 (32px)。
    """

    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 20
    xxl: int = 24
    xxxl: int = 32


@dataclass(frozen=True)
class TypographyTokens:
    """排版设计令牌。

    Attributes:
        size_xs: 超小字号 (11px)。
        size_sm: 小字号 (12px)。
        size_md: 中等字号 (13px)。
        size_lg: 大字号 (14px)。
        size_xl: 超大字号 (16px)。
        size_xxl: 极大字号 (18px)。
        size_emoji: Emoji 字号 (16px)。
        line_height: 标准行高倍数。
        line_height_tight: 紧凑行高倍数。
        weight_normal: 正常字重。
        weight_medium: 中等字重。
        weight_bold: 粗体字重。
    """

    # 字体大小 (px)
    size_xs: int = 11
    size_sm: int = 12
    size_md: int = 13
    size_lg: int = 14
    size_xl: int = 16
    size_xxl: int = 18
    size_emoji: int = 16

    # 行高
    line_height: float = 1.5
    line_height_tight: float = 1.3

    # 字重
    weight_normal: int = 400
    weight_medium: int = 500
    weight_bold: int = 600


@dataclass(frozen=True)
class LayoutTokens:
    """布局设计令牌。

    Attributes:
        radius_sm: 小圆角 (4px)。
        radius_md: 中等圆角 (6px)。
        radius_lg: 大圆角 (8px)。
        button_height_sm: 小按钮高度 (32px)。
        button_height_md: 中等按钮高度 (38px)。
        button_height_lg: 大按钮高度 (44px)。
        dialog_width: 对话框宽度 (480px)。
        dialog_min_height: 对话框最小高度 (520px)。
    """

    radius_sm: int = 4
    radius_md: int = 6
    radius_lg: int = 8

    button_height_sm: int = 32
    button_height_md: int = 38
    button_height_lg: int = 44

    dialog_width: int = 480
    dialog_min_height: int = 520


# 全局设计令牌实例
COLORS = ColorTokens()
SPACING = SpacingTokens()
TYPO = TypographyTokens()
LAYOUT = LayoutTokens()


# ============================================================
# 字体管理器
# ============================================================


class FontManager:
    """跨平台字体管理器（单例模式）。

    自动检测系统可用的 CJK 和 Emoji 字体，提供统一的字体获取接口。
    支持 Windows、macOS 和 Linux 平台。

    Attributes:
        dpi_scale: 当前屏幕的 DPI 缩放比例。
        cjk_family: 检测到的 CJK 字体族名称。
        emoji_family: 检测到的 Emoji 字体族名称。

    Example:
        获取字体管理器实例::

            fm = FontManager()
            font = fm.get_font(size_px=14, bold=True)
            label.setFont(font)

    Note:
        使用单例模式确保全局只有一个实例，避免重复检测字体。
    """

    _instance: Optional["FontManager"] = None

    # 各平台的字体候选列表
    _FONT_STACKS: dict[str, dict[str, list[str]]] = {
        "Windows": {
            "cjk": [
                "Microsoft YaHei UI",
                "Microsoft YaHei",
                "SimHei",
                "Arial",
            ],
            "emoji": [
                "Segoe UI Emoji",
                "Segoe UI Symbol",
            ],
        },
        "Darwin": {
            "cjk": [
                "PingFang SC",
                "-apple-system",
                "Hiragino Sans GB",
            ],
            "emoji": [
                "Apple Color Emoji",
            ],
        },
        "Linux": {
            "cjk": [
                "Noto Sans CJK SC",
                "WenQuanYi Micro Hei",
                "Droid Sans Fallback",
            ],
            "emoji": [
                "Noto Color Emoji",
                "Symbola",
            ],
        },
    }

    def __new__(cls) -> "FontManager":
        """创建或返回单例实例。

        Returns:
            FontManager 的唯一实例。
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """初始化字体管理器。

        如果已经初始化过则直接返回，确保单例模式的正确性。
        """
        if self._initialized:
            return

        self._system: str = platform.system()
        self._available_fonts: Set[str] = set(QFontDatabase.families())
        self._cjk_family: str = ""
        self._emoji_family: str = ""
        self._dpi_scale: float = 1.0

        self._detect_fonts()
        self._detect_dpi()

        self._initialized = True

        logger.debug(
            "FontManager 初始化完成: system=%s, cjk='%s', emoji='%s', dpi=%.2f",
            self._system,
            self._cjk_family,
            self._emoji_family,
            self._dpi_scale,
        )

    def _detect_fonts(self) -> None:
        """检测系统可用的 CJK 和 Emoji 字体。

        按优先级顺序查找字体，找到第一个可用的即停止。
        如果没有找到合适的字体，则使用系统默认字体。
        """
        stack = self._FONT_STACKS.get(self._system, self._FONT_STACKS["Linux"])

        # 检测 CJK 字体
        for family in stack["cjk"]:
            if family in self._available_fonts:
                self._cjk_family = family
                break
        if not self._cjk_family:
            self._cjk_family = QFont().defaultFamily()
            logger.warning("未找到 CJK 字体，使用系统默认: %s", self._cjk_family)

        # 检测 Emoji 字体
        for family in stack["emoji"]:
            if family in self._available_fonts:
                self._emoji_family = family
                break
        if not self._emoji_family:
            self._emoji_family = self._cjk_family

    def _detect_dpi(self) -> None:
        """检测屏幕 DPI 缩放比例。

        如果无法获取屏幕信息，则默认使用 1.0 的缩放比例。
        """
        try:
            app = QGuiApplication.instance()
            if app:
                screen = QGuiApplication.primaryScreen()
                if screen:
                    self._dpi_scale = screen.devicePixelRatio()
        except Exception as e:
            logger.warning("无法检测 DPI 缩放: %s", e)
            self._dpi_scale = 1.0

    @property
    def dpi_scale(self) -> float:
        """获取 DPI 缩放比例。

        Returns:
            屏幕的 DPI 缩放比例，通常为 1.0、1.25、1.5 或 2.0。
        """
        return self._dpi_scale

    @property
    def cjk_family(self) -> str:
        """获取 CJK 字体族名称。

        Returns:
            检测到的 CJK 字体族名称。
        """
        return self._cjk_family

    @property
    def emoji_family(self) -> str:
        """获取 Emoji 字体族名称。

        Returns:
            检测到的 Emoji 字体族名称。
        """
        return self._emoji_family

    def get_font(self, size_px: int = TYPO.size_md, bold: bool = False) -> QFont:
        """获取配置好的 CJK 字体。

        Args:
            size_px: 字体大小（像素），默认为中等字号。
            bold: 是否使用粗体，默认为 False。

        Returns:
            配置好的 QFont 实例。

        Raises:
            ValueError: 如果 size_px 不是正整数。
        """
        if not isinstance(size_px, int) or size_px <= 0:
            raise ValueError(f"size_px 必须是正整数，收到: {size_px}")

        font = QFont(self._cjk_family)
        font.setPixelSize(size_px)
        if bold:
            font.setWeight(QFont.Weight.DemiBold)
        return font

    def get_emoji_font(self, size_px: int = TYPO.size_emoji) -> QFont:
        """获取 Emoji 字体。

        Args:
            size_px: 字体大小（像素），默认为 Emoji 标准字号。

        Returns:
            配置好的 Emoji 字体 QFont 实例。

        Raises:
            ValueError: 如果 size_px 不是正整数。
        """
        if not isinstance(size_px, int) or size_px <= 0:
            raise ValueError(f"size_px 必须是正整数，收到: {size_px}")

        font = QFont(self._emoji_family)
        font.setPixelSize(size_px)
        return font

    def css_font_family(self) -> str:
        """获取 CSS 格式的字体族声明。

        Returns:
            CSS font-family 格式的字符串。

        Example:
            >>> fm.css_font_family()
            '"Microsoft YaHei UI", "sans-serif"'
        """
        families = [self._cjk_family, "sans-serif"]
        return ", ".join(f'"{f}"' for f in families)

    def css_emoji_family(self) -> str:
        """获取 CSS 格式的 Emoji 字体族声明。

        Returns:
            包含 Emoji 字体的 CSS font-family 格式字符串。
        """
        families = [self._emoji_family, self._cjk_family, "sans-serif"]
        return ", ".join(f'"{f}"' for f in families)

    def scale(self, value: int) -> int:
        """根据 DPI 缩放数值。

        Args:
            value: 要缩放的原始像素值。

        Returns:
            缩放后的像素值，最小为 1。

        Raises:
            ValueError: 如果 value 不是整数。
        """
        if not isinstance(value, int):
            raise ValueError(f"value 必须是整数，收到: {type(value)}")
        return max(1, int(value * self._dpi_scale))


def get_font_manager() -> FontManager:
    """获取全局 FontManager 实例。

    Returns:
        FontManager 的单例实例。

    Example:
        >>> fm = get_font_manager()
        >>> font = fm.get_font(14)
    """
    return FontManager()


# ============================================================
# 样式表构建器
# ============================================================


class StyleBuilder:
    """类型安全的 CSS 样式表构建器。

    提供预定义的样式方法，避免手写 CSS 字符串的错误。
    所有样式方法返回格式化的 CSS 字符串。

    Example:
        >>> builder = StyleBuilder()
        >>> style = builder.primary_button("#2196F3", "#1976D2")
        >>> button.setStyleSheet(style)
    """

    def __init__(self) -> None:
        """初始化样式构建器。"""
        self._fm = get_font_manager()

    def _base_text(self, size: int, color: str, bold: bool = False) -> str:
        """生成基础文字样式。

        Args:
            size: 字体大小（像素）。
            color: 文字颜色（CSS 颜色值）。
            bold: 是否粗体。

        Returns:
            CSS 样式片段。
        """
        weight = TYPO.weight_bold if bold else TYPO.weight_normal
        return f"""
            font-family: {self._fm.css_font_family()};
            font-size: {size}px;
            font-weight: {weight};
            color: {color};
            line-height: {TYPO.line_height};
        """

    def dialog(self) -> str:
        """生成对话框样式。

        Returns:
            对话框的完整 CSS 样式。
        """
        return f"""
            QDialog {{
                background-color: {COLORS.bg_base};
                font-family: {self._fm.css_font_family()};
                font-size: {TYPO.size_md}px;
            }}
        """

    def label(
        self,
        size: int = TYPO.size_md,
        color: str = COLORS.text_primary,
        bold: bool = False,
    ) -> str:
        """生成标签样式。

        Args:
            size: 字体大小（像素）。
            color: 文字颜色。
            bold: 是否粗体。

        Returns:
            QLabel 的 CSS 样式。
        """
        return f"""
            QLabel {{
                {self._base_text(size, color, bold)}
                background: transparent;
                padding: 0px;
            }}
        """

    def emoji_label(self, size: int = TYPO.size_emoji) -> str:
        """生成 Emoji 标签样式。

        Args:
            size: Emoji 字体大小（像素）。

        Returns:
            Emoji 标签的 CSS 样式。
        """
        return f"""
            QLabel {{
                font-family: {self._fm.css_emoji_family()};
                font-size: {size}px;
                background: transparent;
                padding: 0px;
            }}
        """

    def section_frame(self) -> str:
        """生成区块容器样式。

        Returns:
            区块容器的 CSS 样式。
        """
        return f"""
            QFrame#sectionFrame {{
                background-color: {COLORS.bg_surface};
                border: 1px solid {COLORS.border};
                border-radius: {LAYOUT.radius_lg}px;
            }}
        """

    def warning_frame(self) -> str:
        """生成警告容器样式。

        Returns:
            警告容器的 CSS 样式。
        """
        return f"""
            QFrame#warningFrame {{
                background-color: {COLORS.warning_bg};
                border: 1px solid {COLORS.warning};
                border-radius: {LAYOUT.radius_md}px;
            }}
        """

    def checkbox(self) -> str:
        """生成复选框样式。

        Returns:
            QCheckBox 的 CSS 样式。
        """
        indicator_size = self._fm.scale(16)
        return f"""
            QCheckBox {{
                {self._base_text(TYPO.size_sm, COLORS.text_primary)}
                spacing: {SPACING.sm}px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: {indicator_size}px;
                height: {indicator_size}px;
                border: 2px solid {COLORS.text_muted};
                border-radius: {LAYOUT.radius_sm}px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.success};
                border-color: {COLORS.success};
            }}
            QCheckBox::indicator:hover {{
                border-color: {COLORS.success};
            }}
        """

    def primary_button(
        self,
        bg: str,
        hover: str,
        pressed: str = "",
    ) -> str:
        """生成主要按钮样式。

        Args:
            bg: 默认背景色。
            hover: 悬停背景色。
            pressed: 按下背景色，默认与 bg 相同。

        Returns:
            QPushButton 的 CSS 样式。
        """
        pressed = pressed or bg
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {COLORS.text_primary};
                border: none;
                border-radius: {LAYOUT.radius_md}px;
                font-family: {self._fm.css_font_family()};
                font-size: {TYPO.size_lg}px;
                font-weight: {TYPO.weight_bold};
                padding: 0 {SPACING.xl}px;
                min-height: {LAYOUT.button_height_md}px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:pressed {{
                background-color: {pressed};
            }}
            QPushButton:disabled {{
                background-color: {COLORS.bg_hover};
                color: {COLORS.text_disabled};
            }}
        """

    def secondary_button(self) -> str:
        """生成次要按钮样式。

        Returns:
            次要按钮的 CSS 样式。
        """
        return f"""
            QPushButton {{
                background-color: {COLORS.bg_surface};
                color: {COLORS.text_primary};
                border: 1px solid {COLORS.border};
                border-radius: {LAYOUT.radius_md}px;
                font-family: {self._fm.css_font_family()};
                font-size: {TYPO.size_md}px;
                padding: 0 {SPACING.lg}px;
                min-height: {LAYOUT.button_height_sm}px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_hover};
                border-color: {COLORS.border_hover};
            }}
            QPushButton:pressed {{
                background-color: {COLORS.bg_pressed};
            }}
        """


# ============================================================
# 组件工厂
# ============================================================


class ComponentFactory:
    """UI 组件工厂。

    提供预配置的 UI 组件创建方法，确保视觉风格的一致性。
    所有组件都已应用正确的字体、样式和尺寸。

    Example:
        >>> factory = ComponentFactory()
        >>> title = factory.title_label("标题文本")
        >>> button = factory.primary_button("确定", "#2196F3", "#1976D2")
    """

    def __init__(self) -> None:
        """初始化组件工厂。"""
        self._fm = get_font_manager()
        self._styles = StyleBuilder()

    def title_label(
        self,
        text: str,
        size: int = TYPO.size_xxl,
        color: str = COLORS.text_primary,
    ) -> QLabel:
        """创建标题标签。

        Args:
            text: 标签文本。
            size: 字体大小（像素）。
            color: 文字颜色。

        Returns:
            配置好的 QLabel 实例。
        """
        label = QLabel(text)
        label.setFont(self._fm.get_font(size, bold=True))
        label.setStyleSheet(self._styles.label(size, color, bold=True))
        label.setMinimumHeight(int(size * TYPO.line_height))
        return label

    def text_label(
        self,
        text: str,
        size: int = TYPO.size_md,
        color: str = COLORS.text_muted,
        wrap: bool = False,
    ) -> QLabel:
        """创建文本标签。

        Args:
            text: 标签文本。
            size: 字体大小（像素）。
            color: 文字颜色。
            wrap: 是否自动换行。

        Returns:
            配置好的 QLabel 实例。
        """
        label = QLabel(text)
        label.setFont(self._fm.get_font(size))
        label.setStyleSheet(self._styles.label(size, color))
        label.setWordWrap(wrap)
        label.setMinimumHeight(int(size * TYPO.line_height))

        if wrap:
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Minimum,
            )

        return label

    def emoji_label(
        self,
        emoji: str,
        size: int = TYPO.size_emoji,
        min_width: int = 28,
    ) -> QLabel:
        """创建 Emoji 图标标签。

        Args:
            emoji: Emoji 字符。
            size: 字体大小（像素）。
            min_width: 最小宽度（像素）。

        Returns:
            配置好的 Emoji 标签。
        """
        label = QLabel(emoji)
        label.setFont(self._fm.get_emoji_font(size))
        label.setStyleSheet(self._styles.emoji_label(size))
        label.setFixedWidth(self._fm.scale(min_width))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumHeight(int(size * TYPO.line_height))
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def section_frame(self) -> QFrame:
        """创建区块容器。

        Returns:
            配置好的 QFrame 实例。
        """
        frame = QFrame()
        frame.setObjectName("sectionFrame")
        frame.setStyleSheet(self._styles.section_frame())
        return frame

    def warning_frame(self) -> QFrame:
        """创建警告容器。

        Returns:
            配置好的警告样式 QFrame 实例。
        """
        frame = QFrame()
        frame.setObjectName("warningFrame")
        frame.setStyleSheet(self._styles.warning_frame())
        return frame

    def primary_button(
        self,
        text: str,
        bg: str,
        hover: str,
        pressed: str = "",
    ) -> QPushButton:
        """创建主要按钮。

        Args:
            text: 按钮文本。
            bg: 默认背景色。
            hover: 悬停背景色。
            pressed: 按下背景色。

        Returns:
            配置好的 QPushButton 实例。
        """
        btn = QPushButton(text)
        btn.setFont(self._fm.get_font(TYPO.size_lg, bold=True))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(self._styles.primary_button(bg, hover, pressed))
        btn.setMinimumHeight(LAYOUT.button_height_md)
        return btn

    def secondary_button(self, text: str, width: int = 100) -> QPushButton:
        """创建次要按钮。

        Args:
            text: 按钮文本。
            width: 按钮宽度（像素）。

        Returns:
            配置好的 QPushButton 实例。
        """
        btn = QPushButton(text)
        btn.setFont(self._fm.get_font(TYPO.size_md))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(self._styles.secondary_button())
        btn.setFixedWidth(self._fm.scale(width))
        btn.setMinimumHeight(LAYOUT.button_height_sm)
        return btn

    def checkbox(self, text: str, checked: bool = False) -> QCheckBox:
        """创建复选框。

        Args:
            text: 复选框文本。
            checked: 是否默认选中。

        Returns:
            配置好的 QCheckBox 实例。
        """
        cb = QCheckBox(text)
        cb.setFont(self._fm.get_font(TYPO.size_sm))
        cb.setChecked(checked)
        cb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cb.setStyleSheet(self._styles.checkbox())
        return cb


# ============================================================
# 备份恢复对话框
# ============================================================


class BackupRestoreDialog(QDialog):
    """备份恢复对话框。

    提供用户数据备份和恢复的可视化界面，支持：
    - 创建数据备份（已查看记录、收藏、浏览历史、设置）
    - 从备份文件恢复数据
    - 恢复后自动下载收藏图片（可选）

    Signals:
        backup_completed: 备份完成信号，参数为 (success: bool, message: str)。
        restore_completed: 恢复完成信号，参数为 (success: bool, message: str)。

    Attributes:
        auto_download_enabled: 是否启用恢复后自动下载。

    Example:
        创建并显示对话框::

            dialog = BackupRestoreDialog(parent=main_window)
            dialog.backup_completed.connect(on_backup_done)
            dialog.restore_completed.connect(on_restore_done)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                print("对话框已关闭")

    Note:
        恢复操作会覆盖当前数据，但会先自动备份到 backup_temp/ 目录。
    """

    # 信号定义
    backup_completed = pyqtSignal(bool, str)
    restore_completed = pyqtSignal(bool, str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        download_manager: Optional["DownloadManager"] = None,
        on_restore_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        """初始化备份恢复对话框。

        Args:
            parent: 父窗口，用于模态显示和居中定位。
            download_manager: 下载管理器实例，用于恢复后自动下载。
            on_restore_complete: 恢复完成后的回调函数。

        Raises:
            TypeError: 如果参数类型不正确。
        """
        super().__init__(parent)

        # 参数验证
        if download_manager is not None and not hasattr(download_manager, "download"):
            logger.warning("download_manager 可能不是有效的 DownloadManager 实例")

        if on_restore_complete is not None and not callable(on_restore_complete):
            raise TypeError("on_restore_complete 必须是可调用对象")

        self._download_manager = download_manager
        self._on_restore_complete = on_restore_complete
        self._backup_manager: Optional["BackupManager"] = None

        # UI 工具
        self._fm = get_font_manager()
        self._factory = ComponentFactory()
        self._styles = StyleBuilder()

        # 按钮引用（延迟初始化）
        self._backup_btn: Optional[QPushButton] = None
        self._restore_btn: Optional[QPushButton] = None
        self._auto_download_cb: Optional[QCheckBox] = None

        # 初始化
        self._init_backup_manager()
        self._setup_window()
        self._build_ui()
        self._center_on_parent()

        logger.debug("BackupRestoreDialog 初始化完成")

    def _init_backup_manager(self) -> None:
        """初始化备份管理器。

        尝试导入并创建 BackupManager 实例。如果失败，记录错误但不抛出异常，
        允许对话框显示但功能受限。
        """
        try:
            from utils.backup_manager import BackupManager
            from config.app_config import CONFIG

            self._backup_manager = BackupManager(str(CONFIG.base_dir))
            logger.debug("BackupManager 初始化成功")
        except ImportError as e:
            logger.error("无法导入 BackupManager: %s", e)
            self._backup_manager = None
        except Exception as e:
            logger.exception("初始化 BackupManager 失败: %s", e)
            self._backup_manager = None

    def _setup_window(self) -> None:
        """配置窗口属性。"""
        self.setWindowTitle("备份与恢复")
        self.setMinimumSize(
            self._fm.scale(LAYOUT.dialog_width),
            self._fm.scale(LAYOUT.dialog_min_height),
        )
        # 移除帮助按钮
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet(self._styles.dialog())

    def _center_on_parent(self) -> None:
        """将对话框居中显示在父窗口上。"""
        parent = self.parent()
        if parent is not None:
            parent_geo = parent.geometry()
            x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - self.height()) // 2
            self.move(max(0, x), max(0, y))

    def _build_ui(self) -> None:
        """构建用户界面。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING.lg)
        layout.setContentsMargins(
            SPACING.xxl, SPACING.xxl, SPACING.xxl, SPACING.xxl
        )

        # 标题区域
        self._build_header(layout)

        # 备份区块
        self._build_backup_section(layout)

        # 恢复区块
        self._build_restore_section(layout)

        # 警告提示
        self._build_warning(layout)

        # 弹性空间
        layout.addStretch(1)

        # 底部按钮
        self._build_footer(layout)

    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        """构建标题区域。

        Args:
            parent_layout: 父布局。
        """
        # 标题行
        title_row = QHBoxLayout()
        title_row.setSpacing(SPACING.sm)
        title_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = self._factory.emoji_label("📦", size=TYPO.size_xxl)
        title_row.addWidget(icon)

        title = self._factory.title_label("备份与恢复")
        title_row.addWidget(title)

        parent_layout.addLayout(title_row)

        # 副标题
        subtitle = self._factory.text_label(
            "备份数据到文件，方便在其他设备上恢复",
            size=TYPO.size_sm,
            color=COLORS.text_muted,
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        parent_layout.addWidget(subtitle)

        parent_layout.addSpacing(SPACING.sm)

    def _build_backup_section(self, parent_layout: QVBoxLayout) -> None:
        """构建备份功能区块。

        Args:
            parent_layout: 父布局。
        """
        frame = self._factory.section_frame()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(
            SPACING.xl, SPACING.lg, SPACING.xl, SPACING.lg
        )
        frame_layout.setSpacing(SPACING.md)

        # 标题行
        title_row = QHBoxLayout()
        title_row.setSpacing(SPACING.sm)

        icon = self._factory.emoji_label("💾")
        title_row.addWidget(icon)

        title = self._factory.title_label(
            "创建备份",
            size=TYPO.size_lg,
            color=COLORS.info,
        )
        title_row.addWidget(title)
        title_row.addStretch()

        frame_layout.addLayout(title_row)

        # 描述文本
        desc = self._factory.text_label(
            "将已查看记录、收藏、浏览历史和设置保存到一个文件中",
            size=TYPO.size_xs,
            color=COLORS.text_muted,
            wrap=True,
        )
        frame_layout.addWidget(desc)

        # 备份按钮
        self._backup_btn = self._factory.primary_button(
            "创建备份文件",
            COLORS.info,
            COLORS.info_hover,
            COLORS.info_pressed,
        )
        self._backup_btn.clicked.connect(self._do_backup)
        frame_layout.addWidget(self._backup_btn)

        parent_layout.addWidget(frame)

    def _build_restore_section(self, parent_layout: QVBoxLayout) -> None:
        """构建恢复功能区块。

        Args:
            parent_layout: 父布局。
        """
        frame = self._factory.section_frame()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(
            SPACING.xl, SPACING.lg, SPACING.xl, SPACING.lg
        )
        frame_layout.setSpacing(SPACING.md)

        # 标题行
        title_row = QHBoxLayout()
        title_row.setSpacing(SPACING.sm)

        icon = self._factory.emoji_label("📥")
        title_row.addWidget(icon)

        title = self._factory.title_label(
            "恢复备份",
            size=TYPO.size_lg,
            color=COLORS.success,
        )
        title_row.addWidget(title)
        title_row.addStretch()

        frame_layout.addLayout(title_row)

        # 描述文本
        desc = self._factory.text_label(
            "从备份文件恢复数据，可选择自动下载收藏的图片",
            size=TYPO.size_xs,
            color=COLORS.text_muted,
            wrap=True,
        )
        frame_layout.addWidget(desc)

        # 自动下载复选框
        self._auto_download_cb = self._factory.checkbox(
            "恢复后自动下载收藏的图片",
            checked=True,
        )
        frame_layout.addWidget(self._auto_download_cb)

        # 恢复按钮
        self._restore_btn = self._factory.primary_button(
            "选择备份文件并恢复",
            COLORS.success,
            COLORS.success_hover,
            COLORS.success_pressed,
        )
        self._restore_btn.clicked.connect(self._do_restore)
        frame_layout.addWidget(self._restore_btn)

        parent_layout.addWidget(frame)

    def _build_warning(self, parent_layout: QVBoxLayout) -> None:
        """构建警告提示区域。

        Args:
            parent_layout: 父布局。
        """
        frame = self._factory.warning_frame()

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(
            SPACING.lg, SPACING.md, SPACING.lg, SPACING.md
        )
        layout.setSpacing(SPACING.sm)

        icon = self._factory.emoji_label("⚠️")
        layout.addWidget(icon)

        text = self._factory.text_label(
            "恢复操作会覆盖当前数据（当前数据会自动备份到 backup_temp/）",
            size=TYPO.size_xs,
            color=COLORS.warning,
            wrap=True,
        )
        layout.addWidget(text, 1)

        parent_layout.addWidget(frame)

    def _build_footer(self, parent_layout: QVBoxLayout) -> None:
        """构建底部按钮区域。

        Args:
            parent_layout: 父布局。
        """
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        close_btn = self._factory.secondary_button("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        btn_layout.addStretch()

        parent_layout.addLayout(btn_layout)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """设置操作按钮的启用状态。

        Args:
            enabled: 是否启用按钮。
        """
        if self._backup_btn is not None:
            self._backup_btn.setEnabled(enabled)
        if self._restore_btn is not None:
            self._restore_btn.setEnabled(enabled)

    def _show_message(
        self,
        msg_type: str,
        title: str,
        message: str,
    ) -> None:
        """显示消息对话框。

        Args:
            msg_type: 消息类型 ("error", "info", "warning")。
            title: 对话框标题。
            message: 消息内容。
        """
        if msg_type == "error":
            QMessageBox.critical(self, title, message)
        elif msg_type == "info":
            QMessageBox.information(self, title, message)
        elif msg_type == "warning":
            QMessageBox.warning(self, title, message)
        else:
            logger.warning("未知的消息类型: %s", msg_type)
            QMessageBox.information(self, title, message)

    def _do_backup(self) -> None:
        """执行备份操作。

        显示文件选择对话框，创建备份文件，并在完成后通知用户。
        """
        if self._backup_manager is None:
            self._show_message(
                "error",
                "错误",
                "备份管理器未初始化，请检查程序配置",
            )
            return

        # 选择保存路径
        default_name = f"yande_backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择备份保存位置",
            default_name,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )

        if not file_path:
            return  # 用户取消

        # 更新 UI 状态
        self._set_buttons_enabled(False)
        original_text = ""
        if self._backup_btn is not None:
            original_text = self._backup_btn.text()
            self._backup_btn.setText("备份中...")
        QApplication.processEvents()

        def on_complete(success: bool, message: str) -> None:
            """备份完成回调。"""
            self._set_buttons_enabled(True)
            if self._backup_btn is not None:
                self._backup_btn.setText(original_text)

            if success:
                self._show_message("info", "备份成功", message)
                self.backup_completed.emit(True, message)
            else:
                self._show_message("error", "备份失败", message)
                self.backup_completed.emit(False, message)

        try:
            self._backup_manager.create_backup(
                save_path=file_path,
                on_complete=on_complete,
            )
        except Exception as e:
            logger.exception("备份操作失败")
            on_complete(False, f"备份时发生错误: {e}")

    def _do_restore(self) -> None:
        """执行恢复操作。

        显示文件选择对话框，确认后恢复数据，并在完成后通知用户。
        """
        if self._backup_manager is None:
            self._show_message(
                "error",
                "错误",
                "备份管理器未初始化，请检查程序配置",
            )
            return

        # 选择备份文件
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择要恢复的备份文件",
            "",
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )

        if not file_path:
            return  # 用户取消

        # 确认操作
        reply = QMessageBox.question(
            self,
            "确认恢复",
            "恢复操作将覆盖当前数据，是否继续？\n\n"
            "（当前数据会自动备份到 backup_temp/ 文件夹）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 更新 UI 状态
        self._set_buttons_enabled(False)
        original_text = ""
        if self._restore_btn is not None:
            original_text = self._restore_btn.text()
            self._restore_btn.setText("恢复中...")
        QApplication.processEvents()

        def on_complete(success: bool, message: str) -> None:
            """恢复完成回调。"""
            self._set_buttons_enabled(True)
            if self._restore_btn is not None:
                self._restore_btn.setText(original_text)

            if success:
                self._show_message("info", "恢复成功", message)
                self.restore_completed.emit(True, message)

                # 执行恢复完成回调
                if self._on_restore_complete is not None:
                    try:
                        self._on_restore_complete()
                    except Exception as e:
                        logger.error("恢复完成回调执行失败: %s", e)
            else:
                self._show_message("error", "恢复失败", message)
                self.restore_completed.emit(False, message)

        try:
            self._backup_manager.restore_backup(
                backup_path=file_path,
                on_complete=on_complete,
            )
        except Exception as e:
            logger.exception("恢复操作失败")
            on_complete(False, f"恢复时发生错误: {e}")

    def keyPressEvent(self, event) -> None:
        """处理键盘事件。

        Args:
            event: 键盘事件对象。

        Note:
            按下 Escape 键关闭对话框。
        """
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)

    @property
    def auto_download_enabled(self) -> bool:
        """获取是否启用自动下载。

        Returns:
            如果复选框被选中则返回 True，否则返回 False。
        """
        if self._auto_download_cb is not None:
            return self._auto_download_cb.isChecked()
        return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 主要类
    "BackupRestoreDialog",
    "FontManager",
    "ComponentFactory",
    "StyleBuilder",
    # 工具函数
    "get_font_manager",
    # 设计令牌
    "COLORS",
    "SPACING",
    "TYPO",
    "LAYOUT",
    "ColorTokens",
    "SpacingTokens",
    "TypographyTokens",
    "LayoutTokens",
]