"""
配置模块。

提供应用程序的所有配置管理功能，包括：
- 设计令牌（颜色、间距、字体等视觉变量）
- 应用配置（路径、API、性能设置）
- 用户设置（可持久化的用户偏好）

Example
-------
>>> from config import CONFIG, TOKENS, C, S, T, L, A
>>> print(CONFIG.api_url)
>>> print(C.accent)  # 快捷访问颜色

Notes
-----
快捷别名说明：
    - C: 颜色令牌 (colors)
    - S: 间距令牌 (spacing)
    - T: 字体令牌 (typography)
    - L: 布局令牌 (layout)
    - A: 动画令牌 (animation)
"""

from __future__ import annotations

__version__ = "2.0.0"
__author__ = "YandeViewer Team"

from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    pass

# =============================================================================
# 核心模块导入
# =============================================================================

try:
    from .design_tokens import (
        TOKENS,
        DesignTokens,
        ColorTokens,
        Spacing,
        Typography,
        Layout,
        Animation,
    )
except ImportError as e:
    raise ImportError(f"无法导入 design_tokens 模块: {e}") from e

try:
    from .app_config import AppConfig, CONFIG, DownloadConfig
except ImportError as e:
    raise ImportError(f"无法导入 app_config 模块: {e}") from e

try:
    from .user_settings import (
        FilterSettings,
        PerformanceSettings,
        UISettings,
        UserSettings,
    )
except ImportError as e:
    raise ImportError(f"无法导入 user_settings 模块: {e}") from e


# =============================================================================
# 快捷别名
# =============================================================================

C = TOKENS.colors       # 颜色令牌
S = TOKENS.spacing      # 间距令牌
T = TOKENS.typography   # 字体令牌
L = TOKENS.layout       # 布局令牌
A = TOKENS.animation    # 动画令牌


__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    # 应用配置
    "AppConfig",
    "CONFIG",
    "DownloadConfig",
    # 用户设置
    "FilterSettings",
    "PerformanceSettings",
    "UISettings",
    "UserSettings",
    # 设计令牌
    "TOKENS",
    "DesignTokens",
    "ColorTokens",
    "Spacing",
    "Typography",
    "Layout",
    "Animation",
    # 快捷别名
    "C",
    "S",
    "T",
    "L",
    "A",
]


def get_version() -> str:
    """
    获取模块版本号。

    Returns
    -------
    str
        当前模块版本号
    """
    return __version__


def get_config_summary() -> Dict[str, str]:
    """
    获取配置摘要信息。

    主要用于调试和日志记录。

    Returns
    -------
    dict
        包含版本、配置文件路径、基础目录和 API 地址的字典
    """
    return {
        "version": __version__,
        "config_file": str(CONFIG.config_file),
        "base_dir": str(CONFIG.base_dir),
        "api_url": CONFIG.api_url,
    }