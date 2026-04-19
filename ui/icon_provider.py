"""程序化矢量图标提供器。

本模块使用 QPainter 程序化绘制所有图标，不依赖外部资源文件。
支持 HiDPI、颜色自定义和内置缓存。

Example:
    icon = IconProvider.get("folder", color="#FFFFFF", size=24)
    button.setIcon(icon)
"""

from __future__ import annotations

import math
import threading
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

# 设计令牌快捷引用
from config.design_tokens import TOKENS

C = TOKENS.colors


class IconProvider:
    """程序化矢量图标提供器。

    使用 QPainter 绘制线条/形状图标，支持：
    - HiDPI 适配（2x 分辨率绘制）
    - 自定义颜色（与主题色体系统一）
    - 内置缓存（同参数不重复绘制）
    - 线条圆角风格（类似 Lucide/Feather Icons）

    所有图标使用线条绘制，笔画圆角（RoundCap、RoundJoin），
    线宽约为尺寸的 8%，风格简洁圆润。

    Attributes:
        _cache: 图标缓存字典，键为 (name, color, size) 元组。

    Example:
        # 获取文件夹图标
        icon = IconProvider.get("folder")

        # 指定颜色和大小
        icon = IconProvider.get("refresh", color=C.accent, size=32)
    """

    # 支持的图标名称列表
    ICONS = (
        "folder",
        "search",
        "refresh",
        "eye",
        "trash",
        "locate",
        "zoom-in",
        "zoom-out",
        "fit",
        "arrow-left",
        "arrow-right",
        "loading",
    )

    # 实例缓存
    _instance: Optional["IconProvider"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "IconProvider":
        """单例模式，确保全局只有一个实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache: Dict[Tuple[str, str, int], QIcon] = {}
                    cls._instance._cache_lock = threading.Lock()
        return cls._instance

    @classmethod
    def get(
        cls,
        name: str,
        color: Optional[str] = None,
        size: int = 20,
    ) -> QIcon:
        """获取图标。

        Args:
            name: 图标名称，支持: folder, search, refresh, eye, trash,
                  locate, zoom-in, zoom-out, fit, arrow-left, arrow-right, loading
            color: 颜色值（十六进制），默认为 text_secondary
            size: 图标尺寸（逻辑像素），默认 20

        Returns:
            QIcon 对象

        Raises:
            ValueError: 不支持的图标名称
        """
        if name not in cls.ICONS:
            raise ValueError(f"不支持的图标: {name}，支持的图标: {', '.join(cls.ICONS)}")

        # 默认颜色
        if color is None:
            color = C.text_secondary

        instance = cls()
        cache_key = (name, color, size)

        # 检查缓存
        with instance._cache_lock:
            if cache_key in instance._cache:
                return instance._cache[cache_key]

        # 绘制图标
        icon = instance._draw_icon(name, color, size)

        # 存入缓存
        with instance._cache_lock:
            instance._cache[cache_key] = icon

        return icon

    @classmethod
    def clear_cache(cls) -> None:
        """清空图标缓存。"""
        instance = cls()
        with instance._cache_lock:
            instance._cache.clear()

    def _draw_icon(self, name: str, color: str, size: int) -> QIcon:
        """绘制指定图标。

        Args:
            name: 图标名称
            color: 颜色值
            size: 逻辑尺寸

        Returns:
            QIcon 对象
        """
        # 获取设备像素比
        dpr = self._get_device_pixel_ratio()
        actual_size = int(size * dpr)

        # 创建 2x 分辨率 pixmap
        pixmap = QPixmap(actual_size, actual_size)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.Transparent)

        # 绘制
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 计算线宽（约为尺寸的 8%）
        line_width = max(1.5, size * 0.08)

        # 设置画笔
        qcolor = QColor(color)
        pen = QPen(qcolor, line_width, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        # 缩放和平移到逻辑坐标系
        painter.scale(dpr, dpr)

        # 绘制图标
        draw_method = getattr(self, f"_draw_{name.replace('-', '_')}", None)
        if draw_method:
            draw_method(painter, size, line_width)

        painter.end()
        return QIcon(pixmap)

    def _get_device_pixel_ratio(self) -> float:
        """获取设备像素比。

        Returns:
            设备像素比，默认 1.0
        """
        try:
            app = QApplication.instance()
            if app is not None:
                screen = app.primaryScreen()
                if screen is not None:
                    return screen.devicePixelRatio()
        except Exception:
            pass
        return 1.0

    # =========================================================================
    # 图标绘制方法
    # =========================================================================

    def _draw_folder(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制文件夹图标。

        ┌───┐
        │ ├─┐
        └───┴─┘
        """
        s = size
        p = line_width / 2  # padding
        r = s * 0.12  # corner radius

        # 外框路径
        path = QPainterPath()

        # 上折页（小三角）
        top_h = s * 0.15
        path.moveTo(p, p + top_h)
        path.lineTo(p, p + top_h)
        path.lineTo(s * 0.25, p + top_h)
        path.lineTo(s * 0.35, p)
        path.lineTo(s * 0.55, p)
        path.lineTo(s * 0.65, p + top_h)

        # 右侧和底部
        path.lineTo(s - p - r, p + top_h)
        path.arcTo(s - p - r, p + top_h, r * 2, r * 2, 90, -90)
        path.lineTo(s - p, s - p - r)
        path.arcTo(s - p - r, s - p - r, r * 2, r * 2, 0, -90)
        path.lineTo(p + r, s - p)
        path.arcTo(p, s - p - r, r * 2, r * 2, 270, -90)
        path.lineTo(p, p + top_h + r)
        path.arcTo(p, p + top_h, r * 2, r * 2, 180, -90)

        painter.drawPath(path)

    def _draw_search(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制搜索图标。

          ○
         ╱
        ‾
        """
        s = size
        p = line_width

        # 圆圈
        circle_r = s * 0.35
        circle_cx = s * 0.4
        circle_cy = s * 0.4

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            QPointF(circle_cx, circle_cy), circle_r, circle_r
        )

        # 把手（右下斜线）
        handle_start_x = circle_cx + circle_r * 0.7
        handle_start_y = circle_cy + circle_r * 0.7
        handle_end_x = s - p
        handle_end_y = s - p

        painter.drawLine(
            QPointF(handle_start_x, handle_start_y),
            QPointF(handle_end_x, handle_end_y),
        )

    def _draw_refresh(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制刷新图标（圆形箭头）。↻"""
        s = size
        cx = s / 2
        cy = s / 2
        r = s * 0.35

        # 圆弧（3/4 圆）
        arc_r = r
        rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, 90 * 16, -270 * 16)

        # 箭头（在起点位置，指向上方）
        arrow_len = s * 0.15
        arrow_x = cx
        arrow_y = cy - r

        # 箭头两翼
        painter.drawLine(
            QPointF(arrow_x, arrow_y),
            QPointF(arrow_x - arrow_len, arrow_y + arrow_len * 0.8),
        )
        painter.drawLine(
            QPointF(arrow_x, arrow_y),
            QPointF(arrow_x + arrow_len, arrow_y + arrow_len * 0.8),
        )

    def _draw_eye(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制预览图标（眼睛）。

        ──●──
         ╱   ╲
        """
        s = size
        cx = s / 2
        cy = s / 2
        p = line_width / 2

        # 眼睛轮廓（扁椭圆）
        eye_w = s * 0.8
        eye_h = s * 0.4

        path = QPainterPath()
        path.moveTo(p, cy)
        path.cubicTo(
            QPointF(s * 0.25, cy - eye_h / 2),
            QPointF(s * 0.75, cy - eye_h / 2),
            QPointF(s - p, cy),
        )
        path.cubicTo(
            QPointF(s * 0.75, cy + eye_h / 2),
            QPointF(s * 0.25, cy + eye_h / 2),
            QPointF(p, cy),
        )
        painter.drawPath(path)

        # 瞳孔（小圆）
        pupil_r = s * 0.12
        painter.setBrush(QColor(painter.pen().color()))
        painter.drawEllipse(QPointF(cx, cy), pupil_r, pupil_r)

    def _draw_trash(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制删除图标（垃圾桶）。

        ─────
        ┌─────┐
        │  │  │
        └─┴─┴─┘
        """
        s = size
        p = line_width / 2
        r = s * 0.06

        # 垃圾桶主体
        body_w = s * 0.7
        body_h = s * 0.5
        body_x = (s - body_w) / 2
        body_y = s * 0.35

        # 盖子
        lid_h = s * 0.12
        lid_y = s * 0.22

        # 盖子横线
        painter.drawLine(QPointF(p, lid_y), QPointF(s - p, lid_y))

        # 盖子把手
        handle_w = s * 0.3
        handle_x = (s - handle_w) / 2
        painter.drawLine(
            QPointF(handle_x, lid_y - p),
            QPointF(handle_x + handle_w, lid_y - p)
        )

        # 主体圆角矩形
        path = QPainterPath()
        path.moveTo(body_x + r, body_y)
        path.lineTo(body_x + body_w - r, body_y)
        path.arcTo(body_x + body_w - r * 2, body_y, r * 2, r * 2, 90, -90)
        path.lineTo(body_x + body_w, body_y + body_h - r)
        path.arcTo(body_x, body_y + body_h - r * 2, r * 2, r * 2, 270, -90)
        path.lineTo(body_x + r, body_y + body_h)
        path.arcTo(body_x, body_y + body_h - r * 2, r * 2, r * 2, 180, -90)
        path.lineTo(body_x, body_y + r)
        path.arcTo(body_x, body_y, r * 2, r * 2, 180, -90)
        painter.drawPath(path)

        # 垃圾桶内的三条竖线
        line_gap = body_w / 4
        for i in range(3):
            lx = body_x + line_gap * (i + 1)
            painter.drawLine(
                QPointF(lx, body_y + p * 2),
                QPointF(lx, body_y + body_h - p * 2),
            )

    def _draw_locate(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制打开位置图标（文件夹+箭头）。

        ┌───┐
        │  ├→
        └───┘
        """
        s = size
        p = line_width / 2
        r = s * 0.1

        # 文件夹（简化版）
        folder_w = s * 0.65
        folder_h = s * 0.55
        folder_x = p
        folder_y = s * 0.25

        # 文件夹轮廓
        path = QPainterPath()
        path.moveTo(folder_x + r, folder_y)
        path.lineTo(folder_x + folder_w - r, folder_y)
        path.arcTo(
            folder_x + folder_w - r * 2, folder_y, r * 2, r * 2, 90, -90
        )
        path.lineTo(folder_x + folder_w, folder_y + folder_h - r)
        path.arcTo(
            folder_x + folder_w - r * 2, folder_y + folder_h - r * 2, r * 2, r * 2, 0, -90,
        )
        path.lineTo(folder_x + r, folder_y + folder_h)
        path.arcTo(folder_x, folder_y + folder_h - r * 2, r * 2, r * 2, 270, -90)
        path.lineTo(folder_x, folder_y + r)
        path.arcTo(folder_x, folder_y, r * 2, r * 2, 180, -90)
        painter.drawPath(path)

        # 箭头（从文件夹内部指向外部）
        arrow_start_x = folder_x + folder_w * 0.4
        arrow_start_y = folder_y + folder_h / 2
        arrow_end_x = s - p
        arrow_end_y = arrow_start_y

        # 箭头线
        painter.drawLine(
            QPointF(arrow_start_x, arrow_start_y),
            QPointF(arrow_end_x, arrow_end_y)
        )

        # 箭头头部
        arrow_head_len = s * 0.15
        painter.drawLine(
            QPointF(arrow_end_x - arrow_head_len, arrow_end_y - arrow_head_len * 0.6),
            QPointF(arrow_end_x, arrow_end_y),
        )
        painter.drawLine(
            QPointF(arrow_end_x - arrow_head_len, arrow_end_y + arrow_head_len * 0.6),
            QPointF(arrow_end_x, arrow_end_y),
        )

    def _draw_zoom_in(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制放大图标。

        ⊕
         ╱
        ‾
        """
        s = size
        cx = s * 0.38
        cy = s * 0.38
        r = s * 0.28
        p = line_width / 2

        # 圆圈
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # 加号
        plus_len = r * 0.6
        painter.drawLine(QPointF(cx - plus_len, cy), QPointF(cx + plus_len, cy))
        painter.drawLine(QPointF(cx, cy - plus_len), QPointF(cx, cy + plus_len))

        # 把手
        handle_start_x = cx + r * 0.7
        handle_start_y = cy + r * 0.7
        handle_end_x = s - p
        handle_end_y = s - p

        painter.drawLine(
            QPointF(handle_start_x, handle_start_y),
            QPointF(handle_end_x, handle_end_y),
        )

    def _draw_zoom_out(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制缩小图标。

        ⊖
         ╱
        ‾
        """
        s = size
        cx = s * 0.38
        cy = s * 0.38
        r = s * 0.28
        p = line_width / 2

        # 圆圈
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # 减号
        minus_len = r * 0.6
        painter.drawLine(QPointF(cx - minus_len, cy), QPointF(cx + minus_len, cy))

        # 把手
        handle_start_x = cx + r * 0.7
        handle_start_y = cy + r * 0.7
        handle_end_x = s - p
        handle_end_y = s - p

        painter.drawLine(
            QPointF(handle_start_x, handle_start_y),
            QPointF(handle_end_x, handle_end_y),
        )

    def _draw_fit(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制适合窗口图标（四角箭头）。

        ↖  ↗
        ↙  ↘
        """
        s = size
        m = s / 2  # 中心点
        p = line_width / 2
        arrow_len = s * 0.25

        # 四个角的箭头
        corners = [
            (p, p, 45),        # 左上
            (s - p, p, 135),   # 右上
            (p, s - p, -45),   # 左下
            (s - p, s - p, -135),  # 右下
        ]

        for cx, cy, angle in corners:
            # 箭头线
            rad = math.radians(angle)
            dx = math.cos(rad) * arrow_len
            dy = -math.sin(rad) * arrow_len

            painter.drawLine(
                QPointF(cx, cy),
                QPointF(cx + dx, cy + dy),
            )

            # 箭头翼
            wing_len = s * 0.1
            wing_rad = math.radians(angle + 90)
            wing_dx = math.cos(wing_rad) * wing_len
            wing_dy = -math.sin(wing_rad) * wing_len

            painter.drawLine(
                QPointF(cx + dx, cy + dy),
                QPointF(cx + dx + wing_dx, cy + dy + wing_dy),
            )

    def _draw_arrow_left(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制左箭头图标。←"""
        s = size
        cy = s / 2
        p = line_width / 2
        arrow_len = s * 0.25

        # 箭头线
        start_x = s - p
        end_x = p

        painter.drawLine(QPointF(start_x, cy), QPointF(end_x, cy))

        # 箭头头部
        painter.drawLine(
            QPointF(end_x + arrow_len, cy - arrow_len * 0.6),
            QPointF(end_x, cy),
        )
        painter.drawLine(
            QPointF(end_x + arrow_len, cy + arrow_len * 0.6),
            QPointF(end_x, cy),
        )

    def _draw_arrow_right(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制右箭头图标。→"""
        s = size
        cy = s / 2
        p = line_width / 2
        arrow_len = s * 0.25

        # 箭头线
        start_x = p
        end_x = s - p

        painter.drawLine(QPointF(start_x, cy), QPointF(end_x, cy))

        # 箭头头部
        painter.drawLine(
            QPointF(end_x - arrow_len, cy - arrow_len * 0.6),
            QPointF(end_x, cy),
        )
        painter.drawLine(
            QPointF(end_x - arrow_len, cy + arrow_len * 0.6),
            QPointF(end_x, cy),
        )

    def _draw_loading(self, painter: QPainter, size: int, line_width: float) -> None:
        """绘制加载占位图标（圆弧）。⏳ 简化为一个不完整的圆"""
        s = size
        cx = s / 2
        cy = s / 2
        r = s * 0.35

        # 3/4 圆弧（开口在右上）
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, 30 * 16, 300 * 16)

        # 小圆点（在开口处）
        dot_angle = math.radians(60)
        dot_x = cx + math.cos(dot_angle) * r
        dot_y = cy - math.sin(dot_angle) * r
        dot_r = line_width * 0.8

        painter.setBrush(QColor(painter.pen().color()))
        painter.drawEllipse(QPointF(dot_x, dot_y), dot_r, dot_r)