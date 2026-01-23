# -*- coding: utf-8 -*-
"""UI 模块初始化文件。

本模块提供应用程序的所有用户界面组件，包括：
    - MainWindow: 应用程序主窗口
    - FavoritesManager: 收藏管理器
    - UIFactory: UI 组件工厂
    - TagCloud: 标签云组件

子模块:
    - dialogs: 对话框组件（设置、备份、模式选择）
    - widgets: 自定义控件

Example:
    基本使用示例::

        from ui import MainWindow

        window = MainWindow()
        window.show()

Note:
    所有导入均采用延迟加载和错误容忍机制，
    即使部分组件加载失败也不会影响模块整体可用性。
"""

from __future__ import annotations

__version__ = "2.0.0"
__author__ = "YandeViewer Team"
__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    # 主要组件
    "MainWindow",
    "FavoritesManager",
    "UIFactory",
    "TagCloud",
    # 对话框
    "BackupRestoreDialog",
    "ModeSelectDialog",
    "SettingsDialog",
    # 工具函数
    "get_version",
    "check_components",
]

import logging
from typing import Dict, Optional, Type

# 配置模块级日志记录器
logger = logging.getLogger("YandeViewer.UI")

# =============================================================================
# 类型占位符（用于导入失败时的类型注解）
# =============================================================================

# 声明可能为 None 的组件类型
MainWindow: Optional[Type] = None
FavoritesManager: Optional[Type] = None
UIFactory: Optional[Type] = None
TagCloud: Optional[Type] = None
BackupRestoreDialog: Optional[Type] = None
ModeSelectDialog: Optional[Type] = None
SettingsDialog: Optional[Type] = None

# =============================================================================
# 核心组件导入
# =============================================================================


def _safe_import(module_path: str, names: tuple) -> Dict[str, Optional[Type]]:
    """安全导入模块中的指定名称。

    Args:
        module_path: 模块路径，如 'ui.main_window'
        names: 要导入的名称元组

    Returns:
        包含导入结果的字典，失败的项值为 None
    """
    result = {name: None for name in names}
    try:
        module = __import__(module_path, fromlist=names)
        for name in names:
            result[name] = getattr(module, name, None)
    except ImportError as exc:
        logger.warning("无法导入 %s: %s", module_path, exc)
    except Exception as exc:
        logger.error("导入 %s 时发生意外错误: %s", module_path, exc)
    return result


# 导入主窗口
_main_imports = _safe_import("ui.main_window", ("MainWindow",))
MainWindow = _main_imports.get("MainWindow")

# 导入收藏管理器
_fav_imports = _safe_import("ui.favorites_manager", ("FavoritesManager",))
FavoritesManager = _fav_imports.get("FavoritesManager")

# 导入 UI 组件
_comp_imports = _safe_import("ui.components", ("UIFactory", "TagCloud"))
UIFactory = _comp_imports.get("UIFactory")
TagCloud = _comp_imports.get("TagCloud")

# =============================================================================
# 对话框组件导入
# =============================================================================

_dialog_imports = _safe_import(
    "ui.dialogs",
    ("BackupRestoreDialog", "ModeSelectDialog", "SettingsDialog"),
)
BackupRestoreDialog = _dialog_imports.get("BackupRestoreDialog")
ModeSelectDialog = _dialog_imports.get("ModeSelectDialog")
SettingsDialog = _dialog_imports.get("SettingsDialog")

# =============================================================================
# 公共 API 函数
# =============================================================================


def get_version() -> str:
    """获取 UI 模块版本号。

    Returns:
        版本号字符串，格式为 'X.Y.Z'
    """
    return __version__


def check_components() -> Dict[str, bool]:
    """检查所有 UI 组件的加载状态。

    用于诊断哪些组件成功加载，哪些加载失败。

    Returns:
        字典，键为组件名称，值为是否成功加载的布尔值

    Example:
        >>> status = check_components()
        >>> if not status["MainWindow"]:
        ...     print("主窗口组件加载失败")
    """
    return {
        "MainWindow": MainWindow is not None,
        "FavoritesManager": FavoritesManager is not None,
        "UIFactory": UIFactory is not None,
        "TagCloud": TagCloud is not None,
        "BackupRestoreDialog": BackupRestoreDialog is not None,
        "ModeSelectDialog": ModeSelectDialog is not None,
        "SettingsDialog": SettingsDialog is not None,
    }