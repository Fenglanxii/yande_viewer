#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 会话管理模块。

本模块提供统一的 HTTP 会话管理功能，封装 requests.Session
并添加自动重试、连接池等企业级特性。

主要特性:
    - 自动重试: 可配置的重试策略，支持指数退避
    - 连接池: 复用 TCP 连接以提高性能
    - SSL 验证: 默认启用证书验证
    - 统一请求头: 预配置 User-Agent 和 Accept 头

线程安全:
    所有方法均为线程安全，可在多线程环境中使用

单例模式:
    使用双重检查锁定确保全局唯一实例

示例:
    >>> from core.session import SESSION
    >>> response = SESSION.get("https://api.example.com/data")
    >>> print(response.json())

License:
    MIT License

Author:
    YandeViewer Team
"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    import requests

__all__ = [
    "SessionConfig",
    "SessionManager",
    "SESSION",
]

logger = logging.getLogger("YandeViewer.Session")


# ============================================================
# 会话配置
# ============================================================


class SessionConfig:
    """会话配置常量类。

    定义 HTTP 会话的各项配置参数。

    Attributes:
        MAX_RETRIES: 最大重试次数。
        BACKOFF_FACTOR: 重试退避因子。
        RETRY_STATUS_CODES: 触发重试的 HTTP 状态码集合。
        RETRY_METHODS: 允许重试的 HTTP 方法集合。
        POOL_CONNECTIONS: 连接池保持的连接数。
        POOL_MAXSIZE: 连接池最大连接数。
        POOL_BLOCK: 连接池满时是否阻塞。
        USER_AGENT: 默认 User-Agent 字符串。
        DEFAULT_TIMEOUT: 默认请求超时时间（秒）。
    """

    # 重试配置
    MAX_RETRIES: int = 5
    BACKOFF_FACTOR: float = 0.5
    RETRY_STATUS_CODES: frozenset = frozenset([429, 500, 502, 503, 504])
    RETRY_METHODS: frozenset = frozenset(["GET", "HEAD", "OPTIONS"])

    # 连接池配置
    POOL_CONNECTIONS: int = 20
    POOL_MAXSIZE: int = 50
    POOL_BLOCK: bool = False

    # 请求头配置
    USER_AGENT: str = (
        "Mozilla/5.0 (YandeViewer/2.0; +https://github.com/yandeviewer)"
    )

    # 超时配置
    DEFAULT_TIMEOUT: float = 30.0


# ============================================================
# 会话管理器
# ============================================================


class SessionManager:
    """统一的 HTTP 会话管理器。

    封装 requests.Session，提供自动重试、连接复用等特性。
    使用双重检查锁定实现单例模式，确保全局唯一实例。

    主要特性:
        - 自动重试: 对特定状态码和网络错误自动重试
        - 连接复用: 使用连接池提高网络性能
        - 线程安全: 可在多线程环境中安全使用
        - 资源管理: 程序退出时自动关闭连接

    示例:
        >>> session = SessionManager()  # 获取单例
        >>> response = session.get("https://example.com", timeout=10)

        >>> # 配置代理
        >>> session.set_proxy(
        ...     http_proxy="http://127.0.0.1:7890",
        ...     https_proxy="http://127.0.0.1:7890",
        ... )
    """

    _instance: Optional["SessionManager"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "SessionManager":
        """双重检查锁定实现单例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init()
                    cls._instance = instance
        return cls._instance

    def _init(self) -> None:
        """初始化会话管理器内部状态。"""
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        self._session = requests.Session()
        self._lock = threading.RLock()
        self._closed = False

        # 配置重试策略
        retry_strategy = Retry(
            total=SessionConfig.MAX_RETRIES,
            backoff_factor=SessionConfig.BACKOFF_FACTOR,
            status_forcelist=list(SessionConfig.RETRY_STATUS_CODES),
            allowed_methods=list(SessionConfig.RETRY_METHODS),
            raise_on_status=False,
            respect_retry_after_header=True,
        )

        # 配置 HTTP 适配器
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=SessionConfig.POOL_CONNECTIONS,
            pool_maxsize=SessionConfig.POOL_MAXSIZE,
            pool_block=SessionConfig.POOL_BLOCK,
        )

        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # 设置默认请求头
        self._session.headers.update(
            {
                "User-Agent": SessionConfig.USER_AGENT,
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )

        # 注册程序退出时的清理回调
        atexit.register(self._cleanup)

        logger.debug("SessionManager 已初始化")

    @property
    def session(self) -> "requests.Session":
        """获取底层 requests.Session 实例。

        Warning:
            直接操作底层会话可能绕过本管理器的线程安全保护，
            请谨慎使用。

        Returns:
            底层的 requests.Session 实例。
        """
        return self._session

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        verify: bool = True,
        **kwargs: Any,
    ) -> "requests.Response":
        """发送 GET 请求。

        Args:
            url: 请求目标 URL。
            params: URL 查询参数。
            headers: 额外的请求头。
            timeout: 超时时间（秒），默认使用配置值。
            verify: 是否验证 SSL 证书。
            **kwargs: 传递给 requests.get 的其他参数。

        Returns:
            HTTP 响应对象。

        Raises:
            ValueError: 如果会话已关闭。
            requests.RequestException: 请求失败时。
        """
        self._check_closed()

        with self._lock:
            return self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout or SessionConfig.DEFAULT_TIMEOUT,
                verify=verify,
                **kwargs,
            )

    def post(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        verify: bool = True,
        **kwargs: Any,
    ) -> "requests.Response":
        """发送 POST 请求。

        Args:
            url: 请求目标 URL。
            data: 表单数据。
            json: JSON 数据（会自动序列化）。
            headers: 额外的请求头。
            timeout: 超时时间（秒）。
            verify: 是否验证 SSL 证书。
            **kwargs: 传递给 requests.post 的其他参数。

        Returns:
            HTTP 响应对象。

        Raises:
            ValueError: 如果会话已关闭。
            requests.RequestException: 请求失败时。
        """
        self._check_closed()

        with self._lock:
            return self._session.post(
                url,
                data=data,
                json=json,
                headers=headers,
                timeout=timeout or SessionConfig.DEFAULT_TIMEOUT,
                verify=verify,
                **kwargs,
            )

    def head(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        verify: bool = True,
        **kwargs: Any,
    ) -> "requests.Response":
        """发送 HEAD 请求。

        Args:
            url: 请求目标 URL。
            headers: 额外的请求头。
            timeout: 超时时间（秒）。
            verify: 是否验证 SSL 证书。
            **kwargs: 传递给 requests.head 的其他参数。

        Returns:
            HTTP 响应对象。

        Raises:
            ValueError: 如果会话已关闭。
        """
        self._check_closed()

        with self._lock:
            return self._session.head(
                url,
                headers=headers,
                timeout=timeout or SessionConfig.DEFAULT_TIMEOUT,
                verify=verify,
                **kwargs,
            )

    def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> "requests.Response":
        """发送通用 HTTP 请求。

        Args:
            method: HTTP 方法（GET、POST、PUT、DELETE 等）。
            url: 请求目标 URL。
            **kwargs: 传递给 requests.request 的其他参数。

        Returns:
            HTTP 响应对象。

        Raises:
            ValueError: 如果会话已关闭。
        """
        self._check_closed()

        kwargs.setdefault("timeout", SessionConfig.DEFAULT_TIMEOUT)
        kwargs.setdefault("verify", True)

        with self._lock:
            return self._session.request(method, url, **kwargs)

    def update_headers(self, headers: Dict[str, str]) -> None:
        """更新默认请求头。

        Args:
            headers: 要添加或更新的请求头字典。

        示例:
            >>> SESSION.update_headers({"Authorization": "Bearer token123"})
        """
        with self._lock:
            self._session.headers.update(headers)

    def set_proxy(
        self,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
    ) -> None:
        """设置代理服务器。

        Args:
            http_proxy: HTTP 代理地址（如 "http://127.0.0.1:7890"）。
            https_proxy: HTTPS 代理地址。

        示例:
            >>> SESSION.set_proxy(
            ...     http_proxy="http://127.0.0.1:7890",
            ...     https_proxy="http://127.0.0.1:7890",
            ... )

            >>> # 清除代理
            >>> SESSION.set_proxy()
        """
        with self._lock:
            proxies: Dict[str, str] = {}
            if http_proxy:
                proxies["http"] = http_proxy
            if https_proxy:
                proxies["https"] = https_proxy

            if proxies:
                self._session.proxies.update(proxies)
                logger.info("代理已配置: %s", proxies)
            else:
                self._session.proxies.clear()
                logger.info("代理已清除")

    def _check_closed(self) -> None:
        """检查会话是否已关闭。

        Raises:
            ValueError: 如果会话已关闭。
        """
        if self._closed:
            raise ValueError("SessionManager 已关闭")

    def _cleanup(self) -> None:
        """程序退出时的清理回调。"""
        self.close()

    def close(self) -> None:
        """关闭会话。

        关闭后所有请求方法将抛出 ValueError。
        此方法是幂等的，多次调用是安全的。
        """
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._session.close()
                    logger.debug("SessionManager 已关闭")
                except Exception as e:
                    logger.warning("关闭会话时出错: %s", e)

    def __repr__(self) -> str:
        """返回会话管理器的字符串表示。"""
        status = "closed" if self._closed else "active"
        return f"<SessionManager {status}>"


# ============================================================
# 全局实例
# ============================================================

#: 全局会话管理器实例
SESSION = SessionManager()