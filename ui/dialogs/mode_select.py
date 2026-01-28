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
from PyQt6.QtGui import QCursor, QKeyEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
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
    """颜色令牌协议，定义必需的颜色属性。

    所有颜色值应为有效的 CSS 颜色字符串（十六进制、rgb 等）。
    """

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
    """排版令牌协议，定义必需的字体属性。

    字体值应为有效的 CSS font-family 字符串。
    """

    font_primary: str
    font_icon: str


class LayoutTokensProtocol(Protocol):
    """布局令牌协议，定义必需的布局属性。"""

    radius_md: int


class DesignTokensProtocol(Protocol):
    """设计令牌完整协议。

    外部令牌提供者必须实现此接口才能与对话框的样式系统兼容。
    """

    colors: ColorTokensProtocol
    typography: TypographyTokensProtocol
    layout: LayoutTokensProtocol


@dataclass(frozen=True)
class DefaultColorTokens:
    """默认颜色令牌，作为备用值使用。

    这些颜色遵循深色主题设计，专为图片浏览应用优化，可减少眼睛疲劳。

    属性：
        bg_base: 对话框主背景色
        bg_surface: 提升表面背景（禁用按钮等）
        text_primary: 主要文本颜色，用于高对比度可读性
        text_muted: 次要文本颜色，用于不太突出的信息
        info: 信息元素强调色（最新模式按钮）
        primary_hover: 主要操作的悬停状态
        success: 成功指示色（续看模式按钮）
        success_muted: 成功元素的悬停状态
        warning: 警告指示色
    """

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
    """默认排版令牌，作为备用值使用。

    使用系统无衬线字体以实现最大平台兼容性。

    属性：
        font_primary: 正文主要字体族
        font_icon: 包含图标的文本字体族（emoji 回退）
    """

    font_primary: str = "sans-serif"
    font_icon: str = "sans-serif"


@dataclass(frozen=True)
class DefaultLayoutTokens:
    """默认布局令牌，作为备用值使用。

    属性：
        radius_md: 按钮和容器的中等圆角半径
    """

    radius_md: int = 6


@dataclass(frozen=True)
class DefaultDesignTokens:
    """完整的默认设计令牌容器。

    当外部设计令牌不可用或验证失败时，提供完整的备用值集合。
    所有嵌套的令牌类都使用各自的默认值创建。

    示例::

        tokens = DefaultDesignTokens()
        print(tokens.colors.bg_base)  # '#1E1E1E'
    """

    colors: DefaultColorTokens = field(default_factory=DefaultColorTokens)
    typography: DefaultTypographyTokens = field(
        default_factory=DefaultTypographyTokens
    )
    layout: DefaultLayoutTokens = field(default_factory=DefaultLayoutTokens)


def _validate_tokens(tokens: Any) -> bool:
    """验证令牌对象是否具有所有必需的属性。

    执行令牌结构的全面验证，包括：
    - 所有必需嵌套对象的存在性（colors、typography、layout）
    - 每个嵌套对象内所有必需属性的存在性
    - 每个属性值的类型验证
    - 颜色和字体值的非空字符串验证

    参数：
        tokens: 要验证的令牌对象。可以是任何可能实现
            DesignTokensProtocol 的对象。

    返回：
        如果所有必需属性存在且通过类型/值检查，返回 True；
        否则返回 False。验证期间发生任何异常也返回 False。

    注意：
        此函数捕获所有异常以确保可靠的回退行为。
        验证失败会记录在调试级别日志中。
    """
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
        # 验证 colors 命名空间
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

        # 验证 typography 命名空间
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

        # 验证 layout 命名空间
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
    """安全获取设计令牌，带验证和回退机制。

    尝试从配置模块导入外部设计令牌，验证其结构完整性，
    必要时回退到内置默认值。

    该函数处理三种失败场景：
    1. ImportError：外部令牌模块不可用
    2. 验证失败：令牌存在但不完整/无效
    3. 意外异常：加载期间的任何其他错误

    返回：
        实现 DesignTokensProtocol 的有效设计令牌对象。
        如果外部令牌不可用或无效，返回 DefaultDesignTokens()。
    """
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
    """构建完整的对话框样式表。

    创建集中式样式表，使用对象名称和动态属性为对话框中的
    所有组件设置样式。

    重要设计决策：
    - 使用 border 而非 outline 实现焦点指示，避免跨平台兼容性问题
    - 显式设置 outline: none 移除系统默认焦点框
    - 通过动态属性 [mode="..."] 实现模式特定样式

    返回：
        对话框的完整 CSS 样式表字符串。
    """
    return f"""
        /* ============================================
           对话框容器
           ============================================ */
        QDialog {{
            background-color: {TOKENS.colors.bg_base};
        }}

        QFrame {{
            background-color: transparent;
        }}

        /* ============================================
           标签样式（基于角色）
           ============================================ */

        QLabel[role="title"] {{
            color: {TOKENS.colors.text_primary};
            font-family: {TOKENS.typography.font_icon};
            font-size: 16px;
            font-weight: bold;
        }}

        QLabel[role="subtitle"] {{
            color: {TOKENS.colors.text_muted};
            font-family: {TOKENS.typography.font_primary};
            font-size: 11px;
        }}

        QLabel[role="warning"] {{
            color: {TOKENS.colors.warning};
            font-family: {TOKENS.typography.font_primary};
            font-size: 9px;
        }}

        QLabel[role="hint"] {{
            color: {TOKENS.colors.text_muted};
            font-size: 9px;
        }}

        /* ============================================
           按钮样式（基于模式）
           注意：使用 border 替代 outline 以确保
           跨平台一致的焦点样式显示
           ============================================ */

        /* 最新模式按钮 - 信息/主要配色 */
        QPushButton[mode="latest"] {{
            background-color: {TOKENS.colors.info};
            color: {TOKENS.colors.text_primary};
            font-family: {TOKENS.typography.font_icon};
            font-size: 11px;
            border: 2px solid transparent;
            border-radius: {TOKENS.layout.radius_md}px;
            padding: 8px 16px;
            outline: none;
        }}

        QPushButton[mode="latest"]:hover {{
            background-color: {TOKENS.colors.primary_hover};
        }}

        QPushButton[mode="latest"]:pressed {{
            background-color: {TOKENS.colors.info};
        }}

        QPushButton[mode="latest"]:focus {{
            border: 2px solid {TOKENS.colors.text_primary};
        }}

        /* 续看模式按钮（启用状态） - 成功配色 */
        QPushButton[mode="continue"]:enabled {{
            background-color: {TOKENS.colors.success};
            color: {TOKENS.colors.text_primary};
            font-family: {TOKENS.typography.font_icon};
            font-size: 11px;
            border: 2px solid transparent;
            border-radius: {TOKENS.layout.radius_md}px;
            padding: 8px 16px;
            outline: none;
        }}

        QPushButton[mode="continue"]:enabled:hover {{
            background-color: {TOKENS.colors.success_muted};
        }}

        QPushButton[mode="continue"]:enabled:pressed {{
            background-color: {TOKENS.colors.success};
        }}

        QPushButton[mode="continue"]:enabled:focus {{
            border: 2px solid {TOKENS.colors.text_primary};
        }}

        /* 续看模式按钮（禁用状态） - 柔和外观 */
        QPushButton[mode="continue"]:disabled {{
            background-color: {TOKENS.colors.bg_surface};
            color: {TOKENS.colors.text_muted};
            font-family: {TOKENS.typography.font_icon};
            font-size: 11px;
            border: 2px solid transparent;
            border-radius: {TOKENS.layout.radius_md}px;
            padding: 8px 16px;
            outline: none;
        }}
    """


# 缓存的样式表（模块加载时构建一次）
_DIALOG_STYLESHEET: Final[str] = _build_dialog_stylesheet()


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

    示例::

        dialog = ModeSelectDialog(
            parent=main_window,
            has_history=True,
            last_session={"viewed_count": 50, "last_viewed_id": 12345}
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            mode = dialog.get_result()
            if mode == MODE_LATEST:
                start_from_latest()
            elif mode == MODE_CONTINUE:
                resume_browsing()
    """

    # 用户选择模式时发出的信号
    mode_selected = pyqtSignal(str)

    # 布局约束（DPI 自适应的最小值）
    MIN_DIALOG_WIDTH: ClassVar[int] = 380
    MIN_DIALOG_HEIGHT: ClassVar[int] = 320
    MIN_BUTTON_WIDTH: ClassVar[int] = 240
    MIN_BUTTON_HEIGHT: ClassVar[int] = 56

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
                如果为 None，对话框将居中于主屏幕。
            has_history: 是否存在浏览历史。为 False 时，
                续看按钮将被禁用并显示解释性工具提示。
            last_session: 包含上次会话信息的字典。
                预期键：
                - viewed_count (int): 上次会话中查看的图片数量
                - last_viewed_id (int): 上次查看的图片 ID
                如果为 None 或为空，显示通用续看文本。
            tmp_count: 上次会话中未完成的下载数量。
                如果大于 0，显示关于自动恢复下载的警告消息。
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
        """验证并将值转换为布尔值。

        参数：
            value: 要验证和转换的值
            name: 用于诊断日志的参数名称

        返回：
            验证后的布尔值
        """
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
        """验证并将值转换为非负整数。

        参数：
            value: 要验证和转换的值
            name: 用于诊断日志的参数名称

        返回：
            验证后的非负整数，无效输入默认为 0
        """
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
        """配置窗口属性并应用样式表。

        设置窗口标题、最小尺寸、窗口标志和样式表。
        """
        self.setWindowTitle(self._tr("选择浏览模式"))
        self.setMinimumSize(self.MIN_DIALOG_WIDTH, self.MIN_DIALOG_HEIGHT)

        # 移除标题栏上的帮助按钮
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        # 应用样式表
        self.setStyleSheet(_DIALOG_STYLESHEET)

    def _setup_ui(self) -> None:
        """构建完整的用户界面。

        包含标题区域、警告区域（条件性）、按钮区域和提示区域。
        """
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题区域
        self._create_header(layout)

        # 未完成下载警告（条件性）
        if self._tmp_count > 0:
            self._create_warning(layout)

        layout.addSpacing(15)

        # 模式选择按钮
        self._create_buttons(layout)

        # 首次使用提示（条件性）
        if not self._has_history:
            self._create_hint(layout)

        layout.addStretch()
        self.adjustSize()

    def _create_header(self, layout: QVBoxLayout) -> None:
        """创建标题区域。

        参数：
            layout: 父布局
        """
        title = QLabel(self._tr("🎨 Yande.re Viewer"))
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(self._tr("选择浏览模式"))
        subtitle.setProperty("role", "subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

    def _create_warning(self, layout: QVBoxLayout) -> None:
        """创建未完成下载警告。

        参数：
            layout: 父布局
        """
        warning_text = self._tr(
            "⚠️ 发现 {count} 个未完成下载，启动后将自动恢复"
        ).format(count=self._tmp_count)

        warn_label = QLabel(warning_text)
        warn_label.setProperty("role", "warning")
        warn_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warn_label.setWordWrap(True)
        layout.addWidget(warn_label)

    def _create_buttons(self, layout: QVBoxLayout) -> None:
        """创建模式选择按钮。

        参数：
            layout: 父布局
        """
        btn_frame = QFrame()
        btn_layout = QVBoxLayout(btn_frame)
        btn_layout.setSpacing(10)

        # 最新模式按钮（始终可用）
        self._btn_latest = self._create_mode_button(
            text=self._tr("🆕 最新模式\n从最新发布的图片开始"),
            mode=MODE_LATEST,
            enabled=True,
        )
        btn_layout.addWidget(
            self._btn_latest, alignment=Qt.AlignmentFlag.AlignCenter
        )

        # 续看模式按钮（需要历史记录）
        continue_text = self._get_continue_button_text()
        self._btn_continue = self._create_mode_button(
            text=continue_text,
            mode=MODE_CONTINUE,
            enabled=self._has_history,
        )
        btn_layout.addWidget(
            self._btn_continue, alignment=Qt.AlignmentFlag.AlignCenter
        )

        layout.addWidget(btn_frame)

    def _get_continue_button_text(self) -> str:
        """生成续看按钮文本。

        返回：
            格式化的按钮文本
        """
        base_text = self._tr("📖 续看模式") + "\n"

        if self._last_session:
            viewed = self._last_session.get("viewed_count", 0)
            last_id = self._last_session.get("last_viewed_id", "?")
            detail = self._tr("已看{count}张，上次: ID {id}").format(
                count=viewed, id=last_id
            )
            return base_text + detail

        return base_text + self._tr("从上次位置继续浏览")

    def _create_mode_button(
        self,
        text: str,
        mode: str,
        enabled: bool,
    ) -> QPushButton:
        """创建模式选择按钮。

        参数：
            text: 按钮显示文本
            mode: 模式标识符（用于样式匹配）
            enabled: 是否启用

        返回：
            配置好的按钮实例
        """
        btn = QPushButton(text)
        btn.setProperty("mode", mode)
        btn.setMinimumSize(self.MIN_BUTTON_WIDTH, self.MIN_BUTTON_HEIGHT)
        btn.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        btn.setEnabled(enabled)

        # 关键修复：禁用自动默认行为以避免系统焦点边框
        btn.setAutoDefault(False)
        btn.setDefault(False)

        if enabled:
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda: self._select_mode(mode))
        else:
            btn.setToolTip(self._tr("无浏览历史记录，无法使用续看模式"))

        return btn

    def _create_hint(self, layout: QVBoxLayout) -> None:
        """创建首次使用提示。

        参数：
            layout: 父布局
        """
        hint = QLabel(self._tr("（首次使用，无历史记录）"))
        hint.setProperty("role", "hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    def _select_mode(self, mode: str) -> None:
        """处理模式选择。

        参数：
            mode: 选择的模式标识符
        """
        if mode not in (MODE_LATEST, MODE_CONTINUE):
            logger.warning("无效的模式选择已忽略: %s", mode)
            return

        self.result = mode
        self.mode_selected.emit(mode)
        logger.info("用户选择模式: %s", mode)
        self.accept()

    def showEvent(self, event: QShowEvent) -> None:
        """处理对话框显示事件。

        参数：
            event: 显示事件
        """
        super().showEvent(event)
        self._center_on_parent_or_screen()

    def _center_on_parent_or_screen(self) -> None:
        """将对话框居中于父窗口或屏幕。

        优先居中于可见父窗口，否则居中于当前屏幕。
        位置会被约束在可用屏幕区域内。
        """
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

                # 约束在可用区域内
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

        参数：
            event: 键盘事件
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
        """获取用户选择的模式。

        应在 exec() 返回后调用。

        返回：
            MODE_LATEST: 用户选择最新模式
            MODE_CONTINUE: 用户选择续看模式
            None: 对话框未选择关闭
        """
        return self.result

    def _tr(self, text: str) -> str:
        """翻译文本。

        参数：
            text: 源文本

        返回：
            翻译后的文本（如有）或原文
        """
        return QCoreApplication.translate("ModeSelectDialog", text)


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    "ModeSelectDialog",
    "MODE_LATEST",
    "MODE_CONTINUE",
]