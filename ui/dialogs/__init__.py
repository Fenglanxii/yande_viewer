# -*- coding: utf-8 -*-
"""对话框模块初始化文件。

本模块提供应用程序的所有对话框组件，包括：
    - BackupRestoreDialog: 备份恢复对话框
    - ModeSelectDialog: 模式选择对话框
    - SettingsDialog: 设置对话框

所有对话框遵循统一的设计规范，使用 DesignTokens 定义的样式。

Example:
    使用设置对话框::

        from ui.dialogs import SettingsDialog

        dialog = SettingsDialog(parent, settings)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_settings = dialog.get_settings()
"""

from __future__ import annotations

__version__ = "2.0.0"
__all__ = [
    "__version__",
    "BackupRestoreDialog",
    "ModeSelectDialog",
    "SettingsDialog",
    "MODE_LATEST",
    "MODE_CONTINUE",
    "get_available_dialogs",
]

import logging
from typing import List, Optional, Type

logger = logging.getLogger("YandeViewer.UI.Dialogs")

# =============================================================================
# 类型占位符
# =============================================================================

BackupRestoreDialog: Optional[Type] = None
ModeSelectDialog: Optional[Type] = None
SettingsDialog: Optional[Type] = None

# 模式常量的默认值（导入失败时使用）
MODE_LATEST: str = "latest"
MODE_CONTINUE: str = "continue"

# =============================================================================
# 安全导入
# =============================================================================

try:
    from .backup_dialog import BackupRestoreDialog
except ImportError as exc:
    logger.warning("无法导入 BackupRestoreDialog: %s", exc)

try:
    from .mode_select import ModeSelectDialog, MODE_LATEST, MODE_CONTINUE
except ImportError as exc:
    logger.warning("无法导入 ModeSelectDialog: %s", exc)

try:
    from .settings_dialog import SettingsDialog
except ImportError as exc:
    logger.warning("无法导入 SettingsDialog: %s", exc)


# =============================================================================
# 公共 API
# =============================================================================


def get_available_dialogs() -> List[str]:
    """获取成功加载的对话框列表。

    用于诊断哪些对话框组件可用。

    Returns:
        成功加载的对话框类名列表

    Example:
        >>> dialogs = get_available_dialogs()
        >>> print(dialogs)
        ['BackupRestoreDialog', 'ModeSelectDialog', 'SettingsDialog']
    """
    available = []
    if BackupRestoreDialog is not None:
        available.append("BackupRestoreDialog")
    if ModeSelectDialog is not None:
        available.append("ModeSelectDialog")
    if SettingsDialog is not None:
        available.append("SettingsDialog")
    return available