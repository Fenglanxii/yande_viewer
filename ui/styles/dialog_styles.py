"""对话框样式生成器。
集中管理所有对话框相关的样式表生成，只依赖 TOKENS，不依赖对话框状态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 圆角常量
RADIUS_NONE: int = 0
RADIUS_MICRO: int = 2
RADIUS_SMALL: int = 3


@dataclass
class DialogStyleFactory:
    """集中管理所有样式生成。
    该类只依赖设计令牌，不依赖任何对话框状态。

    Attributes:
        colors: 颜色令牌对象
        typography: 字体令牌对象
        layout: 布局令牌对象
    """

    colors: Any
    typography: Any
    layout: Any

    # ── 文字样式 ──────────────────────────────────────────────────
    def page_title(self) -> str:
        """页面标题样式。"""
        return f"""
        QLabel {{
            color: {self.colors.text_primary};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_lg}px;
            font-weight: 600;
            letter-spacing: 1px;
        }}
        """

    def section_title(self) -> str:
        """分组标题样式。"""
        return f"""
        QLabel {{
            color: {self.colors.text_primary};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_sm}px;
            font-weight: 700;
            letter-spacing: 1px;
        }}
        """

    def section_desc(self) -> str:
        """分组描述样式。"""
        return f"""
        QLabel {{
            color: {self.colors.text_muted};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_xs}px;
        }}
        """

    def param_title(self) -> str:
        """参数标题样式。"""
        return f"""
        QLabel {{
            color: {self.colors.text_primary};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_sm}px;
            font-weight: 500;
        }}
        """

    def hint_text(self) -> str:
        """提示文字样式。"""
        return f"""
        QLabel {{
            color: {self.colors.text_muted};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_xs}px;
        }}
        """

    def sub_text(self) -> str:
        """次要文字样式。"""
        return f"""
        QLabel {{
            color: {self.colors.text_secondary};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_xs}px;
        }}
        """

    # ── 容器样式 ──────────────────────────────────────────────────
    def panel(self) -> str:
        """面板容器样式。"""
        return f"""
        QFrame {{
            background-color: {self.colors.bg_surface};
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-left: 3px solid {self.colors.accent};
            border-radius: {RADIUS_NONE}px;
            padding: 12px 16px 12px 14px;
        }}
        """

    # ── 控件样式 ──────────────────────────────────────────────────
    def value_badge(self) -> str:
        """数值徽章样式。"""
        return f"""
        QLabel {{
            color: {self.colors.accent};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_sm}px;
            font-weight: 600;
            background-color: rgba(233, 30, 99, 0.15);
            border-radius: {RADIUS_MICRO}px;
            padding: 2px 8px;
        }}
        """

    def checkbox_with_check(self) -> str:
        """复选框样式。"""
        return f"""
        QCheckBox {{
            color: {self.colors.text_primary};
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_sm}px;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {self.colors.border_default};
            border-radius: {RADIUS_MICRO}px;
            background-color: transparent;
        }}
        QCheckBox::indicator:hover {{
            border-color: {self.colors.accent};
        }}
        QCheckBox::indicator:checked {{
            background-color: {self.colors.accent};
            border-color: {self.colors.accent};
            image: none;
        }}
        """

    def score_chip(self) -> str:
        """分数选择按钮样式。"""
        return f"""
        QPushButton {{
            background-color: transparent;
            color: {self.colors.text_secondary};
            border: 1px solid {self.colors.border_default};
            border-radius: {RADIUS_MICRO}px;
            padding: 4px 14px;
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_xs}px;
            font-weight: 500;
            min-width: 42px;
            min-height: 26px;
        }}
        QPushButton:checked {{
            background-color: {self.colors.accent};
            color: #FFFFFF;
            border-color: {self.colors.accent};
            font-weight: 600;
        }}
        QPushButton:hover:!checked {{
            border-color: {self.colors.accent};
            background-color: rgba(232, 67, 147, 0.08);
        }}
        """

    def rating_chip(self, bg_color: str, text_color: str) -> str:
        """评级选择按钮样式。

        Parameters:
            bg_color: 选中时的背景色
            text_color: 选中时的文字色
        """
        return f"""
        QPushButton {{
            background-color: transparent;
            color: {self.colors.text_secondary};
            border: 1px solid {self.colors.border_default};
            border-radius: {RADIUS_MICRO}px;
            padding: 6px 14px;
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_xs}px;
            min-height: 28px;
        }}
        QPushButton:checked {{
            background-color: {bg_color};
            color: {text_color};
            border-color: {text_color};
        }}
        QPushButton:hover:!checked {{
            border-color: {text_color};
        }}
        """

    def slider(self) -> str:
        """滑动条样式。"""
        return f"""
        QSlider {{
            min-height: 22px;
        }}
        QSlider::groove:horizontal {{
            background: {self.colors.slider_track};
            height: 3px;
            border-radius: {RADIUS_NONE}px;
        }}
        QSlider::sub-page:horizontal {{
            background: {self.colors.accent};
            border-radius: {RADIUS_NONE}px;
        }}
        QSlider::handle:horizontal {{
            background: {self.colors.accent};
            width: 12px;
            height: 12px;
            margin: -5px 0;
            border-radius: {RADIUS_MICRO}px;
            border: 1px solid rgba(255, 255, 255, 0.15);
        }}
        QSlider::handle:horizontal:hover {{
            background: {self.colors.accent_hover};
        }}
        """

    def line_edit(self) -> str:
        """单行输入框样式。"""
        return f"""
        QLineEdit {{
            background-color: #2A2A2A;
            color: {self.colors.text_primary};
            border: 1px solid {self.colors.border_default};
            border-radius: {RADIUS_MICRO}px;
            padding: 4px 8px;
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_sm}px;
        }}
        QLineEdit:focus {{
            border-color: {self.colors.accent};
            background-color: #333333;
        }}
        QLineEdit:disabled {{
            background-color: #252525;
            color: {self.colors.text_muted};
            border-color: transparent;
        }}
        """

    def spinbox(self) -> str:
        """数值输入框样式。"""
        return f"""
        QSpinBox {{
            background-color: #2A2A2A;
            color: {self.colors.text_primary};
            border: 1px solid {self.colors.border_default};
            border-radius: {RADIUS_MICRO}px;
            padding: 2px 4px;
            min-height: 20px;
            font-family: {self.typography.font_primary};
            font-size: {self.typography.size_xs}px;
        }}
        QSpinBox:focus {{
            border-color: {self.colors.accent};
        }}
        QSpinBox:disabled {{
            background-color: #252525;
            color: {self.colors.text_muted};
            border-color: transparent;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            width: 14px;
            background-color: transparent;
            border: none;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: rgba(255, 255, 255, 0.1);
        }}
        """

    # ── 按钮样式 ──────────────────────────────────────────────────
    def button(self, variant: str = "default") -> str:
        """按钮样式。

        Parameters:
            variant: 按钮变体，可选值: 'primary', 'secondary', 'ghost'
        """
        r = RADIUS_MICRO
        if variant == "primary":
            return f"""
            QPushButton {{
                background-color: {self.colors.accent};
                color: #FFFFFF;
                border: none;
                border-radius: {r}px;
                padding: 6px 24px;
                font-family: {self.typography.font_primary};
                font-weight: 600;
                font-size: {self.typography.size_sm}px;
                min-height: 32px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: {self.colors.accent_hover};
                border: 1px solid rgba(255, 255, 255, 0.15);
            }}
            """
        if variant == "secondary":
            return f"""
            QPushButton {{
                background-color: {self.colors.bg_surface};
                color: {self.colors.text_primary};
                border: 1px solid {self.colors.border_default};
                border-radius: {r}px;
                padding: 6px 16px;
                font-family: {self.typography.font_primary};
                font-weight: 500;
                font-size: {self.typography.size_sm}px;
                min-height: 28px;
            }}
            QPushButton:hover {{
                background-color: {self.colors.bg_hover};
                border-color: {self.colors.text_muted};
            }}
            """
        # ghost
        return f"""
        QPushButton {{
            background-color: transparent;
            color: {self.colors.text_muted};
            border: 1px solid {self.colors.border_subtle};
            border-radius: {r}px;
            padding: 6px 14px;
            font-family: {self.typography.font_primary};
            font-weight: 400;
            font-size: {self.typography.size_xs}px;
            min-height: 28px;
        }}
        QPushButton:hover {{
            color: {self.colors.text_secondary};
            border-color: {self.colors.border_default};
            background-color: rgba(255, 255, 255, 0.03);
        }}
        """

    # ── 滚动条样式 ───────────────────────────────────────────────
    def scrollbar(self) -> str:
        """滚动条样式。"""
        return f"""
        QScrollBar:vertical {{
            background: transparent;
            width: 7px;
            margin: 2px 1px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(255, 255, 255, 0.12);
            border-radius: {RADIUS_MICRO}px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(255, 255, 255, 0.22);
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
        """