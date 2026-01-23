"""
核心模块。

提供应用程序的核心功能组件，包括：
- 会话管理 (SessionManager)
- 事件总线 (EventBus)
- 下载管理 (DownloadManager)
- 缓存系统 (LRUCache)
- 图片预加载 (TurboPreloader)

这些组件是线程安全的，可在多线程环境中使用。

Example
-------
>>> from core import SESSION, EVENT_BUS, LRUCache
>>> response = SESSION.get("https://example.com/api")
>>> EVENT_BUS.subscribe(EventType.IMAGE_LOADED, my_handler)
"""

from __future__ import annotations

__version__ = "2.0.0"
__author__ = "YandeViewer Team"

from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    pass

# =============================================================================
# 核心组件导入
# =============================================================================

try:
    from .session import SESSION, SessionManager
except ImportError as e:
    raise ImportError(f"无法导入 session 模块: {e}") from e

try:
    from .event_bus import (
        EVENT_BUS,
        Event,
        EventBus,
        EventType,
        SubscriptionToken,
    )
except ImportError as e:
    raise ImportError(f"无法导入 event_bus 模块: {e}") from e

try:
    from .download_manager import (
        CancellationToken,
        DownloadManager,
        DownloadTask,
    )
except ImportError as e:
    raise ImportError(f"无法导入 download_manager 模块: {e}") from e

try:
    from .cache import LRUCache, MemoryAwareLRUCache
except ImportError as e:
    raise ImportError(f"无法导入 cache 模块: {e}") from e

try:
    from .preloader import PreloadResult, PreloadTask, TurboPreloader
except ImportError as e:
    raise ImportError(f"无法导入 preloader 模块: {e}") from e


__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    # 会话管理
    "SessionManager",
    "SESSION",
    # 事件系统
    "EventType",
    "Event",
    "EventBus",
    "EVENT_BUS",
    "SubscriptionToken",
    # 下载管理
    "DownloadManager",
    "DownloadTask",
    "CancellationToken",
    # 缓存系统
    "LRUCache",
    "MemoryAwareLRUCache",
    # 预加载
    "TurboPreloader",
    "PreloadTask",
    "PreloadResult",
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


def get_status() -> Dict[str, bool]:
    """
    获取核心模块状态概览。

    Returns
    -------
    dict
        包含各组件激活状态的字典
    """
    return {
        "version": __version__,
        "session_active": SESSION is not None,
        "event_bus_active": EVENT_BUS is not None,
    }