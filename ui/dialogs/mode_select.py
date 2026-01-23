# -*- coding: utf-8 -*-
"""模式选择对话框模块。

应用启动时显示的模式选择界面，允许用户选择浏览模式：
- 最新模式：从最新发布的图片开始浏览
- 续看模式：从上次浏览位置继续

主要特性:
    - 键盘快捷键支持 (1/2/Enter/Escape)
    - 会话信息展示
    - 未完成下载提示
    - 高 DPI 自适应

Example:
    基本用法::

        dialog = ModeSelectDialog(
            parent=main_window,
            has_history=True,
            last_session={"viewed_count": 100, "last_viewed_id": 12345},
            tmp_count=5
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            mode = dialog.get_result()  # "latest" 或 "continue"
            print(f"用户选择了: {mode}")

Keyboard Shortcuts:
    1: 选择最新模式
    2: 选择续看模式（如果可用）
    Enter: 选择最新模式
    Escape: 关闭对话框

License:
    MIT License
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Final, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QKeyEvent
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# 模块级日志器
logger = logging.getLogger("YandeViewer.UI.ModeSelect")


# ============================================================
# 常量定义
# ============================================================

#: 最新模式标识符
MODE_LATEST: Final[str] = "latest"

#: 续看模式标识符
MODE_CONTINUE: Final[str] = "continue"


# ============================================================
# 设计令牌
# ============================================================


class _DesignTokens:
    """内部设计令牌容器。

    提供默认值，如果无法导入外部设计令牌则使用这些默认值。
    """

    class Colors:
        """颜色令牌。"""

        bg_base: str = "#1E1E1E"
        bg_surface: str = "#2D2D30"
        text_primary: str = "#FFFFFF"
        text_muted: str = "#AAAAAA"
        info: str = "#2196F3"
        primary_hover: str = "#1976D2"
        success: str = "#4CAF50"
        success_muted: str = "#388E3C"
        warning: str = "#FF9800"

    class Typography:
        """排版令牌。"""

        font_primary: str = "sans-serif"
        font_icon: str = "sans-serif"

    class Layout:
        """布局令牌。"""

        radius_md: int = 6

    colors = Colors()
    typography = Typography()
    layout = Layout()


def _get_tokens() -> Optional[Any]:
    """安全获取外部设计令牌。

    Returns:
        设计令牌对象，如果导入失败则返回 None。
    """
    try:
        from config.design_tokens import TOKENS

        return TOKENS
    except ImportError:
        logger.debug("外部设计令牌不可用，使用默认值")
        return None


# 全局设计令牌（优先使用外部令牌，否则使用默认值）
_EXTERNAL_TOKENS = _get_tokens()
TOKENS = _EXTERNAL_TOKENS if _EXTERNAL_TOKENS is not None else _DesignTokens()


# ============================================================
# 模式选择对话框
# ============================================================


class ModeSelectDialog(QDialog):
    """模式选择对话框。

    应用启动时显示，允许用户选择浏览模式。

    Attributes:
        result: 用户选择的模式 (MODE_LATEST 或 MODE_CONTINUE)。

    Signals:
        mode_selected: 模式选择信号，参数为模式字符串。

    Example:
        创建并使用对话框::

            dialog = ModeSelectDialog(
                parent=main_window,
                has_history=True,
                last_session={"viewed_count": 50}
            )
            dialog.mode_selected.connect(on_mode_selected)

            if dialog.exec() == QDialog.DialogCode.Accepted:
                mode = dialog.get_result()

    Note:
        如果 has_history 为 False，续看按钮将被禁用。
    """

    # 信号定义
    mode_selected = pyqtSignal(str)

    # 尺寸常量
    DIALOG_WIDTH: Final[int] = 400
    DIALOG_HEIGHT: Final[int] = 350
    BUTTON_WIDTH: Final[int] = 250
    BUTTON_HEIGHT: Final[int] = 60

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        has_history: bool = False,
        last_session: Optional[Dict[str, Any]] = None,
        tmp_count: int = 0,
    ) -> None:
        """初始化模式选择对话框。

        Args:
            parent: 父窗口，用于模态显示和居中定位。
            has_history: 是否有浏览历史，决定续看按钮是否可用。
            last_session: 上次会话信息字典，可包含:
                - viewed_count (int): 已查看图片数量
                - last_viewed_id (int): 上次查看的图片 ID
            tmp_count: 未完成下载的数量，如果大于 0 则显示警告。

        Raises:
            TypeError: 如果参数类型不正确。
        """
        super().__init__(parent)

        # 参数验证和规范化
        if not isinstance(has_history, bool):
            logger.warning(
                "has_history 应为 bool 类型，收到 %s，已自动转换",
                type(has_history).__name__,
            )
            has_history = bool(has_history)

        if not isinstance(tmp_count, int):
            logger.warning(
                "tmp_count 应为 int 类型，收到 %s，已自动转换",
                type(tmp_count).__name__,
            )
            try:
                tmp_count = int(tmp_count)
            except (ValueError, TypeError):
                tmp_count = 0

        if tmp_count < 0:
            logger.warning("tmp_count 不应为负数，已修正为 0")
            tmp_count = 0

        self.result: Optional[str] = None
        self._has_history = has_history
        self._last_session = last_session if last_session is not None else {}
        self._tmp_count = tmp_count

        # 窗口配置
        self._setup_window()

        # 构建 UI
        self._setup_ui()

        # 居中显示
        self._center_on_parent()

        logger.debug(
            "ModeSelectDialog 初始化完成: has_history=%s, tmp_count=%d",
            has_history,
            tmp_count,
        )

    def _setup_window(self) -> None:
        """配置窗口属性。"""
        self.setWindowTitle("选择浏览模式")
        self.setFixedSize(self.DIALOG_WIDTH, self.DIALOG_HEIGHT)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        bg_color = TOKENS.colors.bg_base
        self.setStyleSheet(f"background-color: {bg_color};")

    def _center_on_parent(self) -> None:
        """将对话框居中显示在父窗口上。"""
        parent = self.parent()
        if parent is not None:
            geo = parent.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(max(0, x), max(0, y))

    def _setup_ui(self) -> None:
        """构建用户界面。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题区域
        self._create_header(layout)

        # 未完成下载警告
        if self._tmp_count > 0:
            self._create_warning(layout)

        layout.addSpacing(15)

        # 按钮区域
        self._create_buttons(layout)

        # 首次使用提示
        if not self._has_history:
            self._create_hint(layout)

        layout.addStretch()

    def _create_header(self, layout: QVBoxLayout) -> None:
        """创建标题区域。

        Args:
            layout: 父布局。
        """
        # 主标题
        title = QLabel("🎨 Yande.re Viewer")
        title.setStyleSheet(
            f"""
            QLabel {{
                color: {TOKENS.colors.text_primary};
                font-family: {TOKENS.typography.font_icon};
                font-size: 16px;
                font-weight: bold;
            }}
        """
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 副标题
        subtitle = QLabel("选择浏览模式")
        subtitle.setStyleSheet(
            f"""
            QLabel {{
                color: {TOKENS.colors.text_muted};
                font-family: {TOKENS.typography.font_primary};
                font-size: 11px;
            }}
        """
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

    def _create_warning(self, layout: QVBoxLayout) -> None:
        """创建未完成下载警告。

        Args:
            layout: 父布局。
        """
        warn_label = QLabel(
            f"⚠️ 发现 {self._tmp_count} 个未完成下载，启动后将自动恢复"
        )
        warn_label.setStyleSheet(
            f"""
            QLabel {{
                color: {TOKENS.colors.warning};
                font-family: {TOKENS.typography.font_primary};
                font-size: 9px;
            }}
        """
        )
        warn_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(warn_label)

    def _create_buttons(self, layout: QVBoxLayout) -> None:
        """创建模式选择按钮。

        Args:
            layout: 父布局。
        """
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background-color: transparent;")
        btn_layout = QVBoxLayout(btn_frame)
        btn_layout.setSpacing(10)

        # 最新模式按钮
        btn_latest = self._create_mode_button(
            text="🆕 最新模式\n从最新发布的图片开始",
            mode=MODE_LATEST,
            enabled=True,
            bg_color=TOKENS.colors.info,
            hover_color=TOKENS.colors.primary_hover,
        )
        btn_layout.addWidget(btn_latest, alignment=Qt.AlignmentFlag.AlignCenter)

        # 续看模式按钮
        continue_text = self._get_continue_button_text()
        btn_continue = self._create_mode_button(
            text=continue_text,
            mode=MODE_CONTINUE,
            enabled=self._has_history,
            bg_color=TOKENS.colors.success,
            hover_color=TOKENS.colors.success_muted,
        )
        btn_layout.addWidget(
            btn_continue, alignment=Qt.AlignmentFlag.AlignCenter
        )

        layout.addWidget(btn_frame)

    def _get_continue_button_text(self) -> str:
        """获取续看按钮的文本。

        Returns:
            根据会话信息格式化的按钮文本。
        """
        base_text = "📖 续看模式\n"

        if self._last_session:
            viewed = self._last_session.get("viewed_count", 0)
            last_id = self._last_session.get("last_viewed_id", "?")
            return f"{base_text}已看{viewed}张，上次: ID {last_id}"

        return f"{base_text}从上次位置继续浏览"

    def _create_mode_button(
        self,
        text: str,
        mode: str,
        enabled: bool,
        bg_color: str,
        hover_color: str,
    ) -> QPushButton:
        """创建模式选择按钮。

        Args:
            text: 按钮显示文本。
            mode: 模式标识符 (MODE_LATEST 或 MODE_CONTINUE)。
            enabled: 按钮是否可用。
            bg_color: 默认背景色。
            hover_color: 悬停背景色。

        Returns:
            配置好的 QPushButton 实例。
        """
        btn = QPushButton(text)
        btn.setFixedSize(self.BUTTON_WIDTH, self.BUTTON_HEIGHT)
        btn.setEnabled(enabled)

        if enabled:
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {bg_color};
                    color: {TOKENS.colors.text_primary};
                    font-family: {TOKENS.typography.font_icon};
                    font-size: 11px;
                    border: none;
                    border-radius: {TOKENS.layout.radius_md}px;
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                }}
                QPushButton:pressed {{
                    background-color: {bg_color};
                }}
            """
            )
            btn.clicked.connect(lambda: self._select_mode(mode))
        else:
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {TOKENS.colors.bg_surface};
                    color: {TOKENS.colors.text_muted};
                    font-family: {TOKENS.typography.font_icon};
                    font-size: 11px;
                    border: none;
                    border-radius: {TOKENS.layout.radius_md}px;
                }}
            """
            )

        return btn

    def _create_hint(self, layout: QVBoxLayout) -> None:
        """创建首次使用提示。

        Args:
            layout: 父布局。
        """
        hint = QLabel("（首次使用，无历史记录）")
        hint.setStyleSheet(
            f"""
            QLabel {{
                color: {TOKENS.colors.text_muted};
                font-size: 9px;
            }}
        """
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    def _select_mode(self, mode: str) -> None:
        """处理模式选择。

        Args:
            mode: 选择的模式标识符。

        Note:
            设置 result 属性，发送 mode_selected 信号，然后关闭对话框。
        """
        if mode not in (MODE_LATEST, MODE_CONTINUE):
            logger.warning("无效的模式选择: %s", mode)
            return

        self.result = mode
        self.mode_selected.emit(mode)

        logger.info("用户选择模式: %s", mode)
        self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """处理键盘事件。

        Args:
            event: 键盘事件对象。

        Keyboard Shortcuts:
            1: 选择最新模式
            2: 选择续看模式（如果可用）
            Enter/Return: 选择最新模式
            Escape: 关闭对话框
        """
        key = event.key()

        if key == Qt.Key.Key_1:
            self._select_mode(MODE_LATEST)
        elif key == Qt.Key.Key_2 and self._has_history:
            self._select_mode(MODE_CONTINUE)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._select_mode(MODE_LATEST)
        elif key == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def get_result(self) -> Optional[str]:
        """获取用户选择的模式。

        Returns:
            MODE_LATEST: 用户选择了最新模式。
            MODE_CONTINUE: 用户选择了续看模式。
            None: 用户未做出选择（关闭了对话框）。

        Example:
            >>> dialog = ModeSelectDialog(parent=None)
            >>> if dialog.exec() == QDialog.DialogCode.Accepted:
            ...     mode = dialog.get_result()
            ...     if mode == MODE_LATEST:
            ...         start_from_latest()
        """
        return self.result


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 主要类
    "ModeSelectDialog",
    # 常量
    "MODE_LATEST",
    "MODE_CONTINUE",
]