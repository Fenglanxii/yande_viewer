"""矩形风格 Switch 开关控件。

提供完全独立的通用控件，可用于各种需要开关状态切换的场景。
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import (
    Qt,
    QPropertyAnimation,
    QEasingCurve,
    QRect,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush

if TYPE_CHECKING:
    pass  # 无外部类型依赖

logger = logging.getLogger("YandeViewer.UI.SwitchWidget")


def _get_accent_color() -> str:
    """安全获取主题强调色。"""
    try:
        from config.design_tokens import TOKENS
        return TOKENS.colors.accent
    except ImportError:
        return "#E84393"


# 模块级常量（只读）
_ACCENT_COLOR: str = _get_accent_color()


class SwitchWidget(QWidget):
    """矩形风格 Switch 开关控件。

    这是一个完全独立的通用控件，提供平滑的动画过渡效果。

    Signals:
        toggled: 状态改变时发射，携带新的布尔状态值。

    Attributes:
        SWITCH_WIDTH: 开关宽度（像素）
        SWITCH_HEIGHT: 开关高度（像素）
        THUMB_WIDTH: 滑块宽度（像素）
        THUMB_HEIGHT: 滑块高度（像素）
    """

    toggled = pyqtSignal(bool)

    SWITCH_WIDTH: int = 38
    SWITCH_HEIGHT: int = 20
    THUMB_WIDTH: int = 16
    THUMB_HEIGHT: int = 14
    TRACK_RADIUS: int = 2
    THUMB_RADIUS: int = 1
    MARGIN: int = 3

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        checked: bool = False
    ) -> None:
        super().__init__(parent)
        self._checked: bool = checked
        self._thumb_position: float = 1.0 if checked else 0.0
        self._animation: Optional[QPropertyAnimation] = None

        self.setFixedSize(self.SWITCH_WIDTH, self.SWITCH_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    # ── 公开接口 ──────────────────────────────────────────────

    def isChecked(self) -> bool:
        """返回当前开关状态。"""
        return self._checked

    def setChecked(self, checked: bool) -> None:
        """设置开关状态，触发动画和信号。"""
        if self._checked != checked:
            self._checked = checked
            self._animate_thumb()
            self.toggled.emit(checked)
            self.update()

    def toggle(self) -> None:
        """切换开关状态。"""
        self.setChecked(not self._checked)

    def stop_animation(self) -> None:
        """停止正在进行的动画。

        在控件销毁前调用，防止动画回调访问已销毁的对象。
        """
        if self._animation is not None:
            self._animation.stop()
            self._animation = None

    # ── 动画属性 ──────────────────────────────────────────────

    def _get_thumb_pos(self) -> float:
        return self._thumb_position

    def _set_thumb_pos(self, value: float) -> None:
        self._thumb_position = value
        self.update()

    thumb_position = pyqtProperty(float, fget=_get_thumb_pos, fset=_set_thumb_pos)

    def _animate_thumb(self) -> None:
        """启动滑块位置动画。"""
        target = 1.0 if self._checked else 0.0
        if self._animation is not None:
            self._animation.stop()
        self._animation = QPropertyAnimation(self, b"thumb_position", self)
        self._animation.setDuration(140)
        self._animation.setStartValue(self._thumb_position)
        self._animation.setEndValue(target)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()

    # ── 绘制 ──────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_track(painter)
            self._paint_thumb(painter)
        except Exception:
            logger.debug("Switch 绘制异常", exc_info=True)
        finally:
            painter.end()

    def _paint_track(self, painter: QPainter) -> None:
        """绘制轨道背景。"""
        accent = QColor(_ACCENT_COLOR)
        off_color = QColor("#2A2A30")

        # 插值轨道颜色
        ratio = self._thumb_position
        r = int(off_color.red() + ratio * (accent.red() - off_color.red()))
        g = int(off_color.green() + ratio * (accent.green() - off_color.green()))
        b = int(off_color.blue() + ratio * (accent.blue() - off_color.blue()))
        track_color = QColor(r, g, b)

        border_color = accent if self._checked else QColor("#3A3A42")
        rect = QRect(0, 0, self.SWITCH_WIDTH, self.SWITCH_HEIGHT)

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(rect, self.TRACK_RADIUS, self.TRACK_RADIUS)

    def _paint_thumb(self, painter: QPainter) -> None:
        """绘制滑块（拇指）。"""
        travel = self.SWITCH_WIDTH - self.THUMB_WIDTH - self.MARGIN * 2
        thumb_x = self.MARGIN + self._thumb_position * travel
        thumb_y = (self.SWITCH_HEIGHT - self.THUMB_HEIGHT) // 2

        # 阴影
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 40)))
        painter.drawRoundedRect(
            int(thumb_x) + 1,
            int(thumb_y) + 1,
            self.THUMB_WIDTH,
            self.THUMB_HEIGHT,
            self.THUMB_RADIUS,
            self.THUMB_RADIUS,
        )

        # 拇指
        thumb_color = QColor("#FFFFFF") if self._checked else QColor("#909090")
        painter.setBrush(QBrush(thumb_color))
        painter.drawRoundedRect(
            int(thumb_x),
            int(thumb_y),
            self.THUMB_WIDTH,
            self.THUMB_HEIGHT,
            self.THUMB_RADIUS,
            self.THUMB_RADIUS,
        )

    # ── 事件 ──────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self._checked)
        else:
            super().keyPressEvent(event)