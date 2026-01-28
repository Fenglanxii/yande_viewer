"""
加载动画组件模块

本模块提供用于显示加载状态的 UI 组件，包括圆形旋转指示器
和带文字提示的加载面板。基于 PyQt6 实现，使用 Qt 定时器
驱动动画效果。

版权所有 (c) 2026 Yande Viewer Team
遵循 MIT 许可证发布

组件:
    - CircularLoadingIndicator: 圆形旋转加载指示器
    - LoadingWidget: 带文字的完整加载组件

示例:
    >>> from ui.widgets.loading_widget import LoadingWidget
    >>> loading = LoadingWidget(parent=main_window)
    >>> loading.set_text("正在加载图片...")
    >>> loading.show()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from config.design_tokens import TOKENS

if TYPE_CHECKING:
    from PyQt6.QtCore import QTimerEvent
    from PyQt6.QtGui import QCloseEvent, QHideEvent, QPaintEvent, QShowEvent

logger = logging.getLogger(__name__)

# 设计令牌别名
C = TOKENS.colors
T = TOKENS.typography
S = TOKENS.spacing
L = TOKENS.layout


class CircularLoadingIndicator(QWidget):
    """
    圆形旋转加载指示器。
    
    使用 Qt 定时器驱动的动画组件，在显示时自动启动动画，
    隐藏或销毁时自动停止，无需手动管理生命周期。
    
    动画效果为一个圆弧在圆形轨道上旋转。
    
    Attributes:
        _indicator_size: 指示器尺寸（像素）
        _color: 前景色
        _angle: 当前旋转角度
        _timer_id: Qt 定时器 ID
        _pen_width: 画笔宽度
    
    Example:
        >>> # 创建默认样式的加载指示器
        >>> indicator = CircularLoadingIndicator()
        >>> indicator.show()
        
        >>> # 创建自定义样式的加载指示器
        >>> indicator = CircularLoadingIndicator(
        ...     size=64,
        ...     color="#e74c3c"
        ... )
    """
    
    # 动画帧率（毫秒/帧）
    _FRAME_INTERVAL: int = 50  # 20 FPS
    
    # 每帧旋转角度
    _ROTATION_STEP: int = 10
    
    # 弧线角度范围
    _ARC_SPAN: int = 90
    
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        size: int = 40,
        color: Optional[str] = None
    ) -> None:
        """
        初始化加载指示器。
        
        Args:
            parent: 父组件，可选
            size: 指示器尺寸（像素），默认 40
            color: 前景色，默认使用主题强调色
        
        Raises:
            ValueError: 如果 size 小于 10
        """
        super().__init__(parent)
        
        if size < 10:
            raise ValueError("指示器尺寸不能小于 10 像素")
        
        self._indicator_size = size
        self._color = color or C.accent
        self._angle = 0
        self._timer_id: Optional[int] = None
        
        # 根据尺寸计算线宽（最小为 2）
        self._pen_width = max(2, size // 12)
        
        self.setFixedSize(size, size)
    
    @property
    def is_animating(self) -> bool:
        """检查动画是否正在运行。"""
        return self._timer_id is not None
    
    def start_animation(self) -> None:
        """
        启动动画。
        
        如果动画已在运行，则不执行任何操作。
        """
        if self._timer_id is None:
            self._timer_id = self.startTimer(self._FRAME_INTERVAL)
    
    def stop_animation(self) -> None:
        """
        停止动画。
        
        如果动画未在运行，则不执行任何操作。
        """
        if self._timer_id is not None:
            self.killTimer(self._timer_id)
            self._timer_id = None
    
    def timerEvent(self, event: "QTimerEvent") -> None:
        """
        处理定时器事件。
        
        更新旋转角度并触发重绘。
        
        Args:
            event: 定时器事件对象
        """
        self._angle = (self._angle + self._ROTATION_STEP) % 360
        self.update()
    
    def paintEvent(self, event: "QPaintEvent") -> None:
        """
        绘制圆形旋转动画。
        
        绘制两层：
        1. 半透明圆环背景
        2. 旋转的高亮弧线
        
        Args:
            event: 绘制事件对象
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 计算绘制参数
        w = self.width()
        h = self.height()
        size = min(w, h)
        radius = (size - self._pen_width) / 2 - 2  # 留出边距
        
        center_x = w / 2
        center_y = h / 2
        left = center_x - radius
        top = center_y - radius
        
        rect = QRectF(left, top, radius * 2, radius * 2)
        
        # 绘制圆环背景（半透明）
        bg_color = QColor(self._color)
        bg_color.setAlpha(50)
        bg_pen = QPen(bg_color, self._pen_width)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(bg_pen)
        painter.drawEllipse(rect)
        
        # 绘制旋转弧线（Qt 角度单位为 1/16 度）
        start_angle = int(self._angle * 16)
        span_angle = int(self._ARC_SPAN * 16)
        
        fg_pen = QPen(QColor(self._color), self._pen_width)
        fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(fg_pen)
        painter.drawArc(rect, start_angle, span_angle)
    
    def showEvent(self, event: "QShowEvent") -> None:
        """
        显示事件处理。
        
        组件显示时自动启动动画。
        
        Args:
            event: 显示事件对象
        """
        super().showEvent(event)
        self.start_animation()
    
    def hideEvent(self, event: "QHideEvent") -> None:
        """
        隐藏事件处理。
        
        组件隐藏时自动停止动画以节省资源。
        
        Args:
            event: 隐藏事件对象
        """
        self.stop_animation()
        super().hideEvent(event)
    
    def closeEvent(self, event: "QCloseEvent") -> None:
        """
        关闭事件处理。
        
        确保动画资源被正确释放。
        
        Args:
            event: 关闭事件对象
        """
        self.stop_animation()
        super().closeEvent(event)


class LoadingWidget(QWidget):
    """
    带文字提示的加载组件。
    
    包含圆形加载指示器和可自定义的文字说明，
    通常用于覆盖在内容区域上方显示加载状态。
    
    组件具有半透明背景，自动在父组件中居中显示。
    
    Attributes:
        spinner: 圆形加载指示器
        text_label: 文字标签
    
    Example:
        >>> # 基本用法
        >>> loading = LoadingWidget(parent=self)
        >>> loading.show()
        
        >>> # 自定义提示文字
        >>> loading = LoadingWidget(parent=self)
        >>> loading.set_text("正在处理...")
        >>> loading.show()
    """
    
    # 组件默认尺寸
    _DEFAULT_WIDTH: int = 120
    _DEFAULT_HEIGHT: int = 100
    
    # 指示器默认尺寸
    _SPINNER_SIZE: int = 48
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        初始化加载组件。
        
        Args:
            parent: 父组件，可选
        """
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """构建组件 UI。"""
        # 设置透明背景属性
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(S.md)
        
        # 半透明背景样式
        self.setStyleSheet(f"""
            LoadingWidget {{
                background-color: rgba(0, 0, 0, 0.6);
                border-radius: {L.radius_lg}px;
            }}
        """)
        
        # 创建圆形加载指示器
        self.spinner = CircularLoadingIndicator(
            self,
            size=self._SPINNER_SIZE,
            color=C.accent
        )
        layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # 文字标签
        self.text_label = QLabel("正在加载...")
        self.text_label.setStyleSheet(f"""
            QLabel {{
                color: {C.text_primary};
                font-family: {T.font_primary};
                font-size: {T.size_sm}px;
                font-weight: bold;
                background: transparent;
            }}
        """)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.text_label)
        
        # 设置固定尺寸
        self.setFixedSize(self._DEFAULT_WIDTH, self._DEFAULT_HEIGHT)
    
    def set_text(self, text: str) -> None:
        """
        设置提示文字。
        
        Args:
            text: 要显示的文本内容
        """
        self.text_label.setText(text)
    
    def showEvent(self, event: "QShowEvent") -> None:
        """
        显示事件处理。
        
        自动将组件定位到父组件中心。
        
        Args:
            event: 显示事件对象
        """
        super().showEvent(event)
        self._center_in_parent()
    
    def _center_in_parent(self) -> None:
        """在父组件中居中定位。"""
        parent = self.parent()
        if parent is None:
            return
        
        # 获取父组件尺寸
        parent_width = parent.width()
        parent_height = parent.height()
        
        # 计算居中位置
        x = max(0, (parent_width - self.width()) // 2)
        y = max(0, (parent_height - self.height()) // 2)
        
        self.move(x, y)
    
    # =========================================================================
    # 兼容性接口
    # =========================================================================
    
    def show_animation(self) -> None:
        """
        显示加载动画。
        
        此方法为兼容旧版接口保留，建议直接使用 show()。
        """
        self.show()
    
    def hide_animation(self) -> None:
        """
        隐藏加载动画。
        
        此方法为兼容旧版接口保留，建议直接使用 hide()。
        """
        self.hide()