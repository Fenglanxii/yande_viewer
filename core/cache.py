"""
LRU 缓存模块。

提供基于最近最少使用（LRU）策略的缓存实现：
- LRUCache: 基础 LRU 缓存
- MemoryAwareLRUCache: 支持内存大小限制的 LRU 缓存

线程安全性
----------
所有公共方法均使用 RLock 保证线程安全。

Example
-------
>>> cache = LRUCache(maxsize=100)
>>> cache.put("key", "value")
>>> cache.get("key")
'value'
"""

from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from typing import Any, Callable, Optional, Tuple


class LRUCache:
    """
    线程安全的 LRU 缓存。

    使用 OrderedDict 实现，通过组合模式提供缓存功能。

    Attributes
    ----------
    maxsize : int
        最大缓存容量

    Example
    -------
    >>> cache = LRUCache(maxsize=50)
    >>> cache.put("image_1", image_data)
    >>> result = cache.get("image_1")
    """

    def __init__(self, maxsize: int = 50) -> None:
        """
        初始化 LRU 缓存。

        Parameters
        ----------
        maxsize : int
            最大缓存容量，默认为 50
        """
        if maxsize < 1:
            raise ValueError(f"maxsize 必须 >= 1，当前值: {maxsize}")

        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    @property
    def lock(self) -> threading.RLock:
        """获取内部锁对象，供外部同步使用。"""
        return self._lock

    @property
    def cache(self) -> OrderedDict:
        """获取内部缓存字典，供外部遍历使用。"""
        return self._cache

    @property
    def maxsize(self) -> int:
        """获取最大容量。"""
        return self._maxsize

    @maxsize.setter
    def maxsize(self, value: int) -> None:
        """设置最大容量并淘汰超出项。"""
        with self._lock:
            self._maxsize = max(1, value)
            while len(self._cache) > self._maxsize:
                _, evicted = self._cache.popitem(last=False)
                self._safe_close(evicted)

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存项。

        命中时自动将项移动到末尾（最近使用）。

        Parameters
        ----------
        key : str
            缓存键

        Returns
        -------
        Any or None
            缓存值，不存在时返回 None
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        """
        添加缓存项。

        超过容量时淘汰最久未使用的项。

        Parameters
        ----------
        key : str
            缓存键
        value : Any
            缓存值
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value

            while len(self._cache) > self._maxsize:
                _, evicted = self._cache.popitem(last=False)
                self._safe_close(evicted)

    def get_or_load(
        self,
        key: str,
        loader: Callable[[], Any],
    ) -> Tuple[Any, bool]:
        """
        获取或加载缓存项（原子操作）。

        如果缓存中存在则直接返回，否则调用 loader 加载并缓存。

        Parameters
        ----------
        key : str
            缓存键
        loader : callable
            加载函数，签名为 () -> Any

        Returns
        -------
        tuple
            (value, from_cache)：值和是否来自缓存
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key], True

        # 在锁外执行加载（避免阻塞其他操作）
        value = loader()

        with self._lock:
            # Double-check（可能已被其他线程加载）
            if key in self._cache:
                self._safe_close(value)
                return self._cache[key], True

            self._cache[key] = value
            self._misses += 1

            while len(self._cache) > self._maxsize:
                _, evicted = self._cache.popitem(last=False)
                self._safe_close(evicted)

            return value, False

    @staticmethod
    def _safe_close(obj: Any) -> None:
        """安全关闭资源。"""
        if hasattr(obj, "close"):
            try:
                obj.close()
            except Exception:
                pass

    def has(self, key: str) -> bool:
        """
        检查键是否存在。

        Parameters
        ----------
        key : str
            缓存键

        Returns
        -------
        bool
            键是否存在
        """
        with self._lock:
            return key in self._cache

    def size(self) -> int:
        """
        获取当前缓存大小。

        Returns
        -------
        int
            缓存项数量
        """
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            for v in self._cache.values():
                self._safe_close(v)
            self._cache.clear()

    def stats(self) -> dict:
        """
        获取缓存统计信息。

        Returns
        -------
        dict
            包含 size, maxsize, hits, misses, hit_rate 的字典
        """
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0,
            }


class MemoryAwareLRUCache(LRUCache):
    """
    支持内存大小限制的 LRU 缓存。

    除了条目数量限制外，还可以设置内存使用上限。

    Attributes
    ----------
    max_memory_mb : float
        最大内存使用量（MB）

    Example
    -------
    >>> cache = MemoryAwareLRUCache(maxsize=100, max_memory_mb=500)
    >>> cache.put("large_image", image_data)
    """

    def __init__(
        self,
        maxsize: int = 50,
        max_memory_mb: float = 500,
        size_func: Optional[Callable[[Any], int]] = None,
    ) -> None:
        """
        初始化内存感知 LRU 缓存。

        Parameters
        ----------
        maxsize : int
            最大条目数量，默认为 50
        max_memory_mb : float
            最大内存使用量（MB），默认为 500
        size_func : callable, optional
            自定义大小计算函数，签名为 (obj) -> int
        """
        super().__init__(maxsize)
        self._max_memory = int(max_memory_mb * 1024 * 1024)
        self._current_memory = 0
        self._item_sizes: dict = {}
        self._size_func = size_func or self._default_size

    @staticmethod
    def _default_size(obj: Any) -> int:
        """估算对象内存占用（针对 PIL.Image 优化）。"""
        if hasattr(obj, "size") and hasattr(obj, "mode"):
            # PIL.Image: width * height * bytes_per_pixel
            w, h = obj.size
            bpp = {"1": 1, "L": 1, "P": 1, "RGB": 3, "RGBA": 4}.get(obj.mode, 4)
            return w * h * bpp
        return sys.getsizeof(obj)

    def put(self, key: str, value: Any) -> None:
        """
        添加缓存项（同时检查数量和内存限制）。

        Parameters
        ----------
        key : str
            缓存键
        value : Any
            缓存值
        """
        item_size = self._size_func(value)

        with self._lock:
            # 如果已存在，先减去旧值大小
            if key in self._cache:
                self._current_memory -= self._item_sizes.get(key, 0)
                self._cache.move_to_end(key)

            self._cache[key] = value
            self._item_sizes[key] = item_size
            self._current_memory += item_size

            # 淘汰策略：数量或内存超限
            while (
                len(self._cache) > self._maxsize
                or self._current_memory > self._max_memory
            ):
                if not self._cache:
                    break
                evicted_key, evicted_val = self._cache.popitem(last=False)
                self._current_memory -= self._item_sizes.pop(evicted_key, 0)
                self._safe_close(evicted_val)

    def stats(self) -> dict:
        """
        获取扩展的缓存统计信息。

        Returns
        -------
        dict
            包含内存使用信息的扩展统计字典
        """
        base = super().stats()
        with self._lock:
            base.update(
                {
                    "memory_mb": self._current_memory / 1024 / 1024,
                    "max_memory_mb": self._max_memory / 1024 / 1024,
                }
            )
        return base