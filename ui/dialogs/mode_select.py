# -*- coding: utf-8 -*-
"""浏览模式选择对话框模块。

本模块提供应用启动时的模式选择界面，允许用户选择浏览方式：
- 最新模式：从最新发布的图片开始浏览
- 续看模式：从上次浏览位置继续

主要特性：
    - 键盘快捷键支持（1/2/Enter/Escape）
    - 会话信息展示
    - 未完成下载提醒
    - 高 DPI 和字体缩放自适应布局
    - 多屏幕感知居中
    - 国际化支持（i18n）

使用示例::

    dialog = ModeSelectDialog(
        parent=main_window,
        has_history=True,
        last_session={"viewed_count": 100, "last_viewed_id": 12345},
        tmp_count=5
    )

    if dialog.exec() == QDialog.DialogCode.Accepted:
        mode = dialog.get_result()  # "latest" 或 "continue"
        print(f"用户选择了: {mode}")

键盘快捷键：
    1: 选择最新模式
    2: 选择续看模式（如可用）
    Enter: 激活焦点按钮
    Escape: 关闭对话框

许可证：
    MIT License

版权所有 (c) 2026 YandeViewer 贡献者
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final, Optional, Protocol

from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QKeyEvent, QMouseEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# 模块级日志记录器
logger = logging.getLogger("YandeViewer.UI.ModeSelect")


# ============================================================================
# 常量定义
# ============================================================================

#: 最新模式标识符 - 从最新发布的图片开始
MODE_LATEST: Final[str] = "latest"

#: 续看模式标识符 - 从上次浏览位置继续
MODE_CONTINUE: Final[str] = "continue"


# ============================================================================
# 设计令牌协议与默认值
# ============================================================================


class ColorTokensProtocol(Protocol):
    """颜色令牌协议，定义必需的颜色属性。"""

    bg_base: str
    bg_surface: str
    text_primary: str
    text_muted: str
    info: str
    primary_hover: str
    success: str
    success_muted: str
    warning: str


class TypographyTokensProtocol(Protocol):
    """排版令牌协议，定义必需的字体属性。"""

    font_primary: str
    font_icon: str


class LayoutTokensProtocol(Protocol):
    """布局令牌协议，定义必需的布局属性。"""

    radius_md: int


class DesignTokensProtocol(Protocol):
    """设计令牌完整协议。"""

    colors: ColorTokensProtocol
    typography: TypographyTokensProtocol
    layout: LayoutTokensProtocol


@dataclass(frozen=True)
class DefaultColorTokens:
    """默认颜色令牌，作为备用值使用。"""

    bg_base: str = "#1E1E1E"
    bg_surface: str = "#2D2D30"
    text_primary: str = "#FFFFFF"
    text_muted: str = "#AAAAAA"
    info: str = "#2196F3"
    primary_hover: str = "#1976D2"
    success: str = "#4CAF50"
    success_muted: str = "#388E3C"
    warning: str = "#FF9800"


@dataclass(frozen=True)
class DefaultTypographyTokens:
    """默认排版令牌，作为备用值使用。"""

    font_primary: str = "sans-serif"
    font_icon: str = "sans-serif"


@dataclass(frozen=True)
class DefaultLayoutTokens:
    """默认布局令牌，作为备用值使用。"""

    radius_md: int = 6


@dataclass(frozen=True)
class DefaultDesignTokens:
    """完整的默认设计令牌容器。"""

    colors: DefaultColorTokens = field(default_factory=DefaultColorTokens)
    typography: DefaultTypographyTokens = field(
        default_factory=DefaultTypographyTokens
    )
    layout: DefaultLayoutTokens = field(default_factory=DefaultLayoutTokens)


def _validate_tokens(tokens: Any) -> bool:
    """验证令牌对象是否具有所有必需的属性。"""
    required_colors = [
        "bg_base",
        "bg_surface",
        "text_primary",
        "text_muted",
        "info",
        "primary_hover",
        "success",
        "success_muted",
        "warning",
    ]
    required_typography = ["font_primary", "font_icon"]
    required_layout = ["radius_md"]

    try:
        if not hasattr(tokens, "colors"):
            logger.debug("令牌验证失败：缺少 'colors' 属性")
            return False

        for attr in required_colors:
            if not hasattr(tokens.colors, attr):
                logger.debug("令牌验证失败：缺少 colors.%s", attr)
                return False
            value = getattr(tokens.colors, attr)
            if not isinstance(value, str) or not value.strip():
                logger.debug("令牌验证失败：colors.%s 值无效", attr)
                return False

        if not hasattr(tokens, "typography"):
            logger.debug("令牌验证失败：缺少 'typography' 属性")
            return False

        for attr in required_typography:
            if not hasattr(tokens.typography, attr):
                logger.debug("令牌验证失败：缺少 typography.%s", attr)
                return False
            value = getattr(tokens.typography, attr)
            if not isinstance(value, str) or not value.strip():
                logger.debug("令牌验证失败：typography.%s 值无效", attr)
                return False

        if not hasattr(tokens, "layout"):
            logger.debug("令牌验证失败：缺少 'layout' 属性")
            return False

        for attr in required_layout:
            if not hasattr(tokens.layout, attr):
                logger.debug("令牌验证失败：缺少 layout.%s", attr)
                return False
            value = getattr(tokens.layout, attr)
            if not isinstance(value, int):
                logger.debug("令牌验证失败：layout.%s 必须是 int 类型", attr)
                return False

        return True

    except Exception as exc:
        logger.debug("令牌验证因异常而失败: %s", exc)
        return False


def _get_tokens() -> DesignTokensProtocol:
    """安全获取设计令牌，带验证和回退机制。"""
    try:
        from config.design_tokens import TOKENS

        if _validate_tokens(TOKENS):
            logger.debug("外部设计令牌已加载并验证")
            return TOKENS

        logger.warning("外部设计令牌验证失败，使用默认值")
        return DefaultDesignTokens()

    except ImportError:
        logger.debug("外部设计令牌模块不可用")
        return DefaultDesignTokens()

    except Exception:
        logger.exception("加载设计令牌时发生意外错误")
        return DefaultDesignTokens()


# 全局设计令牌实例（模块导入时加载一次）
TOKENS: Final[DesignTokensProtocol] = _get_tokens()


# ============================================================================
# 样式表管理
# ============================================================================


def _build_dialog_stylesheet() -> str:
    """构建完整的对话框样式表。"""
    return f"""
        /* ============================================
           对话框容器（透明外层）
           ============================================ */
        QDialog {{
            background-color: transparent;
        }}

        QFrame {{
            background-color: transparent;
        }}

        /* ============================================
           卡片容器
           ============================================ */
        QFrame#card {{
            background-color: #24262B;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
        }}

        /* ============================================
           关闭按钮
           ============================================ */
        QPushButton#close_btn {{
            background-color: transparent;
            color: #6B7280;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            padding: 0px;
            min-width: 28px;
            min-height: 28px;
            max-width: 28px;
            max-height: 28px;
        }}

        QPushButton#close_btn:hover {{
            background-color: rgba(255, 255, 255, 0.08);
            color: #F2F3F5;
        }}

        QPushButton#close_btn:pressed {{
            background-color: rgba(255, 255, 255, 0.12);
        }}

        /* ============================================
           标签样式（基于角色）
           ============================================ */

        QLabel[role="title"] {{
            color: #F2F3F5;
            font-family: {TOKENS.typography.font_primary};
            font-size: 18px;
            font-weight: 600;
        }}

        QLabel[role="subtitle"] {{
            color: #A8ADB4;
            font-family: {TOKENS.typography.font_primary};
            font-size: 12px;
        }}

        QLabel[role="btn_main"] {{
            color: #F2F3F5;
            font-family: {TOKENS.typography.font_primary};
            font-size: 13px;
            font-weight: 600;
        }}

        QLabel[role="btn_sub"] {{
            color: rgba(255, 255, 255, 0.72);
            font-family: {TOKENS.typography.font_primary};
            font-size: 10px;
        }}

        QLabel[role="btn_sub_disabled"] {{
            color: #A8ADB4;
            font-family: {TOKENS.typography.font_primary};
            font-size: 10px;
        }}

        QLabel[role="info"] {{
            color: #6B7280;
            font-family: {TOKENS.typography.font_primary};
            font-size: 10px;
        }}

        QLabel[role="hint"] {{
            color: #4B5563;
            font-family: {TOKENS.typography.font_primary};
            font-size: 10px;
        }}

        /* ============================================
           按钮样式（基于模式）
           ============================================ */

        /* 最新模式按钮 */
        QPushButton[mode="latest"] {{
            background-color: {TOKENS.colors.info};
            color: {TOKENS.colors.text_primary};
            font-size: 12px;
            border: 2px solid transparent;
            border-radius: 10px;
            padding: 10px 16px;
            outline: none;
        }}

        QPushButton[mode="latest"]:hover {{
            background-color: {TOKENS.colors.primary_hover};
            border: 2px solid rgba(33, 150, 243, 0.35);
        }}

        QPushButton[mode="latest"]:pressed {{
            background-color: {TOKENS.colors.info};
        }}

        QPushButton[mode="latest"]:focus {{
            border: 2px solid rgba(33, 150, 243, 0.5);
        }}

        /* 续看模式按钮（启用状态） */
        QPushButton[mode="continue"]:enabled {{
            background-color: {TOKENS.colors.success};
            color: {TOKENS.colors.text_primary};
            font-size: 12px;
            border: 2px solid transparent;
            border-radius: 10px;
            padding: 10px 16px;
            outline: none;
        }}

        QPushButton[mode="continue"]:enabled:hover {{
            background-color: {TOKENS.colors.success_muted};
            border: 2px solid rgba(76, 175, 80, 0.35);
        }}

        QPushButton[mode="continue"]:enabled:pressed {{
            background-color: {TOKENS.colors.success};
        }}

        QPushButton[mode="continue"]:enabled:focus {{
            border: 2px solid rgba(76, 175, 80, 0.5);
        }}

        /* 续看模式按钮（禁用状态） */
        QPushButton[mode="continue"]:disabled {{
            background-color: #2D3036;
            color: #6B7280;
            font-size: 12px;
            border: 2px solid transparent;
            border-radius: 10px;
            padding: 10px 16px;
            outline: none;
        }}
    """


# 缓存的样式表（模块加载时构建一次）
_DIALOG_STYLESHEET: Final[str] = _build_dialog_stylesheet()


# ============================================================================
# 辅助组件
# ============================================================================


class _CardButton(QPushButton):
    """支持鼠标拖动窗口的卡片按钮。

    用于实现无边框窗口的拖动移动功能。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._drag_pos: Optional[Any] = None
        self._dragging = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None:
            diff = event.globalPosition().toPoint() - self._drag_pos
            if diff.manhattanLength() > 3:
                self._dragging = True
                window = self.window()
                if window:
                    window.move(window.pos() + diff)
                self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        self._dragging = False
        super().mouseReleaseEvent(event)


# ============================================================================
# 模式选择对话框
# ============================================================================


class ModeSelectDialog(QDialog):
    """应用启动时的模式选择对话框。

    在应用启动时显示，允许用户选择首选的浏览模式。
    对话框支持键盘导航，并遵循平台 UI 约定。

    属性：
        result: 用户选择的模式，如果对话框未选择关闭则为 None

    信号：
        mode_selected(str): 选择模式时发出，参数是模式标识符

    类属性：
        MIN_DIALOG_WIDTH: 对话框最小宽度（逻辑像素）
        MIN_DIALOG_HEIGHT: 对话框最小高度（逻辑像素）
        MIN_BUTTON_WIDTH: 按钮最小宽度（逻辑像素）
        MIN_BUTTON_HEIGHT: 按钮最小高度（逻辑像素）
    """

    # 用户选择模式时发出的信号
    mode_selected = pyqtSignal(str)

    # 布局约束（DPI 自适应的最小值）
    MIN_DIALOG_WIDTH: ClassVar[int] = 400
    MIN_DIALOG_HEIGHT: ClassVar[int] = 360
    MIN_BUTTON_WIDTH: ClassVar[int] = 260
    MIN_BUTTON_HEIGHT: ClassVar[int] = 68

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        has_history: bool = False,
        last_session: Optional[dict[str, Any]] = None,
        tmp_count: int = 0,
    ) -> None:
        """初始化模式选择对话框。

        参数：
            parent: 用于模态显示和居中的父窗口。
            has_history: 是否存在浏览历史。为 False 时，续看按钮将被禁用。
            last_session: 包含上次会话信息的字典。
            tmp_count: 上次会话中未完成的下载数量。
        """
        super().__init__(parent)

        # 验证并规范化参数
        self._has_history = self._validate_bool(has_history, "has_history")
        self._tmp_count = self._validate_non_negative_int(tmp_count, "tmp_count")
        self._last_session: dict[str, Any] = (
            dict(last_session) if last_session else {}
        )

        # 对话框状态
        self.result: Optional[str] = None
        self._btn_latest: Optional[QPushButton] = None
        self._btn_continue: Optional[QPushButton] = None

        # 构建对话框
        self._setup_window()
        self._setup_ui()

        logger.debug(
            "ModeSelectDialog 初始化完成: has_history=%s, tmp_count=%d",
            self._has_history,
            self._tmp_count,
        )

    @staticmethod
    def _validate_bool(value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        logger.warning(
            "参数 '%s' 应为 bool 类型，实际为 %s；正在自动转换",
            name,
            type(value).__name__,
        )
        return bool(value)

    @staticmethod
    def _validate_non_negative_int(value: Any, name: str) -> int:
        if not isinstance(value, int):
            logger.warning(
                "参数 '%s' 应为 int 类型，实际为 %s；正在自动转换",
                name,
                type(value).__name__,
            )
            try:
                value = int(value)
            except (ValueError, TypeError):
                logger.warning("无法将 '%s' 转换为 int；默认为 0", name)
                return 0

        if value < 0:
            logger.warning("参数 '%s' 应为非负数；已修正为 0", name)
            return 0

        return value

    def _setup_window(self) -> None:
        """配置窗口属性并应用样式表。"""
        self.setWindowTitle(self._tr("选择浏览模式"))
        self.setMinimumSize(self.MIN_DIALOG_WIDTH, self.MIN_DIALOG_HEIGHT)

        # 无边框 + 透明背景
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.CustomizeWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # 应用样式表
        self.setStyleSheet(_DIALOG_STYLESHEET)

    def _setup_ui(self) -> None:
        """构建完整的用户界面。三段式层级：顶部标题、中部按钮、底部信息。"""
        # 外层透明容器
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)

        # 卡片容器
        card = QFrame()
        card.setObjectName("card")
        outer.addWidget(card)

        # 卡片内部布局
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(0)

        # 顶部区域：标题 + 关闭按钮
        self._create_header(layout)

        layout.addSpacing(28)

        # 中部区域：两个大按钮
        self._create_buttons(layout)

        layout.addStretch()

        # 底部区域：下载提示 + 快捷键提示
        self._create_footer(layout)

        self.adjustSize()

    def _create_header(self, layout: QVBoxLayout) -> None:
        """创建顶部标题区域，包含主标题、副标题和关闭按钮。"""
        # 标题行：标题 + 关闭按钮
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(0)

        # 主标题（支持拖动窗口）
        title = _CardButton(self._tr("Yande.re Viewer"))
        title.setProperty("role", "title")
        title.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        title.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "text-align: left; padding: 0; }"
        )
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title_row.addWidget(title)

        title_row.addStretch()

        # 关闭按钮
        close_btn = QPushButton("\u2715")
        close_btn.setObjectName("close_btn")
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addLayout(title_row)

        # 副标题
        subtitle = QLabel(self._tr("选择开始方式"))
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(subtitle)

    def _create_buttons(self, layout: QVBoxLayout) -> None:
        """创建模式选择按钮区域。"""
        # 最新模式按钮（始终可用）
        self._btn_latest = self._create_mode_button(
            main_text=self._tr("查看最新"),
            sub_text=self._tr("从最新发布的图片开始"),
            mode=MODE_LATEST,
            enabled=True,
        )
        layout.addWidget(self._btn_latest)

        layout.addSpacing(10)

        # 续看模式按钮（需要历史记录）
        self._btn_continue = self._create_mode_button(
            main_text=self._tr("继续上次浏览"),
            sub_text=self._get_continue_sub_text(),
            mode=MODE_CONTINUE,
            enabled=self._has_history,
        )
        layout.addWidget(self._btn_continue)

    def _get_continue_sub_text(self) -> str:
        """生成续看按钮副文案。"""
        if not self._has_history:
            return self._tr("暂无历史记录")

        if self._last_session:
            viewed = self._last_session.get("viewed_count", 0)
            last_id = self._last_session.get("last_viewed_id", "?")
            return self._tr("已看 {count} 张 · 上次位置 ID {id}").format(
                count=viewed, id=last_id
            )

        return self._tr("从上次位置继续浏览")

    def _create_mode_button(
        self,
        main_text: str,
        sub_text: str,
        mode: str,
        enabled: bool,
    ) -> QPushButton:
        """创建模式选择按钮（主文案 + 副文案合并为按钮文本）。"""
        btn = QPushButton()
        btn.setProperty("mode", mode)
        btn.setMinimumSize(self.MIN_BUTTON_WIDTH, self.MIN_BUTTON_HEIGHT)
        btn.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        btn.setEnabled(enabled)
        btn.setAutoDefault(False)
        btn.setDefault(False)

        # 构建按钮内部布局
        btn_layout = QVBoxLayout(btn)
        btn_layout.setContentsMargins(16, 10, 16, 10)
        btn_layout.setSpacing(2)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        main_label = QLabel(main_text)
        main_label.setProperty("role", "btn_main")
        main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(main_label)

        sub_label = QLabel(sub_text)
        sub_label.setProperty("role", "btn_sub" if enabled else "btn_sub_disabled")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(sub_label)

        if enabled:
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda: self._select_mode(mode))

        return btn

    def _create_footer(self, layout: QVBoxLayout) -> None:
        """创建底部辅助信息区域（下载提示 + 快捷键提示）。"""
        # 下载恢复提示（条件性）
        if self._tmp_count > 0:
            info_text = self._tr(
                "将自动恢复 {count} 个未完成下载"
            ).format(count=self._tmp_count)
            info_label = QLabel(info_text)
            info_label.setProperty("role", "info")
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info_label)
            layout.addSpacing(4)

        # 快捷键提示
        hint_text = self._tr("快捷键：1 查看最新 · 2 继续浏览 · Esc 关闭")
        hint_label = QLabel(hint_text)
        hint_label.setProperty("role", "hint")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint_label)

    def _select_mode(self, mode: str) -> None:
        """处理模式选择。"""
        if mode not in (MODE_LATEST, MODE_CONTINUE):
            logger.warning("无效的模式选择已忽略: %s", mode)
            return

        self.result = mode
        self.mode_selected.emit(mode)
        logger.info("用户选择模式: %s", mode)
        self.accept()

    def showEvent(self, event: QShowEvent) -> None:
        """处理对话框显示事件。"""
        super().showEvent(event)
        self._center_on_parent_or_screen()

    def _center_on_parent_or_screen(self) -> None:
        """将对话框居中于父窗口或屏幕。"""
        parent = self.parentWidget()

        if parent is not None and parent.isVisible():
            parent_geo = parent.geometry()
            parent_center = parent_geo.center()

            screen = QApplication.screenAt(parent_center)
            if screen is None:
                screen = QApplication.primaryScreen()

            if screen is not None:
                available = screen.availableGeometry()
                x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
                y = parent_geo.y() + (parent_geo.height() - self.height()) // 2

                x = max(available.x(), min(x, available.right() - self.width()))
                y = max(available.y(), min(y, available.bottom() - self.height()))

                self.move(x, y)
        else:
            screen = self.screen() or QApplication.primaryScreen()

            if screen is not None:
                available = screen.availableGeometry()
                x = available.x() + (available.width() - self.width()) // 2
                y = available.y() + (available.height() - self.height()) // 2
                self.move(x, y)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """处理键盘事件。

        支持的快捷键：
        - 1: 选择最新模式
        - 2: 选择续看模式（如可用）
        - Escape: 关闭对话框
        """
        key = event.key()

        if key == Qt.Key.Key_1:
            self._select_mode(MODE_LATEST)
        elif key == Qt.Key.Key_2 and self._has_history:
            self._select_mode(MODE_CONTINUE)
        elif key == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def get_result(self) -> Optional[str]:
        """获取用户选择的模式。应在 exec() 返回后调用。"""
        return self.result

    def _tr(self, text: str) -> str:
        """翻译文本。"""
        return QCoreApplication.translate("ModeSelectDialog", text)


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    "ModeSelectDialog",
    "MODE_LATEST",
    "MODE_CONTINUE",
]
