"""辅助工具函数模块。

提供文件操作、JSON 安全读写、进程/线程级文件锁、高 DPI 支持等通用工具。
所有函数均设计为跨平台兼容（Windows / macOS / Linux）。

主要功能:
    - file_lock: 跨进程文件锁
    - atomic_write: 原子文件写入
    - safe_json_load / safe_json_save: 线程安全的 JSON 操作
    - get_system_scale_factor: 获取系统 DPI 缩放
    - format_file_size: 格式化文件大小

Example:
    >>> from utils.helpers import safe_json_load, safe_json_save
    >>> data = safe_json_load("config.json", default=dict)
    >>> data["key"] = "value"
    >>> safe_json_save("config.json", data)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar, Union

logger = logging.getLogger(__name__)

# 泛型类型变量
T = TypeVar("T")

# 文件锁超时默认值（秒）
DEFAULT_LOCK_TIMEOUT: float = 10.0

# 原子写入最大重试次数
DEFAULT_MAX_RETRIES: int = 3

# DPI 相关全局状态
_dpi_initialized: bool = False
_dpi_scale_factor: float = 1.0

# 进程内文件锁缓存
_file_locks: dict[str, threading.RLock] = {}
_global_lock = threading.Lock()


# ============================================================
# 文件锁实现
# ============================================================


class FileLockError(Exception):
    """文件锁操作异常。"""

    pass


class FileLockTimeoutError(FileLockError):
    """获取文件锁超时异常。"""

    pass


@contextmanager
def file_lock(
    path: str | Path,
    exclusive: bool = True,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> Iterator[None]:
    """跨进程文件锁上下文管理器。

    提供进程内（threading.RLock）和跨进程（文件系统锁）两级锁定。

    Args:
        path: 需要锁定的文件路径。
        exclusive: True 表示排他锁（写锁），False 表示共享锁（读锁）。
        timeout: 获取锁的超时时间（秒）。

    Yields:
        无返回值，作为上下文管理器使用。

    Raises:
        FileLockTimeoutError: 在超时时间内无法获取锁。
        OSError: 文件系统操作错误。

    Example:
        >>> with file_lock("data.json", exclusive=True):
        ...     with open("data.json", "w") as f:
        ...         f.write('{"key": "value"}')

    Note:
        - 锁文件将创建在目标文件同目录下，命名为 "{filename}.lock"
        - Windows 使用 msvcrt.locking，Unix 使用 fcntl.flock
    """
    path_str = str(Path(path).resolve())

    # 获取或创建进程内锁
    with _global_lock:
        if path_str not in _file_locks:
            _file_locks[path_str] = threading.RLock()
        mem_lock = _file_locks[path_str]

    # 尝试获取内存锁
    acquired = mem_lock.acquire(timeout=timeout)
    if not acquired:
        raise FileLockTimeoutError(f"获取内存锁超时: {path}")

    lock_file = None
    lock_path = path_str + ".lock"

    try:
        # 确保锁文件目录存在
        lock_dir = Path(lock_path).parent
        lock_dir.mkdir(parents=True, exist_ok=True)

        # 创建锁文件（如果不存在）
        Path(lock_path).touch(exist_ok=True)

        # 获取跨进程锁
        lock_file = open(lock_path, "r+")

        if sys.platform == "win32":
            _acquire_windows_lock(lock_file, exclusive, timeout)
        else:
            _acquire_unix_lock(lock_file, exclusive, timeout)

        yield

    finally:
        # 释放文件锁
        if lock_file is not None:
            try:
                if sys.platform == "win32":
                    _release_windows_lock(lock_file)
                else:
                    _release_unix_lock(lock_file)
            except Exception as e:
                logger.debug("释放文件锁失败: %s", e)
            finally:
                try:
                    lock_file.close()
                except Exception:
                    pass

        # 释放内存锁
        mem_lock.release()


def _acquire_windows_lock(
    lock_file: Any,
    exclusive: bool,
    timeout: float,
) -> None:
    """Windows 平台文件锁获取。

    使用 msvcrt.locking 实现锁定。

    Args:
        lock_file: 打开的锁文件对象。
        exclusive: 是否排他锁（Windows 下忽略此参数）。
        timeout: 超时时间（秒）。

    Raises:
        FileLockTimeoutError: 获取锁超时。
    """
    import msvcrt

    start_time = time.monotonic()

    while True:
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                raise FileLockTimeoutError("获取 Windows 文件锁超时")
            time.sleep(0.05)


def _release_windows_lock(lock_file: Any) -> None:
    """Windows 平台文件锁释放。

    Args:
        lock_file: 打开的锁文件对象。
    """
    import msvcrt

    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


def _acquire_unix_lock(
    lock_file: Any,
    exclusive: bool,
    timeout: float,
) -> None:
    """Unix 平台文件锁获取。

    使用 fcntl.flock 实现锁定。

    Args:
        lock_file: 打开的锁文件对象。
        exclusive: True 为排他锁，False 为共享锁。
        timeout: 超时时间（秒）。

    Raises:
        FileLockTimeoutError: 获取锁超时。
    """
    import fcntl

    lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    start_time = time.monotonic()

    while True:
        try:
            fcntl.flock(lock_file.fileno(), lock_type | fcntl.LOCK_NB)
            return
        except OSError:
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                raise FileLockTimeoutError("获取 Unix 文件锁超时")
            time.sleep(0.05)


def _release_unix_lock(lock_file: Any) -> None:
    """Unix 平台文件锁释放。

    Args:
        lock_file: 打开的锁文件对象。
    """
    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


# ============================================================
# 原子写入
# ============================================================


def atomic_write(
    path: str | Path,
    data: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    encoding: str = "utf-8",
) -> None:
    """原子写入文件。

    通过写入临时文件后重命名的方式，确保写入操作的原子性。
    即使在写入过程中发生错误，也不会损坏原文件。

    Args:
        path: 目标文件路径。
        data: 要写入的字符串内容。
        max_retries: 替换操作的最大重试次数（Windows 可能需要重试）。
        encoding: 文件编码。

    Raises:
        OSError: 写入或替换操作失败。
        IOError: 写入操作失败。

    Example:
        >>> atomic_write("config.json", '{"version": 1}')

    Note:
        - 临时文件命名格式: .{filename}.{pid}.{thread_id}.tmp
        - Unix 系统会调用 fsync 确保数据落盘
        - Windows 可能需要多次重试替换操作
    """
    p = Path(path)

    # 确保父目录存在
    p.parent.mkdir(parents=True, exist_ok=True)

    # 构造临时文件路径
    tmp_name = f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    tmp = p.with_name(tmp_name)

    try:
        # 写入临时文件
        with open(tmp, "w", encoding=encoding) as f:
            f.write(data)
            f.flush()
            # Unix: 确保数据同步到磁盘
            if sys.platform != "win32":
                os.fsync(f.fileno())

        # 原子替换
        _safe_replace(tmp, p, max_retries)

    except Exception as e:
        logger.error("原子写入失败 [%s]: %s", path, e)
        _cleanup_temp_file(tmp)
        raise


def _safe_replace(src: Path, dst: Path, max_retries: int) -> None:
    """安全替换文件（Windows 兼容）。

    Args:
        src: 源文件路径。
        dst: 目标文件路径。
        max_retries: 最大重试次数。

    Raises:
        OSError: 替换操作最终失败。
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            if sys.platform == "win32":
                # Windows: 可能需要先删除目标文件
                if dst.exists():
                    try:
                        dst.unlink()
                    except PermissionError:
                        if attempt < max_retries - 1:
                            time.sleep(0.1 * (attempt + 1))
                            continue
                        raise
                src.rename(dst)
            else:
                # POSIX: 原子替换
                src.replace(dst)
            return

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))

    if last_error:
        raise last_error
    raise OSError("文件替换失败（已达最大重试次数）")


def _cleanup_temp_file(tmp: Path) -> None:
    """清理临时文件。

    Args:
        tmp: 临时文件路径。
    """
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError as e:
        logger.debug("清理临时文件失败: %s", e)


# ============================================================
# JSON 操作
# ============================================================


def safe_json_load(
    path: str | Path,
    default: T | Callable[[], T] | None = None,
    as_set: bool = False,
) -> T | Any:
    """线程安全地加载 JSON 文件。

    Args:
        path: JSON 文件路径。
        default: 文件不存在或加载失败时的默认值。
            可以是具体值或返回默认值的可调用对象。
        as_set: 是否将列表数据转换为集合返回。

    Returns:
        加载的 JSON 数据，或默认值。

    Example:
        >>> config = safe_json_load("config.json", default=dict)
        >>> viewed_ids = safe_json_load("viewed.json", default=set, as_set=True)

    Note:
        使用共享锁（读锁）进行文件访问。
    """
    path = Path(path)

    # 获取默认值
    def get_default() -> Any:
        if callable(default):
            return default()
        elif default is not None:
            return default
        return {}

    if not path.exists():
        return get_default()

    try:
        with file_lock(str(path), exclusive=False, timeout=5.0):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                return get_default()

            data = json.loads(content)

            if as_set:
                if isinstance(data, list):
                    return set(data)
                elif isinstance(data, dict):
                    return set(data.keys())

            return data

    except json.JSONDecodeError as e:
        logger.warning("JSON 解析错误 [%s]: %s", path, e)
    except FileLockTimeoutError:
        logger.warning("获取文件锁超时 [%s]", path)
    except Exception as e:
        logger.warning("加载文件失败 [%s]: %s", path, e)

    return get_default()


def safe_json_save(
    path: str | Path,
    data: Any,
    as_list: bool = False,
    indent: int = 2,
) -> bool:
    """线程安全地保存数据到 JSON 文件。

    Args:
        path: 保存路径。
        data: 要保存的数据。
        as_list: 是否将集合类型转换为排序列表。
        indent: JSON 缩进空格数。

    Returns:
        是否保存成功。

    Example:
        >>> safe_json_save("config.json", {"key": "value"})
        True
        >>> safe_json_save("ids.json", {3, 1, 2}, as_list=True)
        True

    Note:
        使用排他锁（写锁）进行文件访问。
    """
    try:
        with file_lock(str(path), exclusive=True, timeout=DEFAULT_LOCK_TIMEOUT):
            save_data = data

            if as_list and isinstance(data, (set, frozenset)):
                # 排序以确保输出确定性
                save_data = sorted(data, key=lambda x: str(x))

            content = json.dumps(
                save_data,
                ensure_ascii=False,
                indent=indent,
                default=str,  # 处理不可序列化的类型
            )
            atomic_write(str(path), content)
            return True

    except FileLockTimeoutError:
        logger.error("获取文件锁超时 [%s]", path)
    except Exception as e:
        logger.error("保存文件失败 [%s]: %s", path, e)

    return False


# ============================================================
# 高 DPI 支持
# ============================================================


def init_dpi_awareness() -> None:
    """初始化系统 DPI 感知（仅 Windows）。

    设置进程的 DPI 感知级别，使应用程序能够正确处理高 DPI 显示器。

    Note:
        - 此函数应在创建任何 GUI 元素之前调用
        - PyQt6 默认启用高 DPI 支持，通常不需要手动调用
        - 多次调用是安全的（幂等操作）

    Warning:
        必须在创建 QApplication 之前调用才能生效。
    """
    global _dpi_initialized, _dpi_scale_factor

    if _dpi_initialized:
        return

    _dpi_initialized = True

    if sys.platform != "win32":
        _dpi_scale_factor = 1.0
        return

    try:
        import ctypes

        # 尝试使用最新的 DPI 感知 API
        try:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+)
            awareness = ctypes.c_void_p(-4)
            ctypes.windll.user32.SetProcessDpiAwarenessContext(awareness)
            logger.debug("DPI 感知已设置: PerMonitorV2")
        except (AttributeError, OSError):
            try:
                # PROCESS_PER_MONITOR_DPI_AWARE (Windows 8.1+)
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
                logger.debug("DPI 感知已设置: PerMonitor")
            except (AttributeError, OSError):
                try:
                    # System DPI Aware (Windows Vista+)
                    ctypes.windll.user32.SetProcessDPIAware()
                    logger.debug("DPI 感知已设置: SystemAware")
                except (AttributeError, OSError):
                    logger.debug("DPI 感知设置不可用")

        # 获取 DPI 缩放因子
        _dpi_scale_factor = _get_windows_dpi_scale()

    except Exception as e:
        logger.debug("DPI 初始化失败: %s", e)
        _dpi_scale_factor = 1.0


def _get_windows_dpi_scale() -> float:
    """获取 Windows 系统 DPI 缩放因子。

    Returns:
        DPI 缩放因子（例如 1.0, 1.25, 1.5, 2.0）。
    """
    try:
        import ctypes

        # 优先使用 GetDpiForSystem (Windows 10+)
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return dpi / 96.0
        except (AttributeError, OSError):
            pass

        # 回退到 GetDeviceCaps
        hdc = ctypes.windll.user32.GetDC(0)
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            return dpi / 96.0
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)

    except Exception as e:
        logger.debug("获取 DPI 缩放因子失败: %s", e)
        return 1.0


def get_system_scale_factor() -> float:
    """获取系统 DPI 缩放因子。

    Returns:
        缩放因子，常见值为 1.0, 1.25, 1.5, 1.75, 2.0 等。

    Example:
        >>> scale = get_system_scale_factor()
        >>> if scale > 1.5:
        ...     print("高 DPI 显示器")

    Note:
        在 PyQt6 应用中，推荐使用 QScreen.devicePixelRatio()
        获取更准确的屏幕缩放值。
    """
    if not _dpi_initialized:
        init_dpi_awareness()

    return _dpi_scale_factor


def scaled_size(value: int, scale: float | None = None) -> int:
    """根据 DPI 缩放计算实际像素值。

    Args:
        value: 设计稿中的像素值（基于 96 DPI）。
        scale: 自定义缩放因子。如果为 None，则使用系统缩放。

    Returns:
        缩放后的像素值。

    Example:
        >>> # 假设系统缩放为 1.5
        >>> scaled_size(100)
        150
        >>> scaled_size(100, scale=2.0)
        200
    """
    if scale is None:
        scale = get_system_scale_factor()
    return int(value * scale)


# ============================================================
# 通用工具函数
# ============================================================


def clean_tags(tags_str: str, max_length: int = 500) -> str:
    """清理标签字符串。

    移除非法字符、规范化空白，并限制最大长度。
    适用于处理可能用于文件名的标签。

    Args:
        tags_str: 原始标签字符串。
        max_length: 结果字符串的最大长度。

    Returns:
        清理后的标签字符串。

    Example:
        >>> clean_tags("  tag1   tag2  <invalid>  ")
        'tag1 tag2 _invalid_'
        >>> clean_tags("a" * 1000, max_length=10)
        'aaaaaaaaaa'
    """
    if not tags_str:
        return ""

    # 移除首尾空白并规范化内部空白
    cleaned = " ".join(tags_str.split())

    # 替换文件名不安全字符
    unsafe_chars = '<>:"/\\|?*&#\x00'
    for char in unsafe_chars:
        cleaned = cleaned.replace(char, "_")

    # 限制长度（在单词边界处截断）
    if len(cleaned) > max_length:
        truncated = cleaned[:max_length]
        # 尝试在空格处截断以保持单词完整
        last_space = truncated.rfind(" ")
        if last_space > max_length // 2:
            cleaned = truncated[:last_space]
        else:
            cleaned = truncated

    return cleaned


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读格式。

    Args:
        size_bytes: 文件大小（字节数）。

    Returns:
        格式化后的字符串，如 "1.5 MB", "256 KB"。

    Example:
        >>> format_file_size(1536)
        '1.5 KB'
        >>> format_file_size(1048576)
        '1.0 MB'
        >>> format_file_size(0)
        '0 B'
    """
    if size_bytes < 0:
        return "0 B"

    if size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)

    for unit in units[:-1]:
        if size < 1024:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024

    return f"{size:.2f} {units[-1]}"


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在，如不存在则创建。

    Args:
        path: 目录路径。

    Returns:
        目录的 Path 对象。

    Raises:
        OSError: 无法创建目录。

    Example:
        >>> data_dir = ensure_dir("./data/cache")
        >>> data_dir.exists()
        True
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p