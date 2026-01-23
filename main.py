#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yande.re Ultimate Viewer 应用程序入口。

一个用于浏览 Yande.re 图站的桌面客户端应用程序。
基于 PyQt6 构建，支持图片预览、下载、收藏等功能。

系统要求:
    - Python 3.9+
    - PyQt6
    - Pillow
    - requests

使用方法:
    python main.py

License:
    MIT License

Author:
    YandeViewer Team
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import traceback
from types import TracebackType
from typing import TYPE_CHECKING, List, Optional, Type

# ============================================================
# 路径配置
# ============================================================

# 将模块目录添加到 Python 搜索路径
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)


# ============================================================
# 依赖检查
# ============================================================


def check_dependencies() -> List[str]:
    """检查必要的依赖是否已安装。

    Returns:
        缺失的依赖包名称列表。如果所有依赖都已安装，返回空列表。

    示例:
        >>> missing = check_dependencies()
        >>> if missing:
        ...     print(f"缺失依赖: {missing}")
    """
    missing: List[str] = []

    # 检查 PyQt6
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        missing.append("PyQt6")

    # 检查 Pillow
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")

    # 检查 requests
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    return missing


# 执行依赖检查
_missing_deps = check_dependencies()
if _missing_deps:
    print(f"错误: 缺少依赖包: {', '.join(_missing_deps)}")
    print(f"请使用以下命令安装: pip install {' '.join(_missing_deps)}")
    sys.exit(1)


# ============================================================
# PIL 安全配置
# ============================================================

from PIL import Image, ImageFile

# 限制最大像素数，防止解压缩炸弹攻击（Decompression Bomb）
Image.MAX_IMAGE_PIXELS = 1024 * 1024 * 50  # 5000 万像素

# 允许加载截断的图片文件
ImageFile.LOAD_TRUNCATED_IMAGES = True


# ============================================================
# PyQt6 导入
# ============================================================

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QMessageBox


# ============================================================
# 日志配置
# ============================================================


def setup_logging() -> logging.Logger:
    """配置应用程序日志系统。

    创建一个同时输出到控制台和文件的日志器。
    控制台输出 INFO 及以上级别，文件记录 DEBUG 及以上级别。

    Returns:
        配置完成的日志器实例。
    """
    logger = logging.getLogger("YandeViewer")

    # 避免重复配置
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 日志格式
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # 文件处理器
    try:
        file_handler = logging.FileHandler(
            "yande_viewer.log",
            encoding="utf-8",
            delay=True,  # 延迟创建文件
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        logger.warning("无法创建日志文件: %s", e)

    return logger


# 初始化日志
logger = setup_logging()


# ============================================================
# 暗色主题
# ============================================================


def setup_dark_palette(app: QApplication) -> None:
    """设置暗色主题调色板。

    为应用程序配置一套完整的暗色主题颜色方案。

    Args:
        app: Qt 应用程序实例。
    """
    palette = QPalette()

    # 基础颜色
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 33, 36))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 221, 222))
    palette.setColor(QPalette.ColorRole.Base, QColor(35, 39, 42))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 49, 52))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(50, 54, 57))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 221, 222))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 221, 222))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 49, 52))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 221, 222))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(88, 166, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(88, 166, 255))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

    # 禁用状态颜色
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(128, 128, 128),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(128, 128, 128),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(128, 128, 128),
    )

    app.setPalette(palette)


# ============================================================
# 全局异常处理
# ============================================================


class ExceptionHandler:
    """全局异常处理器。

    捕获未处理的异常并显示用户友好的错误对话框。
    同时将异常信息记录到日志文件。

    Attributes:
        _original_hook: 原始的异常处理钩子。
        _app: Qt 应用程序实例的弱引用。
    """

    def __init__(self) -> None:
        """初始化异常处理器。"""
        self._original_hook = sys.excepthook
        self._app: Optional[QApplication] = None

    def install(self, app: Optional[QApplication] = None) -> None:
        """安装异常处理钩子。

        Args:
            app: Qt 应用程序实例，用于显示错误对话框。
        """
        self._app = app
        sys.excepthook = self._handle_exception

    def uninstall(self) -> None:
        """卸载异常处理钩子，恢复原始处理器。"""
        sys.excepthook = self._original_hook

    def _handle_exception(
        self,
        exc_type: Type[BaseException],
        exc_value: BaseException,
        exc_tb: Optional[TracebackType],
    ) -> None:
        """处理未捕获的异常。

        Args:
            exc_type: 异常类型。
            exc_value: 异常实例。
            exc_tb: 异常回溯信息。
        """
        # 对于键盘中断，使用原始处理方式
        if issubclass(exc_type, KeyboardInterrupt):
            self._original_hook(exc_type, exc_value, exc_tb)
            return

        # 格式化错误信息
        error_msg = "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb)
        )
        logger.critical("未捕获的异常:\n%s", error_msg)

        # 显示错误对话框
        self._show_error_dialog(
            exc_type.__name__,
            str(exc_value),
            error_msg,
        )

    def _show_error_dialog(
        self,
        error_type: str,
        error_message: str,
        detailed_info: str,
    ) -> None:
        """显示错误对话框。

        Args:
            error_type: 异常类型名称。
            error_message: 简短的错误描述。
            detailed_info: 详细的错误信息（包含堆栈跟踪）。
        """
        try:
            if self._app is None or not QApplication.instance():
                return

            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("程序错误")
            msg_box.setText(f"发生未处理的错误: {error_type}")
            msg_box.setInformativeText(error_message)
            msg_box.setDetailedText(detailed_info)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()
        except Exception as e:
            # 如果显示对话框失败，至少打印到控制台
            print(f"无法显示错误对话框: {e}", file=sys.stderr)


# 全局异常处理器实例
_exception_handler = ExceptionHandler()


# ============================================================
# 主函数
# ============================================================


def main() -> int:
    """应用程序入口函数。

    初始化 Qt 应用程序、配置主题、创建并显示主窗口。

    Returns:
        程序退出码。0 表示正常退出，非零表示发生错误。
    """
    # 记录启动信息
    logger.info("=" * 50)
    logger.info("Yande.re Ultimate Viewer 正在启动...")
    logger.info("Python 版本: %s", sys.version)
    logger.info("运行平台: %s", platform.platform())
    logger.info("工作目录: %s", os.getcwd())
    logger.info("=" * 50)

    # 设置高 DPI 缩放策略（Qt6 新 API）
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    # 创建 Qt 应用程序实例
    app = QApplication(sys.argv)

    # 安装全局异常处理器
    _exception_handler.install(app)

    # 设置应用程序元数据
    app.setApplicationName("Yande.re Ultimate Viewer")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("YandeViewer")
    app.setOrganizationDomain("github.com/yandeviewer")

    # 设置应用程序样式和主题
    app.setStyle("Fusion")
    setup_dark_palette(app)

    # 设置默认字体
    font_family = "Segoe UI" if platform.system() == "Windows" else "sans-serif"
    font = QFont(font_family, 10)
    app.setFont(font)

    # 默认退出码
    exit_code = 1

    try:
        # 导入并创建主窗口
        from ui.main_window import MainWindow

        window = MainWindow()
        window.show()

        logger.info("应用程序启动成功")

        # 运行事件循环
        exit_code = app.exec()

        logger.info("应用程序已退出，退出码: %d", exit_code)

    except ImportError as e:
        logger.critical("模块导入错误: %s", e, exc_info=True)
        QMessageBox.critical(
            None,
            "导入错误",
            f"模块导入失败:\n{e}\n\n请确保所有依赖已正确安装。",
        )

    except Exception as e:
        logger.critical("应用程序启动失败: %s", e, exc_info=True)
        QMessageBox.critical(
            None,
            "启动错误",
            f"程序启动失败:\n{e}",
        )

    finally:
        # 清理资源
        _exception_handler.uninstall()
        logger.info("应用程序清理完成")

    return exit_code


# ============================================================
# 入口点
# ============================================================

if __name__ == "__main__":
    sys.exit(main())