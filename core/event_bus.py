#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事件总线模块。

本模块实现了一个线程安全的发布-订阅模式事件系统，用于应用程序
内部组件之间的松耦合通信。

主要特性:
    - 类型安全的事件定义
    - 基于令牌的订阅生命周期管理
    - 按所有者批量取消订阅
    - 线程安全的同步发布机制

设计模式:
    Observer + Token-based Subscription

示例:
    >>> def handler(event: Event) -> None:
    ...     print(f"收到事件: {event.data}")
    >>>
    >>> token = EVENT_BUS.subscribe(EventType.IMAGE_LOADED, handler, owner="viewer")
    >>> EVENT_BUS.publish(Event(EventType.IMAGE_LOADED, {"id": 123}))
    >>> token.dispose()  # 显式取消订阅

License:
    MIT License

Author:
    YandeViewer Team
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
)

__all__ = [
    "EventType",
    "Event",
    "SubscriptionToken",
    "EventBus",
    "EVENT_BUS",
]

logger = logging.getLogger("YandeViewer.EventBus")


# ============================================================
# 事件类型枚举
# ============================================================


class EventType(Enum):
    """事件类型枚举。

    使用 ``auto()`` 自动分配值，避免手动管理数值冲突。

    分类:
        - 图片相关: ``IMAGE_*``
        - 下载相关: ``DOWNLOAD_*``
        - 界面相关: ``POST_*``, ``MODE_*``, ``WINDOW_*``, ``FULLSCREEN_*``
        - 系统相关: ``CACHE_*``, ``FILTER_*``, ``APP_*``

    示例:
        >>> event_type = EventType.IMAGE_LOADED
        >>> print(event_type.name)
        IMAGE_LOADED
    """

    # 图片事件
    IMAGE_LOADED = auto()
    IMAGE_LOAD_FAILED = auto()
    IMAGE_PRELOADED = auto()

    # 下载事件
    DOWNLOAD_STARTED = auto()
    DOWNLOAD_PROGRESS = auto()
    DOWNLOAD_COMPLETED = auto()
    DOWNLOAD_FAILED = auto()
    DOWNLOAD_CANCELLED = auto()

    # 界面事件
    POST_CHANGED = auto()
    MODE_CHANGED = auto()
    WINDOW_RESIZED = auto()
    FULLSCREEN_TOGGLED = auto()
    VIEW_CHANGED = auto()

    # 系统事件
    CACHE_UPDATED = auto()
    FILTER_CHANGED = auto()
    SETTINGS_CHANGED = auto()
    APP_SHUTDOWN = auto()


# ============================================================
# 事件数据类
# ============================================================


@dataclass(frozen=True)
class Event:
    """不可变事件数据类。

    封装事件的所有相关信息，使用 ``frozen=True`` 确保事件对象
    在传播过程中不可被修改。

    Attributes:
        type: 事件类型。
        data: 事件携带的数据字典。
        timestamp: 事件创建的时间戳（自动生成）。
        event_id: 事件的唯一标识符（自动生成）。

    示例:
        >>> event = Event(EventType.IMAGE_LOADED, {"id": 123, "path": "/img.jpg"})
        >>> print(event.type.name)
        IMAGE_LOADED
        >>> print(event.data["id"])
        123
    """

    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __repr__(self) -> str:
        """返回事件的字符串表示。"""
        return f"Event({self.type.name}, id={self.event_id})"


# ============================================================
# 订阅令牌
# ============================================================


class SubscriptionToken:
    """订阅令牌类。

    代表一个事件订阅的句柄，提供显式的生命周期管理功能。
    支持上下文管理器协议，可用于自动取消订阅。

    Attributes:
        token_id: 订阅的唯一标识符。
        event_type: 订阅的事件类型。
        owner: 订阅者的标识。
        is_active: 订阅是否仍然有效。

    示例:
        >>> token = EVENT_BUS.subscribe(EventType.IMAGE_LOADED, handler)
        >>> # ... 使用中 ...
        >>> token.dispose()  # 取消订阅
        >>> print(token.is_active)
        False

        >>> # 使用上下文管理器
        >>> with EVENT_BUS.subscribe(EventType.IMAGE_LOADED, handler) as token:
        ...     pass  # 退出时自动取消订阅
    """

    __slots__ = (
        "token_id",
        "event_type",
        "owner",
        "_bus_ref",
        "_active",
        "_lock",
    )

    def __init__(
        self,
        token_id: str,
        event_type: EventType,
        owner: Optional[str],
        bus: "EventBus",
    ) -> None:
        """初始化订阅令牌。

        Args:
            token_id: 订阅的唯一标识符。
            event_type: 订阅的事件类型。
            owner: 订阅者的标识。
            bus: 事件总线实例。
        """
        self.token_id = token_id
        self.event_type = event_type
        self.owner = owner
        self._bus_ref: weakref.ref[EventBus] = weakref.ref(bus)
        self._active = True
        self._lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        """检查订阅是否仍然有效。

        Returns:
            如果订阅仍然有效返回 True，否则返回 False。
        """
        with self._lock:
            return self._active

    def dispose(self) -> bool:
        """取消此订阅。

        此方法是幂等的，多次调用是安全的。

        Returns:
            首次成功取消返回 True，重复调用返回 False。
        """
        with self._lock:
            if not self._active:
                return False
            self._active = False

        bus = self._bus_ref()
        if bus is not None:
            bus._remove_subscription(self.token_id, self.event_type)

        return True

    def __enter__(self) -> "SubscriptionToken":
        """进入上下文管理器。"""
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """退出上下文管理器，自动取消订阅。"""
        self.dispose()

    def __repr__(self) -> str:
        """返回令牌的字符串表示。"""
        status = "active" if self.is_active else "disposed"
        return f"<SubscriptionToken {self.token_id[:8]} {self.event_type.name} {status}>"


# ============================================================
# 内部订阅记录
# ============================================================


@dataclass
class _Subscription:
    """内部订阅记录。

    Attributes:
        token_id: 订阅的唯一标识符。
        callback: 事件回调函数。
        owner: 订阅者的标识。
        created_at: 订阅创建时间。
        call_count: 回调调用计数（用于调试）。
    """

    token_id: str
    callback: Callable[[Event], None]
    owner: Optional[str]
    created_at: float = field(default_factory=time.time)
    call_count: int = 0


# ============================================================
# 事件总线
# ============================================================


class EventBus:
    """事件总线类。

    实现发布-订阅模式，作为系统组件间的通信中枢。使用双重检查
    锁定确保全局唯一实例（单例模式）。

    主要特性:
        - 线程安全的订阅/发布操作
        - 基于令牌的订阅管理
        - 按所有者批量取消订阅
        - 错误隔离（单个处理器异常不影响其他处理器）

    示例:
        >>> def on_loaded(event: Event) -> None:
        ...     print(f"已加载: {event.data}")
        >>>
        >>> with EVENT_BUS.subscribe(EventType.IMAGE_LOADED, on_loaded) as token:
        ...     # 订阅在此作用域内有效
        ...     pass  # 退出时自动取消订阅
    """

    _instance: Optional["EventBus"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "EventBus":
        """双重检查锁定实现单例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init()
                    cls._instance = instance
        return cls._instance

    def _init(self) -> None:
        """初始化事件总线内部状态。"""
        # 事件类型 -> {token_id -> _Subscription}
        self._subscribers: Dict[EventType, Dict[str, _Subscription]] = {}
        # owner -> Set[token_id]
        self._owner_tokens: Dict[str, Set[str]] = {}
        # 统计信息
        self._stats: Dict[str, int] = {
            "total_published": 0,
            "total_delivered": 0,
            "total_errors": 0,
        }
        self._lock = threading.RLock()

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], None],
        owner: Optional[str] = None,
    ) -> SubscriptionToken:
        """订阅事件。

        Args:
            event_type: 要订阅的事件类型。
            callback: 事件回调函数，签名为 ``(Event) -> None``。
            owner: 可选的订阅者标识，用于批量取消订阅。

        Returns:
            订阅令牌，用于管理订阅生命周期。

        Raises:
            TypeError: 如果 ``event_type`` 不是 EventType 实例。
            TypeError: 如果 ``callback`` 不可调用。

        示例:
            >>> def handler(event: Event) -> None:
            ...     print(f"收到: {event.data}")
            >>> token = EVENT_BUS.subscribe(
            ...     EventType.POST_CHANGED, handler, owner="viewer"
            ... )
        """
        if not isinstance(event_type, EventType):
            raise TypeError(
                f"event_type 必须是 EventType 实例，收到 {type(event_type).__name__}"
            )
        if not callable(callback):
            raise TypeError(
                f"callback 必须是可调用对象，收到 {type(callback).__name__}"
            )

        token_id = uuid.uuid4().hex
        subscription = _Subscription(
            token_id=token_id,
            callback=callback,
            owner=owner,
        )

        with self._lock:
            # 注册到事件类型映射
            if event_type not in self._subscribers:
                self._subscribers[event_type] = {}
            self._subscribers[event_type][token_id] = subscription

            # 注册到 owner 映射
            if owner is not None:
                if owner not in self._owner_tokens:
                    self._owner_tokens[owner] = set()
                self._owner_tokens[owner].add(token_id)

        logger.debug(
            "已订阅 %s [token=%s, owner=%s]",
            event_type.name,
            token_id[:8],
            owner,
        )

        return SubscriptionToken(token_id, event_type, owner, self)

    def _remove_subscription(
        self, token_id: str, event_type: EventType
    ) -> bool:
        """移除订阅（内部方法）。

        Args:
            token_id: 要移除的订阅标识符。
            event_type: 订阅的事件类型。

        Returns:
            如果成功移除返回 True，否则返回 False。
        """
        with self._lock:
            subs = self._subscribers.get(event_type)
            if subs is None:
                return False

            subscription = subs.pop(token_id, None)
            if subscription is None:
                return False

            # 从 owner 映射中移除
            if subscription.owner:
                owner_set = self._owner_tokens.get(subscription.owner)
                if owner_set:
                    owner_set.discard(token_id)
                    if not owner_set:
                        del self._owner_tokens[subscription.owner]

            logger.debug("已取消订阅 [token=%s]", token_id[:8])
            return True

    def unsubscribe_all(self, owner: str) -> int:
        """取消指定所有者的所有订阅。

        Args:
            owner: 订阅者标识。

        Returns:
            成功取消的订阅数量。

        示例:
            >>> # 组件销毁时取消所有订阅
            >>> count = EVENT_BUS.unsubscribe_all("main_window")
            >>> print(f"已取消 {count} 个订阅")
        """
        if not owner:
            return 0

        removed_count = 0

        with self._lock:
            token_ids = self._owner_tokens.pop(owner, set())
            if not token_ids:
                return 0

            for subs in self._subscribers.values():
                for token_id in token_ids:
                    if subs.pop(token_id, None) is not None:
                        removed_count += 1

        if removed_count > 0:
            logger.debug(
                "已为 owner=%s 取消 %d 个订阅", owner, removed_count
            )

        return removed_count

    def publish(self, event: Event) -> int:
        """同步发布事件。

        按订阅顺序依次调用所有回调函数。单个回调的异常不会影响
        其他回调的执行。

        Args:
            event: 要发布的事件对象。

        Returns:
            成功调用的回调数量。

        Raises:
            TypeError: 如果 ``event`` 不是 Event 实例。

        Note:
            此方法会阻塞直到所有回调执行完成。
        """
        if not isinstance(event, Event):
            raise TypeError(
                f"event 必须是 Event 实例，收到 {type(event).__name__}"
            )

        with self._lock:
            subs = self._subscribers.get(event.type, {})
            subscriptions = list(subs.values())
            self._stats["total_published"] += 1

        if not subscriptions:
            return 0

        delivered = 0
        for sub in subscriptions:
            try:
                sub.callback(event)
                sub.call_count += 1
                delivered += 1
            except Exception as e:
                with self._lock:
                    self._stats["total_errors"] += 1
                logger.error(
                    "事件处理器错误 [%s, token=%s]: %s",
                    event.type.name,
                    sub.token_id[:8],
                    e,
                    exc_info=True,
                )

        with self._lock:
            self._stats["total_delivered"] += delivered

        return delivered

    def get_subscriber_count(
        self, event_type: Optional[EventType] = None
    ) -> int:
        """获取订阅者数量。

        Args:
            event_type: 指定事件类型。如果为 None，返回所有类型的总数。

        Returns:
            订阅者数量。
        """
        with self._lock:
            if event_type is not None:
                return len(self._subscribers.get(event_type, {}))
            return sum(len(subs) for subs in self._subscribers.values())

    def get_stats(self) -> Dict[str, Any]:
        """获取事件总线统计信息。

        Returns:
            包含以下键的字典:
                - total_published: 已发布事件总数
                - total_delivered: 已成功投递总数
                - total_errors: 错误总数
                - subscriber_count: 当前订阅者数量
                - event_types: 有订阅者的事件类型数量
                - owners: 已注册的所有者数量
        """
        with self._lock:
            return {
                **self._stats.copy(),
                "subscriber_count": self.get_subscriber_count(),
                "event_types": len(self._subscribers),
                "owners": len(self._owner_tokens),
            }

    def clear(self) -> int:
        """清除所有订阅。

        主要用于测试或重置事件总线状态。

        Returns:
            清除的订阅数量。
        """
        with self._lock:
            count = sum(len(subs) for subs in self._subscribers.values())
            self._subscribers.clear()
            self._owner_tokens.clear()
            logger.info("已清除 %d 个订阅", count)
            return count

    def __repr__(self) -> str:
        """返回事件总线的字符串表示。"""
        stats = self.get_stats()
        return (
            f"<EventBus subscribers={stats['subscriber_count']} "
            f"published={stats['total_published']}>"
        )


# ============================================================
# 全局实例
# ============================================================

#: 全局事件总线实例
EVENT_BUS = EventBus()