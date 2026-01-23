#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片预加载器模块。

本模块提供基于优先级的图片预加载功能，用于提升用户浏览体验。

主要特性:
    - 优先级队列: 根据用户浏览行为动态调整加载顺序
    - 自动重试: 网络失败时自动延迟重试
    - 批量加载: 支持按页批量预加载
    - 内存管理: 与 LRU 缓存协作避免内存溢出

线程安全:
    所有公共方法均为线程安全

示例:
    >>> from core.cache import LRUCache
    >>> cache = LRUCache(maxsize=100)
    >>> preloader = TurboPreloader(cache)
    >>> preloader.preload_immediate([post1, post2])  # 高优先级
    >>> preloader.preload_batch([post3, post4, ...])  # 低优先级
    >>> preloader.shutdown()

License:
    MIT License

Author:
    YandeViewer Team
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
)

if TYPE_CHECKING:
    from PIL import Image

    from core.cache import LRUCache

__all__ = [
    "PreloadTask",
    "PreloadResult",
    "TurboPreloader",
]

logger = logging.getLogger("YandeViewer.Preloader")


# ============================================================
# 数据类
# ============================================================


@dataclass(order=True)
class PreloadTask:
    """预加载任务数据类。

    支持基于优先级的排序，可直接用于 ``heapq`` 操作。

    Attributes:
        priority: 优先级数值（越小优先级越高）。
        post_id: 帖子唯一标识符。
        post: 帖子完整数据。
        created_at: 任务创建时间戳。

    Note:
        ``order=True`` 使任务可以直接用于堆操作，按 priority 字段排序。
        其他字段设置 ``compare=False`` 不参与比较。
    """

    priority: int
    post_id: str = field(compare=False)
    post: Dict[str, Any] = field(compare=False)
    created_at: float = field(default_factory=time.time, compare=False)


@dataclass
class PreloadResult:
    """预加载结果数据类。

    Attributes:
        post_id: 帖子唯一标识符。
        success: 是否成功加载。
        error: 错误信息（如有）。
        retry_count: 已重试次数。
        load_time: 加载耗时（秒）。
    """

    post_id: str
    success: bool
    error: Optional[str] = None
    retry_count: int = 0
    load_time: float = 0.0


# ============================================================
# 预加载器
# ============================================================


class TurboPreloader:
    """高速图片预加载器。

    支持三级优先级的图片预加载，可根据用户浏览行为动态调整
    任务优先级。

    优先级常量:
        - ``PRIORITY_IMMEDIATE``: 最高优先级（当前浏览附近）
        - ``PRIORITY_NEXT_PAGE``: 中等优先级（下一页）
        - ``PRIORITY_PREFETCH``: 低优先级（后台预取）

    Attributes:
        PRIORITY_IMMEDIATE: 最高优先级常量值。
        PRIORITY_NEXT_PAGE: 中等优先级常量值。
        PRIORITY_PREFETCH: 低优先级常量值。
        DEFAULT_MAX_RETRIES: 默认最大重试次数。
        DEFAULT_RETRY_DELAY: 默认重试延迟（秒）。
        DEFAULT_WORKERS: 默认工作线程数。
        DEFAULT_TIMEOUT: 默认请求超时（秒）。

    示例:
        >>> preloader = TurboPreloader(cache, on_failed=handle_failure)
        >>> preloader.preload_immediate(posts[:5])
        >>> preloader.boost_priority("12345")  # 提升特定任务优先级
    """

    # 优先级常量
    PRIORITY_IMMEDIATE: int = 0
    PRIORITY_NEXT_PAGE: int = 10
    PRIORITY_PREFETCH: int = 50

    # 默认配置
    DEFAULT_MAX_RETRIES: int = 2
    DEFAULT_RETRY_DELAY: float = 1.0
    DEFAULT_WORKERS: int = 8
    DEFAULT_TIMEOUT: int = 15

    def __init__(
        self,
        cache: "LRUCache",
        on_failed: Optional[Callable[[PreloadResult], None]] = None,
        max_workers: int = DEFAULT_WORKERS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化预加载器。

        Args:
            cache: LRU 缓存实例，用于存储预加载的图片。
            on_failed: 加载失败时的回调函数。
            max_workers: 最大工作线程数。
            max_retries: 最大重试次数。
            retry_delay: 重试延迟时间（秒）。
            timeout: HTTP 请求超时时间（秒）。

        Raises:
            ValueError: 如果 cache 为 None。
            ValueError: 如果 max_workers 小于 1。
        """
        if cache is None:
            raise ValueError("cache 参数不能为 None")
        if max_workers < 1:
            raise ValueError(f"max_workers 必须 >= 1，收到 {max_workers}")

        self._cache = cache
        self._on_failed = on_failed
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._timeout = timeout

        # 重试计数: post_id -> retry_count
        self._retry_counts: Dict[str, int] = {}

        # 线程池
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="Preload",
        )

        # 优先级队列和任务跟踪
        self._queue: List[PreloadTask] = []
        self._pending: Dict[str, PreloadTask] = {}
        self._in_progress: Set[str] = set()

        # 同步原语
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._shutdown = threading.Event()

        # 统计信息
        self._stats: Dict[str, int] = {
            "total_loaded": 0,
            "total_failed": 0,
            "total_skipped": 0,
            "total_retries": 0,
        }

        # 延迟初始化的会话
        self._session: Optional[Any] = None

        # 启动调度线程
        self._scheduler = threading.Thread(
            target=self._schedule_loop,
            daemon=True,
            name="PreloadScheduler",
        )
        self._scheduler.start()

        logger.debug(
            "TurboPreloader 已初始化: workers=%d, retries=%d",
            max_workers,
            max_retries,
        )

    def _ensure_session(self) -> Any:
        """确保 HTTP 会话已初始化。

        Returns:
            会话管理器实例。
        """
        if self._session is None:
            from core.session import SESSION

            self._session = SESSION
        return self._session

    # ===== 公共 API =====

    def preload_immediate(self, posts: List[Dict[str, Any]]) -> int:
        """立即预加载（最高优先级）。

        用于当前浏览位置附近的图片，将以最高优先级加载。

        Args:
            posts: 帖子数据列表。

        Returns:
            成功加入队列的任务数。
        """
        return self._enqueue_batch(posts, self.PRIORITY_IMMEDIATE)

    def preload_next_page(self, posts: List[Dict[str, Any]]) -> int:
        """预加载下一页（中等优先级）。

        Args:
            posts: 帖子数据列表。

        Returns:
            成功加入队列的任务数。
        """
        return self._enqueue_batch(posts, self.PRIORITY_NEXT_PAGE)

    def preload_batch(self, posts: List[Dict[str, Any]]) -> int:
        """后台批量预加载（低优先级）。

        Args:
            posts: 帖子数据列表。

        Returns:
            成功加入队列的任务数。
        """
        return self._enqueue_batch(posts, self.PRIORITY_PREFETCH)

    def boost_priority(self, post_id: str) -> bool:
        """提升指定任务的优先级。

        当用户即将查看某图片时调用此方法，将该任务提升到最高优先级。

        Args:
            post_id: 帖子唯一标识符。

        Returns:
            如果成功提升返回 True，任务不在队列中返回 False。
        """
        if not post_id:
            return False

        with self._lock:
            task = self._pending.get(post_id)
            if task is None:
                return False

            if task.priority > self.PRIORITY_IMMEDIATE:
                task.priority = self.PRIORITY_IMMEDIATE
                heapq.heapify(self._queue)
                logger.debug("已提升任务 %s 的优先级", post_id)
                return True

            return False

    def cancel(self, post_id: str) -> bool:
        """取消指定的预加载任务。

        Args:
            post_id: 帖子唯一标识符。

        Returns:
            如果成功取消返回 True，任务不存在返回 False。
        """
        if not post_id:
            return False

        with self._lock:
            if post_id in self._pending:
                del self._pending[post_id]
                # 重建队列（移除已取消的任务）
                self._queue = [
                    t for t in self._queue if t.post_id != post_id
                ]
                heapq.heapify(self._queue)
                return True
            return False

    def clear_pending(self) -> int:
        """清除所有等待中的任务。

        Returns:
            清除的任务数量。
        """
        with self._lock:
            count = len(self._pending)
            self._queue.clear()
            self._pending.clear()
            return count

    # ===== 内部方法 =====

    def _enqueue_batch(
        self,
        posts: List[Dict[str, Any]],
        priority: int,
    ) -> int:
        """添加批量任务到队列。

        Args:
            posts: 帖子数据列表。
            priority: 任务优先级。

        Returns:
            成功加入队列的任务数。
        """
        if not posts:
            return 0

        added = 0
        with self._lock:
            for post in posts:
                post_id = str(post.get("id", ""))
                if not post_id:
                    continue

                # 跳过已缓存、已在队列或正在加载的任务
                if self._cache.has(post_id):
                    self._stats["total_skipped"] += 1
                    continue

                if post_id in self._pending or post_id in self._in_progress:
                    continue

                task = PreloadTask(
                    priority=priority,
                    post_id=post_id,
                    post=post.copy(),  # 复制以避免外部修改
                )
                heapq.heappush(self._queue, task)
                self._pending[post_id] = task
                added += 1

            if added > 0:
                self._condition.notify_all()

        return added

    def _schedule_loop(self) -> None:
        """调度循环：从优先级队列取出任务并执行。"""
        while not self._shutdown.is_set():
            task: Optional[PreloadTask] = None

            with self._condition:
                # 等待任务可用
                while not self._queue and not self._shutdown.is_set():
                    self._condition.wait(timeout=1.0)

                if self._shutdown.is_set():
                    break

                if self._queue:
                    task = heapq.heappop(self._queue)
                    self._in_progress.add(task.post_id)

            if task is not None:
                # 在锁外提交任务以避免阻塞
                self._executor.submit(self._load_one, task)

    def _load_one(self, task: PreloadTask) -> None:
        """加载单张图片。

        Args:
            task: 预加载任务。
        """
        post_id = task.post_id
        start_time = time.time()
        retry_count = self._retry_counts.get(post_id, 0)

        try:
            # 再次检查缓存（可能已被其他途径加载）
            if self._cache.has(post_id):
                return

            # 获取图片 URL
            url = task.post.get("sample_url") or task.post.get("preview_url")
            if not url:
                raise ValueError("无可用的图片 URL")

            # 发起 HTTP 请求
            session = self._ensure_session()
            response = session.get(url, timeout=self._timeout)

            if response.status_code == 404:
                raise ValueError("资源不存在 (404)")
            if response.status_code != 200:
                raise IOError(f"HTTP 错误: {response.status_code}")

            # 加载并处理图片
            from PIL import Image

            with Image.open(BytesIO(response.content)) as img:
                # 限制图片尺寸
                if max(img.size) > 2000:
                    img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)

                # 缓存图片副本
                self._cache.put(post_id, img.copy())

            # 记录成功
            load_time = time.time() - start_time
            self._retry_counts.pop(post_id, None)

            with self._lock:
                self._stats["total_loaded"] += 1

            logger.debug("预加载完成 %s，耗时 %.2fs", post_id, load_time)

        except Exception as e:
            error_msg = str(e)
            load_time = time.time() - start_time

            logger.debug(
                "预加载失败 %s (第 %d 次): %s",
                post_id,
                retry_count + 1,
                error_msg,
            )

            # 判断是否需要重试
            is_permanent_error = isinstance(e, ValueError)
            should_retry = (
                retry_count < self._max_retries and not is_permanent_error
            )

            if should_retry:
                with self._lock:
                    self._retry_counts[post_id] = retry_count + 1
                    self._stats["total_retries"] += 1
                self._schedule_retry(task)
            else:
                # 记录最终失败
                with self._lock:
                    self._stats["total_failed"] += 1
                    self._retry_counts.pop(post_id, None)

                # 回调通知
                if self._on_failed is not None:
                    result = PreloadResult(
                        post_id=post_id,
                        success=False,
                        error=error_msg,
                        retry_count=retry_count,
                        load_time=load_time,
                    )
                    self._safe_callback(self._on_failed, result)

        finally:
            with self._lock:
                self._pending.pop(post_id, None)
                self._in_progress.discard(post_id)

    def _schedule_retry(self, task: PreloadTask) -> None:
        """调度延迟重试。

        Args:
            task: 需要重试的任务。
        """

        def delayed_retry() -> None:
            if self._shutdown.is_set():
                return

            time.sleep(self._retry_delay)

            with self._lock:
                if self._shutdown.is_set():
                    return
                if task.post_id in self._pending:
                    return  # 已重新加入队列

                # 降低优先级后重新入队
                task.priority = self.PRIORITY_PREFETCH + 10
                heapq.heappush(self._queue, task)
                self._pending[task.post_id] = task
                self._condition.notify()

        threading.Thread(target=delayed_retry, daemon=True).start()

    def _safe_callback(
        self,
        callback: Callable[..., Any],
        *args: Any,
    ) -> None:
        """安全执行回调函数。

        Args:
            callback: 回调函数。
            *args: 回调参数。
        """
        try:
            callback(*args)
        except Exception as e:
            logger.warning("回调执行错误: %s", e)

    # ===== 统计信息 =====

    def get_stats(self) -> Dict[str, Any]:
        """获取预加载器统计信息。

        Returns:
            包含以下键的字典:
                - queue_size: 队列中等待的任务数
                - pending: 待处理任务数
                - in_progress: 正在加载的任务数
                - retry_count: 等待重试的任务数
                - cached: 缓存中的图片数
                - total_loaded: 成功加载总数
                - total_failed: 失败总数
                - total_skipped: 跳过总数
                - total_retries: 重试总数
        """
        with self._lock:
            return {
                "queue_size": len(self._queue),
                "pending": len(self._pending),
                "in_progress": len(self._in_progress),
                "retry_count": len(self._retry_counts),
                "cached": self._cache.size(),
                **self._stats.copy(),
            }

    def get_failed_list(self) -> List[str]:
        """获取当前等待重试的帖子 ID 列表。

        Returns:
            等待重试的帖子 ID 列表。
        """
        with self._lock:
            return list(self._retry_counts.keys())

    # ===== 生命周期管理 =====

    def shutdown(self, wait: bool = False) -> None:
        """关闭预加载器。

        Args:
            wait: 是否等待当前任务完成。
        """
        logger.info("正在关闭 TurboPreloader...")

        self._shutdown.set()

        with self._condition:
            self._condition.notify_all()

        self._executor.shutdown(wait=wait, cancel_futures=True)

        logger.info("TurboPreloader 已关闭")

    def __repr__(self) -> str:
        """返回预加载器的字符串表示。"""
        stats = self.get_stats()
        return (
            f"<TurboPreloader queue={stats['queue_size']} "
            f"pending={stats['pending']} loaded={stats['total_loaded']}>"
        )