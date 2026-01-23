"""输入法控制器模块。

提供跨平台的输入法状态管理功能，支持临时切换到英文输入模式。
主要用于处理键盘快捷键时避免输入法干扰。

支持平台:
    - Windows: 完整支持（使用 IMM32 API）
    - macOS: 基础支持（使用 AppleScript）
    - Linux: 暂不支持

Example:
    >>> from utils.ime_controller import IME
    >>> # 临时切换到英文模式
    >>> with IME.english_mode():
    ...     # 在此处理快捷键输入
    ...     handle_keyboard_input()
    >>> # 退出后自动恢复原输入法状态

Note:
    在 Windows 上，需要以普通用户权限运行，不需要管理员权限。
"""

from __future__ import annotations

import logging
import platform
import subprocess
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# 平台标识常量
PLATFORM_WINDOWS: str = "Windows"
PLATFORM_MACOS: str = "Darwin"
PLATFORM_LINUX: str = "Linux"

# 当前运行平台
CURRENT_PLATFORM: str = platform.system()


class IMEError(Exception):
    """输入法控制异常基类。"""

    pass


class IMENotSupportedError(IMEError):
    """当前平台不支持输入法控制。"""

    pass


class BaseIMEController(ABC):
    """输入法控制器抽象基类。

    定义输入法控制器的标准接口，所有平台实现都应继承此类。

    Methods:
        get_status: 获取当前输入法状态
        switch_to_english: 切换到英文输入
        switch_to_chinese: 切换到中文输入
        english_mode: 临时英文模式上下文管理器
    """

    @abstractmethod
    def get_status(self, hwnd: int | None = None) -> bool:
        """获取输入法状态。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。
                如果为 None，则使用当前前台窗口。

        Returns:
            True 表示中文输入法已激活，False 表示英文模式。
        """
        pass

    @abstractmethod
    def switch_to_english(self, hwnd: int | None = None) -> None:
        """切换到英文输入模式。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。
        """
        pass

    @abstractmethod
    def switch_to_chinese(self, hwnd: int | None = None) -> None:
        """切换到中文输入模式。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。
        """
        pass

    @contextmanager
    def english_mode(self, hwnd: int | None = None) -> Iterator[None]:
        """临时英文输入模式上下文管理器。

        进入上下文时切换到英文模式，退出时恢复原状态。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。

        Yields:
            无返回值。

        Example:
            >>> controller = create_ime_controller()
            >>> with controller.english_mode():
            ...     # 在此区域内强制英文输入
            ...     process_hotkey()
            >>> # 退出后自动恢复
        """
        was_chinese = self.get_status(hwnd)
        try:
            self.switch_to_english(hwnd)
            yield
        finally:
            if was_chinese:
                self.switch_to_chinese(hwnd)


class WindowsIMEController(BaseIMEController):
    """Windows 平台输入法控制器。

    使用 Windows IMM32 API 控制输入法状态。

    Attributes:
        is_available: 控制器是否可用。

    Note:
        依赖 ctypes 访问 Windows API，无需额外安装依赖。
    """

    def __init__(self) -> None:
        """初始化 Windows 输入法控制器。

        尝试加载 IMM32 和 User32 DLL。如果加载失败，
        控制器将标记为不可用，但不会抛出异常。
        """
        self.is_available: bool = False
        self._saved_states: dict[int, bool] = {}
        self._imm32: Any = None
        self._user32: Any = None

        if CURRENT_PLATFORM != PLATFORM_WINDOWS:
            logger.debug("非 Windows 平台，IME 控制器不可用")
            return

        try:
            import ctypes

            self._imm32 = ctypes.windll.imm32
            self._user32 = ctypes.windll.user32
            self.is_available = True
            logger.debug("Windows IME 控制器初始化成功")
        except AttributeError as e:
            logger.warning("无法加载 Windows DLL: %s", e)
        except OSError as e:
            logger.warning("IME 控制器初始化失败: %s", e)

    def _get_hwnd(self, hwnd: int | None) -> int:
        """获取有效的窗口句柄。

        Args:
            hwnd: 指定的窗口句柄，或 None。

        Returns:
            有效的窗口句柄。如果未指定，返回当前前台窗口句柄。
        """
        if hwnd is not None:
            return hwnd

        if self._user32 is None:
            return 0

        try:
            return self._user32.GetForegroundWindow()
        except Exception:
            return 0

    def _get_ime_context(self, hwnd: int) -> int | None:
        """获取输入法上下文。

        Args:
            hwnd: 窗口句柄。

        Returns:
            输入法上下文句柄，失败返回 None。
        """
        if self._imm32 is None:
            return None

        try:
            himc = self._imm32.ImmGetContext(hwnd)
            return himc if himc else None
        except Exception as e:
            logger.debug("获取 IME 上下文失败: %s", e)
            return None

    def _release_ime_context(self, hwnd: int, himc: int) -> None:
        """释放输入法上下文。

        Args:
            hwnd: 窗口句柄。
            himc: 输入法上下文句柄。
        """
        if self._imm32 is None:
            return

        try:
            self._imm32.ImmReleaseContext(hwnd, himc)
        except Exception as e:
            logger.debug("释放 IME 上下文失败: %s", e)

    def get_status(self, hwnd: int | None = None) -> bool:
        """获取输入法状态。

        Args:
            hwnd: 窗口句柄。如果为 None，使用当前前台窗口。

        Returns:
            True 表示中文输入法已激活，False 表示英文模式或不可用。
        """
        if not self.is_available:
            return False

        hwnd = self._get_hwnd(hwnd)
        if hwnd == 0:
            return False

        himc = self._get_ime_context(hwnd)
        if himc is None:
            return False

        try:
            status = self._imm32.ImmGetOpenStatus(himc)
            return bool(status)
        except Exception as e:
            logger.debug("获取 IME 状态失败: %s", e)
            return False
        finally:
            self._release_ime_context(hwnd, himc)

    def save_state(self, hwnd: int | None = None) -> None:
        """保存当前输入法状态。

        用于后续恢复。每个窗口句柄独立保存状态。

        Args:
            hwnd: 窗口句柄。
        """
        if not self.is_available:
            return

        hwnd = self._get_hwnd(hwnd)
        if hwnd == 0:
            return

        self._saved_states[hwnd] = self.get_status(hwnd)
        logger.debug("保存 IME 状态: hwnd=%d, chinese=%s", hwnd, self._saved_states[hwnd])

    def restore_state(self, hwnd: int | None = None) -> None:
        """恢复之前保存的输入法状态。

        Args:
            hwnd: 窗口句柄。
        """
        if not self.is_available:
            return

        hwnd = self._get_hwnd(hwnd)
        if hwnd == 0 or hwnd not in self._saved_states:
            return

        was_chinese = self._saved_states.pop(hwnd)
        logger.debug("恢复 IME 状态: hwnd=%d, chinese=%s", hwnd, was_chinese)

        if was_chinese:
            self.switch_to_chinese(hwnd)
        else:
            self.switch_to_english(hwnd)

    @contextmanager
    def english_mode(self, hwnd: int | None = None) -> Iterator[None]:
        """临时英文输入模式。

        使用保存/恢复机制确保状态正确恢复。

        Args:
            hwnd: 窗口句柄。

        Yields:
            无返回值。

        Example:
            >>> controller = WindowsIMEController()
            >>> with controller.english_mode():
            ...     # 处理需要英文输入的操作
            ...     handle_shortcut()
        """
        self.save_state(hwnd)
        try:
            self.switch_to_english(hwnd)
            yield
        finally:
            self.restore_state(hwnd)

    def switch_to_english(self, hwnd: int | None = None) -> None:
        """切换到英文输入模式。

        Args:
            hwnd: 窗口句柄。
        """
        if not self.is_available:
            return

        hwnd = self._get_hwnd(hwnd)
        if hwnd == 0:
            return

        himc = self._get_ime_context(hwnd)
        if himc is None:
            return

        try:
            self._imm32.ImmSetOpenStatus(himc, False)
            logger.debug("切换到英文模式: hwnd=%d", hwnd)
        except Exception as e:
            logger.debug("切换英文模式失败: %s", e)
        finally:
            self._release_ime_context(hwnd, himc)

    def switch_to_chinese(self, hwnd: int | None = None) -> None:
        """切换到中文输入模式。

        Args:
            hwnd: 窗口句柄。
        """
        if not self.is_available:
            return

        hwnd = self._get_hwnd(hwnd)
        if hwnd == 0:
            return

        himc = self._get_ime_context(hwnd)
        if himc is None:
            return

        try:
            self._imm32.ImmSetOpenStatus(himc, True)
            logger.debug("切换到中文模式: hwnd=%d", hwnd)
        except Exception as e:
            logger.debug("切换中文模式失败: %s", e)
        finally:
            self._release_ime_context(hwnd, himc)


class MacIMEController(BaseIMEController):
    """macOS 平台输入法控制器。

    使用 AppleScript 控制输入法切换。

    Note:
        - 状态检测功能尚未实现
        - 需要系统授予终端/应用辅助功能权限
    """

    # AppleScript 切换英文输入源的命令
    # Key code 102 通常对应英文输入源切换
    _SWITCH_ENGLISH_SCRIPT: str = (
        'tell application "System Events" to key code 102'
    )

    # 子进程超时时间（秒）
    _SUBPROCESS_TIMEOUT: float = 2.0

    def get_status(self, hwnd: int | None = None) -> bool:
        """获取输入法状态。

        Args:
            hwnd: 忽略此参数（macOS 不使用窗口句柄）。

        Returns:
            始终返回 False（状态检测尚未实现）。

        Todo:
            实现 macOS 输入法状态检测。
        """
        # TODO: 使用 CGEventSource 或其他方式检测当前输入源
        return False

    def switch_to_english(self, hwnd: int | None = None) -> None:
        """切换到英文输入模式。

        通过 AppleScript 发送按键事件切换输入源。

        Args:
            hwnd: 忽略此参数。

        Note:
            首次使用时可能需要授权辅助功能权限。
        """
        try:
            result = subprocess.run(
                ["osascript", "-e", self._SWITCH_ENGLISH_SCRIPT],
                capture_output=True,
                timeout=self._SUBPROCESS_TIMEOUT,
                check=False,
            )
            if result.returncode != 0:
                logger.debug(
                    "AppleScript 执行失败: %s",
                    result.stderr.decode(errors="ignore"),
                )
        except subprocess.TimeoutExpired:
            logger.debug("AppleScript 执行超时")
        except FileNotFoundError:
            logger.debug("osascript 命令不可用")
        except Exception as e:
            logger.debug("切换英文模式失败: %s", e)

    def switch_to_chinese(self, hwnd: int | None = None) -> None:
        """切换到中文输入模式。

        Args:
            hwnd: 忽略此参数。

        Note:
            macOS 通常不需要主动切回中文，
            用户可通过快捷键或点击输入法图标切换。
        """
        # macOS 输入法切换通常由用户手动完成
        pass


class LinuxIMEController(BaseIMEController):
    """Linux 平台输入法控制器。

    目前为占位实现，不提供实际功能。

    Todo:
        - 支持 IBus 输入法框架
        - 支持 Fcitx 输入法框架
    """

    def get_status(self, hwnd: int | None = None) -> bool:
        """获取输入法状态。

        Returns:
            始终返回 False（尚未实现）。
        """
        return False

    def switch_to_english(self, hwnd: int | None = None) -> None:
        """切换到英文输入模式。

        Note:
            尚未实现，不执行任何操作。
        """
        pass

    def switch_to_chinese(self, hwnd: int | None = None) -> None:
        """切换到中文输入模式。

        Note:
            尚未实现，不执行任何操作。
        """
        pass


class NullIMEController(BaseIMEController):
    """空实现输入法控制器。

    用于不支持输入法控制的平台或初始化失败时的降级方案。
    所有方法都是空操作，不会抛出异常。
    """

    def get_status(self, hwnd: int | None = None) -> bool:
        """获取输入法状态。

        Returns:
            始终返回 False。
        """
        return False

    def switch_to_english(self, hwnd: int | None = None) -> None:
        """切换到英文输入模式（空操作）。"""
        pass

    def switch_to_chinese(self, hwnd: int | None = None) -> None:
        """切换到中文输入模式（空操作）。"""
        pass


def create_ime_controller() -> BaseIMEController:
    """创建适合当前平台的输入法控制器。

    根据运行平台自动选择合适的控制器实现。
    如果平台特定控制器初始化失败，返回空实现。

    Returns:
        输入法控制器实例。

    Example:
        >>> controller = create_ime_controller()
        >>> with controller.english_mode():
        ...     process_keyboard_input()
    """
    if CURRENT_PLATFORM == PLATFORM_WINDOWS:
        try:
            controller = WindowsIMEController()
            if controller.is_available:
                return controller
            logger.info("Windows IME 控制器不可用，使用空实现")
        except Exception as e:
            logger.warning("创建 Windows IME 控制器失败: %s", e)

    elif CURRENT_PLATFORM == PLATFORM_MACOS:
        logger.debug("使用 macOS IME 控制器")
        return MacIMEController()

    elif CURRENT_PLATFORM == PLATFORM_LINUX:
        logger.debug("Linux IME 控制暂不支持，使用空实现")
        return LinuxIMEController()

    return NullIMEController()


class IMEController:
    """输入法控制器门面类。

    提供统一的 API 访问底层平台特定的输入法控制器。
    推荐使用此类或全局 IME 实例，而非直接使用平台特定类。

    Attributes:
        controller: 底层的平台特定控制器实例。

    Example:
        >>> ime = IMEController()
        >>> if ime.get_status():
        ...     print("当前为中文输入模式")
        >>> with ime.english_mode():
        ...     handle_hotkey()
    """

    def __init__(self) -> None:
        """初始化输入法控制器。

        自动创建适合当前平台的底层控制器。
        """
        self._controller: BaseIMEController = create_ime_controller()

    @property
    def controller(self) -> BaseIMEController:
        """获取底层控制器实例。"""
        return self._controller

    @property
    def is_available(self) -> bool:
        """检查控制器是否可用。

        Returns:
            True 表示输入法控制功能可用。
        """
        if isinstance(self._controller, WindowsIMEController):
            return self._controller.is_available
        elif isinstance(self._controller, NullIMEController):
            return False
        return True

    def get_status(self, hwnd: int | None = None) -> bool:
        """获取输入法状态。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。

        Returns:
            True 表示中文输入法已激活。
        """
        return self._controller.get_status(hwnd)

    def switch_to_english(self, hwnd: int | None = None) -> None:
        """切换到英文输入模式。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。
        """
        self._controller.switch_to_english(hwnd)

    def switch_to_chinese(self, hwnd: int | None = None) -> None:
        """切换到中文输入模式。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。
        """
        self._controller.switch_to_chinese(hwnd)

    @contextmanager
    def english_mode(self, hwnd: int | None = None) -> Iterator[None]:
        """临时英文输入模式上下文管理器。

        Args:
            hwnd: 窗口句柄（仅 Windows 有效）。

        Yields:
            无返回值。
        """
        with self._controller.english_mode(hwnd):
            yield


# 全局输入法控制器实例
# 推荐使用此实例而非创建新的 IMEController
IME: BaseIMEController = create_ime_controller()