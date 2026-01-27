"""收藏管理器模块 - 性能优化版 v2.1（稳定版）。

本模块提供收藏图片的浏览、预览、删除等功能，
支持分类筛选、标签搜索和缩略图显示。

v2.1 改进:
    - 修复类型注解兼容性（Python 3.8+）
    - 增强线程安全（锁机制）
    - 完善异常处理和边界检查
    - 改进资源清理逻辑
    - 修复预览对话框 resize 防抖

Example:
    基本使用示例::

        manager = FavoritesManager(parent=main_window, base_dir="./favorites")
        manager.show()
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Optional,
    Set,
    Tuple,
    TYPE_CHECKING,
)

from PyQt6.QtCore import (
    Qt,
    QAbstractListModel,
    QModelIndex,
    QObject,
    QRect,
    QRunnable,
    QSize,
    QThread,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from config.app_config import CONFIG
from config.design_tokens import TOKENS

if TYPE_CHECKING:
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QCloseEvent, QKeyEvent, QResizeEvent

logger = logging.getLogger(__name__)

# 设计令牌快捷引用
C = TOKENS.colors
T = TOKENS.typography
S = TOKENS.spacing
L = TOKENS.layout

# 模块版本（用于缓存失效）
_CACHE_VERSION = "2.1"

# 检测 PIL 可用性
try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PIL 不可用，缩略图生成功能受限")

# 检测 PIL ImageOps 可用性
try:
    from PIL import ImageOps

    HAS_IMAGEOPS = True
except ImportError:
    HAS_IMAGEOPS = False

# 检测 send2trash 可用性
try:
    from send2trash import send2trash

    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False
    logger.info("send2trash 不可用，删除将直接移除文件")


# =============================================================================
# 磁盘缩略图缓存 - 线程安全版
# =============================================================================


class ThumbnailCache:
    """磁盘缩略图缓存管理器 - 带 LRU 淘汰和原子写入。

    特性：
    - 磁盘缓存容量限制（按文件数）
    - 原子写入防止损坏
    - 缓存 key 包含文件大小和版本号
    - 内存 LRU 缓存（线程安全）
    - HiDPI 支持

    Attributes:
        cache_dir: 缓存目录路径。
        max_disk_items: 磁盘缓存最大条目数。
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        max_disk_items: int = 2000,
        max_memory_items: int = 150,
    ) -> None:
        """初始化缓存管理器。

        Args:
            cache_dir: 缓存目录路径，默认使用应用数据目录。
            max_disk_items: 磁盘缓存最大条目数。
            max_memory_items: 内存缓存最大条目数。
        """
        if cache_dir is None:
            app_data = Path(os.environ.get("APPDATA", str(Path.home() / ".cache")))
            cache_dir = str(app_data / "yande_viewer" / "thumb_cache_v2")

        self.cache_dir = Path(cache_dir)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("无法创建缓存目录 [%s]: %s", cache_dir, e)

        self.max_disk_items = max_disk_items
        self._max_memory_items = max_memory_items

        # 内存缓存（LRU）- 线程安全
        self._memory_cache: Dict[str, QImage] = {}
        self._memory_order: List[str] = []
        self._memory_lock = threading.Lock()

        # 定期清理标志
        self._cleanup_scheduled = False
        self._cleanup_lock = threading.Lock()

    def _get_device_pixel_ratio(self) -> float:
        """获取设备像素比（安全方式）。

        Returns:
            设备像素比，默认 1.0。
        """
        try:
            app = QApplication.instance()
            if app is not None:
                screen = app.primaryScreen()
                if screen is not None:
                    return screen.devicePixelRatio()
        except Exception:
            pass
        return 1.0

    def _get_cache_key(self, path: str, mtime: float, size: int) -> str:
        """生成缓存键（包含文件大小和版本号）。

        Args:
            path: 文件路径。
            mtime: 文件修改时间。
            size: 文件大小。

        Returns:
            MD5 哈希字符串。
        """
        thumb_size = getattr(CONFIG, "thumbnail_size", (160, 160))
        dpr = self._get_device_pixel_ratio()
        content = f"{path}:{mtime}:{size}:{thumb_size}:{dpr}:{_CACHE_VERSION}".encode()
        return hashlib.md5(content).hexdigest()

    def get(self, path: str, mtime: float, size: int) -> Optional[QImage]:
        """获取缓存的缩略图（返回 QImage）。

        Args:
            path: 文件路径。
            mtime: 文件修改时间。
            size: 文件大小。

        Returns:
            缓存的 QImage，不存在返回 None。
        """
        key = self._get_cache_key(path, mtime, size)

        # 先检查内存缓存（线程安全）
        with self._memory_lock:
            if key in self._memory_cache:
                # LRU: 移到末尾
                try:
                    self._memory_order.remove(key)
                except ValueError:
                    pass
                self._memory_order.append(key)
                return self._memory_cache[key].copy()  # 返回副本

        # 检查磁盘缓存
        if not self.cache_dir.exists():
            return None

        for suffix in (".webp", ".jpg", ".png"):
            cache_path = self.cache_dir / f"{key}{suffix}"
            if cache_path.exists():
                try:
                    qimage = QImage(str(cache_path))
                    if not qimage.isNull():
                        self._add_to_memory(key, qimage)
                        # 更新访问时间用于 LRU
                        try:
                            cache_path.touch()
                        except OSError:
                            pass
                        return qimage
                    else:
                        # 损坏的缓存文件，删除
                        try:
                            cache_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                except Exception as e:
                    logger.debug("读取缓存失败 [%s]: %s", cache_path, e)

        return None

    def put(self, path: str, mtime: float, size: int, qimage: QImage) -> None:
        """存储缩略图到缓存（接受 QImage）。

        Args:
            path: 文件路径。
            mtime: 文件修改时间。
            size: 文件大小。
            qimage: 缩略图 QImage。
        """
        if qimage.isNull():
            return

        key = self._get_cache_key(path, mtime, size)

        # 存入内存缓存
        self._add_to_memory(key, qimage.copy())

        # 原子写入磁盘缓存
        if self.cache_dir.exists():
            cache_path = self.cache_dir / f"{key}.webp"
            self._atomic_save(qimage, cache_path)

            # 调度磁盘清理
            self._schedule_cleanup()

    def _atomic_save(self, qimage: QImage, target_path: Path) -> None:
        """原子写入图像到磁盘（先写临时文件再重命名）。

        Args:
            qimage: 要保存的 QImage。
            target_path: 目标路径。
        """
        tmp_path: Optional[str] = None
        try:
            # 写入临时文件
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", dir=str(self.cache_dir)
            )
            os.close(fd)

            # 尝试保存为 WEBP
            if qimage.save(tmp_path, "WEBP", 85):
                shutil.move(tmp_path, str(target_path))
                tmp_path = None
            else:
                # WEBP 失败，尝试 PNG
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                fd, tmp_path = tempfile.mkstemp(
                    suffix=".tmp", dir=str(self.cache_dir)
                )
                os.close(fd)
                target_path = target_path.with_suffix(".png")
                if qimage.save(tmp_path, "PNG"):
                    shutil.move(tmp_path, str(target_path))
                    tmp_path = None

        except Exception as e:
            logger.debug("保存缓存失败: %s", e)
        finally:
            # 清理临时文件
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _add_to_memory(self, key: str, qimage: QImage) -> None:
        """添加到内存缓存，必要时淘汰旧条目（LRU，线程安全）。"""
        with self._memory_lock:
            if key in self._memory_cache:
                try:
                    self._memory_order.remove(key)
                except ValueError:
                    pass

            # 淘汰最旧的条目
            while len(self._memory_cache) >= self._max_memory_items:
                if self._memory_order:
                    oldest = self._memory_order.pop(0)
                    self._memory_cache.pop(oldest, None)
                else:
                    break

            self._memory_cache[key] = qimage
            self._memory_order.append(key)

    def _schedule_cleanup(self) -> None:
        """调度磁盘缓存清理（延迟执行避免阻塞）。"""
        with self._cleanup_lock:
            if self._cleanup_scheduled:
                return
            self._cleanup_scheduled = True
        QTimer.singleShot(5000, self._cleanup_disk_cache)

    def _cleanup_disk_cache(self) -> None:
        """清理磁盘缓存，保持在限制内（LRU 策略）。"""
        with self._cleanup_lock:
            self._cleanup_scheduled = False

        try:
            if not self.cache_dir.exists():
                return

            cache_files = list(self.cache_dir.glob("*.*"))
            if len(cache_files) <= self.max_disk_items:
                return

            # 按访问时间排序（最旧的在前）
            cache_files.sort(key=lambda f: f.stat().st_atime)

            # 删除最旧的文件
            to_remove = len(cache_files) - self.max_disk_items
            removed = 0
            for f in cache_files[:to_remove]:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass

            if removed > 0:
                logger.debug("清理了 %d 个缓存文件", removed)
        except Exception as e:
            logger.warning("缓存清理失败: %s", e)

    def clear_memory(self) -> None:
        """清空内存缓存。"""
        with self._memory_lock:
            self._memory_cache.clear()
            self._memory_order.clear()


# 全局缓存实例
_thumbnail_cache = ThumbnailCache()


# =============================================================================
# 异步文件扫描器 - 增量版
# =============================================================================


class FileScannerSignals(QObject):
    """文件扫描器信号定义。"""

    batch_ready = pyqtSignal(str, list)  # (scan_id, 批量文件列表)
    progress = pyqtSignal(str, int)  # (scan_id, 已扫描数)
    finished = pyqtSignal(str, int)  # (scan_id, 总数)
    error = pyqtSignal(str, str)  # (scan_id, 错误信息)


class FileScanner(QThread):
    """异步文件扫描线程 - 增量推送版。

    改进点：
    - 使用 os.scandir() 替代 Path.iterdir()（更快，复用 stat）
    - 单次遍历，边扫描边推送
    - 进度不依赖 total（显示已扫描数 + 动画）
    """

    SUPPORTED_FORMATS: FrozenSet[str] = frozenset(
        {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    )
    BATCH_SIZE: int = 50  # 每批推送数量

    def __init__(
        self,
        base_dir: str,
        scan_id: str,
        parent: Optional[QObject] = None,
    ) -> None:
        """初始化扫描器。

        Args:
            base_dir: 收藏根目录。
            scan_id: 扫描任务 ID（用于过期检测）。
            parent: 父对象。
        """
        super().__init__(parent)
        self.base_dir = base_dir
        self.scan_id = scan_id
        self.signals = FileScannerSignals()
        self._cancelled = False

    def cancel(self) -> None:
        """取消扫描。"""
        self._cancelled = True

    def run(self) -> None:
        """执行扫描任务（单次遍历 + 增量推送）。"""
        try:
            categories = ["Safe", "Questionable", "Explicit"]
            batch: List[Dict[str, Any]] = []
            total_count = 0

            for category in categories:
                if self._cancelled:
                    return

                folder = Path(self.base_dir) / category
                if not folder.exists():
                    continue

                try:
                    # 使用 os.scandir 提高效率
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            if self._cancelled:
                                return

                            if not entry.is_file():
                                continue

                            name = entry.name
                            if name.endswith(".tmp"):
                                continue

                            suffix = Path(name).suffix.lower()
                            if suffix not in self.SUPPORTED_FORMATS:
                                continue

                            try:
                                stat = entry.stat()
                            except OSError:
                                continue

                            stem = Path(name).stem
                            parts = stem.split("_", 1)

                            file_info: Dict[str, Any] = {
                                "path": entry.path,
                                "filename": name,
                                "category": category,
                                "id": parts[0],
                                "tags": (
                                    parts[1].replace("_", " ")
                                    if len(parts) > 1
                                    else ""
                                ),
                                "size": stat.st_size,
                                "mtime": stat.st_mtime,
                            }

                            batch.append(file_info)
                            total_count += 1

                            if len(batch) >= self.BATCH_SIZE:
                                batch.sort(key=lambda x: x["mtime"], reverse=True)
                                self.signals.batch_ready.emit(
                                    self.scan_id, batch.copy()
                                )
                                self.signals.progress.emit(self.scan_id, total_count)
                                batch.clear()

                except OSError as e:
                    logger.warning("扫描目录失败 [%s]: %s", folder, e)
                    continue

            # 推送剩余的
            if batch and not self._cancelled:
                batch.sort(key=lambda x: x["mtime"], reverse=True)
                self.signals.batch_ready.emit(self.scan_id, batch)

            if not self._cancelled:
                self.signals.finished.emit(self.scan_id, total_count)

        except Exception as e:
            logger.error("文件扫描失败: %s", e)
            if not self._cancelled:
                self.signals.error.emit(self.scan_id, str(e))


# =============================================================================
# 异步缩略图加载器 - 线程安全版
# =============================================================================


class ThumbnailSignals(QObject):
    """缩略图加载信号。"""

    ready = pyqtSignal(str, str, object)  # (generation_id, path, QImage)
    failed = pyqtSignal(str, str, str)  # (generation_id, path, error)


class ThumbnailTask(QRunnable):
    """缩略图加载任务 - 返回 QImage。

    关键改进：
    - 后台线程只生成 QImage（线程安全）
    - 主线程负责转换为 QPixmap
    - 支持 EXIF 自动旋转
    - HiDPI 缩放支持
    """

    def __init__(
        self,
        generation_id: str,
        path: str,
        mtime: float,
        size: int,
        thumb_size: Tuple[int, int],
        signals: ThumbnailSignals,
    ) -> None:
        """初始化任务。

        Args:
            generation_id: 任务代号，用于过期检测。
            path: 文件路径。
            mtime: 修改时间。
            size: 文件大小。
            thumb_size: 目标尺寸。
            signals: 信号对象。
        """
        super().__init__()
        self.generation_id = generation_id
        self.path = path
        self.mtime = mtime
        self.size = size
        self.thumb_size = thumb_size
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        """执行加载任务。"""
        try:
            # 检查缓存
            cached = _thumbnail_cache.get(self.path, self.mtime, self.size)
            if cached is not None:
                self.signals.ready.emit(self.generation_id, self.path, cached)
                return

            # 生成缩略图（QImage）
            qimage = self._generate_thumbnail()
            if qimage is not None and not qimage.isNull():
                _thumbnail_cache.put(self.path, self.mtime, self.size, qimage)
                self.signals.ready.emit(self.generation_id, self.path, qimage)
            else:
                self.signals.failed.emit(
                    self.generation_id, self.path, "生成失败"
                )

        except Exception as e:
            self.signals.failed.emit(self.generation_id, self.path, str(e))

    def _get_device_pixel_ratio(self) -> float:
        """获取设备像素比（安全方式）。"""
        try:
            app = QApplication.instance()
            if app is not None:
                screen = app.primaryScreen()
                if screen is not None:
                    return screen.devicePixelRatio()
        except Exception:
            pass
        return 1.0

    def _generate_thumbnail(self) -> Optional[QImage]:
        """生成缩略图（返回 QImage，线程安全）。

        Returns:
            QImage 或 None。
        """
        if not os.path.exists(self.path):
            return None

        dpr = self._get_device_pixel_ratio()
        actual_size = (
            int(self.thumb_size[0] * dpr),
            int(self.thumb_size[1] * dpr),
        )

        try:
            if HAS_PIL:
                return self._generate_with_pil(actual_size, dpr)
            else:
                return self._generate_with_qt(actual_size, dpr)
        except Exception as e:
            logger.debug("缩略图生成失败 [%s]: %s", self.path, e)
            return None

    def _generate_with_pil(
        self, actual_size: Tuple[int, int], dpr: float
    ) -> Optional[QImage]:
        """使用 PIL 生成缩略图。"""
        img: Optional[Image.Image] = None
        try:
            img = Image.open(self.path)

            # 处理 EXIF 旋转
            if HAS_IMAGEOPS:
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass

            img.thumbnail(actual_size, Image.Resampling.LANCZOS)

            # 转换为 RGBA/RGB
            if img.mode not in ("RGBA", "RGB"):
                img = img.convert("RGBA")

            # 转换为 QImage
            if img.mode == "RGBA":
                data = img.tobytes("raw", "RGBA")
                qimage = QImage(
                    data,
                    img.width,
                    img.height,
                    img.width * 4,
                    QImage.Format.Format_RGBA8888,
                )
            else:
                data = img.tobytes("raw", "RGB")
                qimage = QImage(
                    data,
                    img.width,
                    img.height,
                    img.width * 3,
                    QImage.Format.Format_RGB888,
                )

            # 必须深拷贝
            result = qimage.copy()
            result.setDevicePixelRatio(dpr)
            return result
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass

    def _generate_with_qt(
        self, actual_size: Tuple[int, int], dpr: float
    ) -> Optional[QImage]:
        """使用 Qt 生成缩略图。"""
        from PyQt6.QtGui import QImageReader

        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        reader.setScaledSize(QSize(*actual_size))

        qimage = reader.read()
        if qimage.isNull():
            return None

        qimage.setDevicePixelRatio(dpr)
        return qimage


class ThumbnailLoader(QObject):
    """缩略图加载管理器（私有线程池 + 代号机制）。

    改进点：
    - 私有 QThreadPool（不与全局共享）
    - generation_id 任务代号机制
    - 线程安全的 pending 管理
    - closeEvent 时正确关闭
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """初始化加载器。"""
        super().__init__(parent)
        self.signals = ThumbnailSignals()
        self._pending: Set[str] = set()
        self._pending_lock = threading.Lock()
        self._generation_id: str = ""
        self._generation_lock = threading.Lock()

        # 私有线程池
        self._pool = QThreadPool()
        max_threads = max(2, min(4, QThreadPool.globalInstance().maxThreadCount()))
        self._pool.setMaxThreadCount(max_threads)

    def set_generation_id(self, gen_id: str) -> None:
        """设置当前任务代号（新代号会使旧任务结果被忽略）。

        Args:
            gen_id: 新的代号。
        """
        with self._generation_lock:
            self._generation_id = gen_id
        with self._pending_lock:
            self._pending.clear()

    def get_generation_id(self) -> str:
        """获取当前任务代号。"""
        with self._generation_lock:
            return self._generation_id

    def load(
        self,
        path: str,
        mtime: float,
        size: int,
        thumb_size: Tuple[int, int],
    ) -> bool:
        """请求加载缩略图。

        Args:
            path: 文件路径。
            mtime: 修改时间。
            size: 文件大小。
            thumb_size: 目标尺寸。

        Returns:
            是否成功提交请求（False 表示已在队列中）。
        """
        with self._pending_lock:
            if path in self._pending:
                return False
            self._pending.add(path)

        gen_id = self.get_generation_id()
        task = ThumbnailTask(
            gen_id,
            path,
            mtime,
            size,
            thumb_size,
            self.signals,
        )
        self._pool.start(task)
        return True

    def on_complete(self, path: str) -> None:
        """任务完成回调，清理 pending 状态。"""
        with self._pending_lock:
            self._pending.discard(path)

    def clear(self) -> None:
        """清空等待队列。"""
        with self._pending_lock:
            self._pending.clear()
        self._pool.clear()

    def shutdown(self) -> None:
        """关闭线程池。"""
        self._pool.clear()
        self._pool.waitForDone(3000)


# =============================================================================
# 文件列表模型（Qt Model/View 架构）
# =============================================================================


class FileListModel(QAbstractListModel):
    """文件列表数据模型。

    用于 QListView，支持增量添加和筛选。
    """

    # 自定义角色
    PathRole = Qt.ItemDataRole.UserRole + 1
    CategoryRole = Qt.ItemDataRole.UserRole + 2
    TagsRole = Qt.ItemDataRole.UserRole + 3
    SizeRole = Qt.ItemDataRole.UserRole + 4
    MtimeRole = Qt.ItemDataRole.UserRole + 5
    FileIdRole = Qt.ItemDataRole.UserRole + 6
    ThumbnailRole = Qt.ItemDataRole.UserRole + 7

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """初始化模型。"""
        super().__init__(parent)
        self._all_files: List[Dict[str, Any]] = []
        self._filtered_files: List[Dict[str, Any]] = []
        self._thumbnails: Dict[str, QPixmap] = {}
        self._filter_category: str = "All"
        self._filter_query: str = ""

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回行数。"""
        if parent.isValid():
            return 0
        return len(self._filtered_files)

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        """返回数据。"""
        if not index.isValid():
            return None

        row = index.row()
        if row < 0 or row >= len(self._filtered_files):
            return None

        file_info = self._filtered_files[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return f"#{file_info.get('id', 'N/A')}"
        elif role == self.PathRole:
            return file_info.get("path", "")
        elif role == self.CategoryRole:
            return file_info.get("category", "")
        elif role == self.TagsRole:
            return file_info.get("tags", "")
        elif role == self.SizeRole:
            return file_info.get("size", 0)
        elif role == self.MtimeRole:
            return file_info.get("mtime", 0.0)
        elif role == self.FileIdRole:
            return file_info.get("id", "")
        elif role == self.ThumbnailRole:
            path = file_info.get("path", "")
            return self._thumbnails.get(path) if path else None
        elif role == Qt.ItemDataRole.ToolTipRole:
            size_mb = file_info.get("size", 0) / 1024 / 1024
            tags = file_info.get("tags", "")
            tags_preview = tags[:100] if tags else ""
            return (
                f"ID: {file_info.get('id', 'N/A')}\n"
                f"分类: {file_info.get('category', 'N/A')}\n"
                f"大小: {size_mb:.1f}MB\n"
                f"标签: {tags_preview}..."
            )

        return None

    def set_thumbnail(self, path: str, pixmap: QPixmap) -> None:
        """设置缩略图。"""
        if not path or pixmap.isNull():
            return

        self._thumbnails[path] = pixmap

        # 找到对应的行并通知更新
        for i, f in enumerate(self._filtered_files):
            if f.get("path") == path:
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [self.ThumbnailRole])
                break

    def add_files(self, files: List[Dict[str, Any]]) -> None:
        """增量添加文件。"""
        if not files:
            return

        self._all_files.extend(files)
        self._apply_filter()

    def clear(self) -> None:
        """清空所有数据。"""
        self.beginResetModel()
        self._all_files.clear()
        self._filtered_files.clear()
        self._thumbnails.clear()
        self.endResetModel()

    def set_filter(self, category: str = "All", query: str = "") -> None:
        """设置筛选条件。"""
        self._filter_category = category
        self._filter_query = query.lower().strip()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """应用筛选条件。"""
        self.beginResetModel()

        self._filtered_files = [
            f
            for f in self._all_files
            if (
                self._filter_category == "All"
                or f.get("category") == self._filter_category
            )
            and (
                not self._filter_query
                or self._filter_query in f.get("tags", "").lower()
            )
        ]

        self._filtered_files.sort(key=lambda x: x.get("mtime", 0), reverse=True)

        self.endResetModel()

    def get_file_info(self, index: QModelIndex) -> Optional[Dict[str, Any]]:
        """获取指定索引的文件信息。"""
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._filtered_files):
            return None
        return self._filtered_files[row]

    def remove_file(self, path: str) -> None:
        """移除文件。"""
        if not path:
            return

        self._all_files = [f for f in self._all_files if f.get("path") != path]

        for i, f in enumerate(self._filtered_files):
            if f.get("path") == path:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._filtered_files.pop(i)
                self.endRemoveRows()
                break

        self._thumbnails.pop(path, None)

    @property
    def total_count(self) -> int:
        """总文件数。"""
        return len(self._all_files)

    @property
    def filtered_count(self) -> int:
        """筛选后文件数。"""
        return len(self._filtered_files)


# =============================================================================
# 卡片代理 Delegate
# =============================================================================


class CardDelegate(QStyledItemDelegate):
    """卡片样式代理。"""

    CATEGORY_COLORS: Dict[str, str] = {
        "Safe": C.success,
        "Questionable": C.warning,
        "Explicit": C.accent,
    }

    def __init__(
        self,
        thumb_size: Tuple[int, int],
        parent: Optional[QObject] = None,
    ) -> None:
        """初始化代理。"""
        super().__init__(parent)
        self.thumb_size = thumb_size
        self._card_width = thumb_size[0] + 16
        self._card_height = thumb_size[1] + 50

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QSize:
        """返回建议尺寸。"""
        return QSize(self._card_width, self._card_height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """绘制卡片。"""
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            rect = option.rect
            is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
            is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

            # 背景
            bg_color = QColor(C.bg_hover if is_hovered else C.bg_surface)
            if is_selected:
                bg_color = QColor(C.accent)
            bg_color.setAlpha(30)

            painter.setBrush(QBrush(bg_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 8, 8)

            # 缩略图区域
            thumb_rect = QRect(
                rect.x() + 8,
                rect.y() + 8,
                self.thumb_size[0],
                self.thumb_size[1],
            )

            # 缩略图
            pixmap = index.data(FileListModel.ThumbnailRole)
            if pixmap is not None and not pixmap.isNull():
                scaled = pixmap.scaled(
                    thumb_rect.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = thumb_rect.x() + (thumb_rect.width() - scaled.width()) // 2
                y = thumb_rect.y() + (thumb_rect.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
            else:
                painter.setBrush(QBrush(QColor(C.bg_hover)))
                painter.drawRoundedRect(thumb_rect, 4, 4)
                painter.setPen(QPen(QColor(C.text_muted)))
                font = painter.font()
                font.setPointSize(20)
                painter.setFont(font)
                painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "⏳")

            # ID 标签
            file_id = index.data(FileListModel.FileIdRole) or "N/A"
            id_rect = QRect(
                rect.x() + 8,
                thumb_rect.bottom() + 4,
                rect.width() - 16,
                16,
            )
            painter.setPen(QPen(QColor(C.text_primary)))
            font = QFont(T.font_mono)
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(id_rect, Qt.AlignmentFlag.AlignCenter, f"#{file_id}")

            # 分类和大小
            category = index.data(FileListModel.CategoryRole) or ""
            size = index.data(FileListModel.SizeRole) or 0
            size_mb = size / 1024 / 1024
            color = self.CATEGORY_COLORS.get(category, C.text_muted)

            info_rect = QRect(
                rect.x() + 8,
                id_rect.bottom() + 2,
                rect.width() - 16,
                14,
            )
            painter.setPen(QPen(QColor(color)))
            font.setPointSize(8)
            painter.setFont(font)
            cat_initial = category[:1] if category else "?"
            painter.drawText(
                info_rect,
                Qt.AlignmentFlag.AlignCenter,
                f"{cat_initial} · {size_mb:.1f}MB",
            )

            # 分类色条
            bar_rect = QRect(
                rect.x() + 2,
                rect.y() + 2,
                4,
                rect.height() - 4,
            )
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bar_rect, 2, 2)

        finally:
            painter.restore()


# =============================================================================
# 收藏管理器
# =============================================================================


class FavoritesManager:
    """收藏管理器入口类。"""

    def __init__(self, parent: QWidget, base_dir: str) -> None:
        """初始化。"""
        self.parent = parent
        self.base_dir = base_dir
        self.window: Optional[FavoritesWindow] = None

    def show(self) -> None:
        """显示管理器窗口。"""
        if self.window is not None:
            try:
                if self.window.isVisible():
                    self.window.raise_()
                    self.window.activateWindow()
                    return
            except RuntimeError:
                # 窗口已被删除（C++ 对象已销毁）
                self.window = None

        self.window = FavoritesWindow(self.parent, self.base_dir, self)
        self.window.show()


class FavoritesWindow(QMainWindow):
    """收藏管理器窗口 - Model/View 架构版。"""

    CATEGORY_COLORS: Dict[str, str] = {
        "Safe": C.success,
        "Questionable": C.warning,
        "Explicit": C.accent,
    }

    def __init__(
        self,
        parent: QWidget,
        base_dir: str,
        manager: FavoritesManager,
    ) -> None:
        """初始化窗口。"""
        super().__init__(parent)

        self.base_dir = base_dir
        self.manager = manager
        self._closed = False  # 防止关闭后回调执行

        # 任务代号
        self._generation_id: str = ""
        self._scan_id: str = ""

        # 异步组件
        self._scanner: Optional[FileScanner] = None
        self._thumb_loader = ThumbnailLoader(self)
        self._thumb_loader.signals.ready.connect(self._on_thumb_ready)
        self._thumb_loader.signals.failed.connect(self._on_thumb_failed)

        # 数据模型
        self._model = FileListModel(self)

        # 窗口配置
        self.setWindowTitle("📁 收藏管理器")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(f"background-color: {C.bg_base};")

        self._setup_ui()
        self._start_scan()

        # 居中显示
        if parent:
            try:
                self.move(
                    parent.x() + (parent.width() - 1000) // 2,
                    parent.y() + (parent.height() - 700) // 2,
                )
            except Exception:
                pass

    def _setup_ui(self) -> None:
        """构建界面。"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
        layout.addWidget(self._create_toolbar())

        # 加载提示
        self.loading_label = QLabel("正在扫描文件...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet(f"""
            color: {C.text_muted};
            font-size: 14px;
            padding: 40px;
        """)
        layout.addWidget(self.loading_label)

        # QListView
        self.list_view = QListView()
        self.list_view.setModel(self._model)
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setMovement(QListView.Movement.Static)
        self.list_view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_view.setSpacing(10)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setWordWrap(False)

        thumb_size = getattr(CONFIG, "thumbnail_size", (160, 160))
        self._delegate = CardDelegate(thumb_size, self)
        self.list_view.setItemDelegate(self._delegate)

        self.list_view.setStyleSheet(f"""
            QListView {{
                border: none;
                background-color: {C.bg_base};
                padding: 12px;
            }}
            QListView::item {{
                border: none;
                background: transparent;
            }}
            QListView::item:selected {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {C.bg_surface};
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {C.bg_hover};
                min-height: 30px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C.text_muted};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self.list_view.clicked.connect(self._on_item_clicked)
        self.list_view.doubleClicked.connect(self._on_item_double_clicked)
        self.list_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.list_view.customContextMenuRequested.connect(
            self._on_context_menu_requested
        )

        scrollbar = self.list_view.verticalScrollBar()
        if scrollbar:
            scrollbar.valueChanged.connect(self._schedule_load_visible)

        self.list_view.hide()
        layout.addWidget(self.list_view)

        # 防抖定时器
        self._load_visible_timer = QTimer(self)
        self._load_visible_timer.setSingleShot(True)
        self._load_visible_timer.setInterval(50)
        self._load_visible_timer.timeout.connect(self._load_visible_thumbnails)

    def _create_toolbar(self) -> QFrame:
        """创建工具栏。"""
        toolbar = QFrame()
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet(f"background-color: {C.bg_elevated};")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(12, 8, 12, 8)

        self.filter_group = QButtonGroup(self)
        self.filter_buttons: Dict[str, QRadioButton] = {}

        for name in ["All", "Safe", "Questionable", "Explicit"]:
            rb = QRadioButton(name)
            rb.setStyleSheet(f"color: {C.text_primary}; font-size: 11px;")
            if name == "All":
                rb.setChecked(True)
            rb.toggled.connect(self._on_filter_changed)
            self.filter_group.addButton(rb)
            self.filter_buttons[name] = rb
            layout.addWidget(rb)

        layout.addSpacing(20)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索标签...")
        self.search_input.setFixedWidth(200)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C.bg_surface};
                color: {C.text_primary};
                border: none;
                border-radius: {L.radius_md}px;
                padding: 6px 12px;
            }}
        """)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._on_filter_changed)
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        layout.addWidget(self.search_input)

        layout.addStretch()

        self.stats_label = QLabel()
        self.stats_label.setStyleSheet(f"color: {C.text_muted}; font-size: 12px;")
        layout.addWidget(self.stats_label)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C.bg_surface};
                border: none;
                border-radius: {L.radius_md}px;
                font-size: 14px;
            }}
            QPushButton:hover {{ background-color: {C.bg_hover}; }}
        """)
        refresh_btn.clicked.connect(self._start_scan)
        layout.addWidget(refresh_btn)

        folder_btn = QPushButton("📂")
        folder_btn.setFixedSize(32, 32)
        folder_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {C.bg_surface};
                border: none;
                border-radius: {L.radius_md}px;
                font-size: 14px;
            }}
            QPushButton:hover {{ background-color: {C.bg_hover}; }}
        """)
        folder_btn.clicked.connect(self._open_folder)
        layout.addWidget(folder_btn)

        return toolbar

    def _start_scan(self) -> None:
        """开始异步扫描。"""
        if self._closed:
            return

        if self._scanner is not None:
            self._scanner.cancel()
            try:
                self._scanner.wait(2000)
            except Exception:
                pass

        self._scan_id = str(uuid.uuid4())
        self._generation_id = str(uuid.uuid4())
        self._thumb_loader.set_generation_id(self._generation_id)

        self._model.clear()

        self.loading_label.setText("正在扫描文件...")
        self.loading_label.show()
        self.list_view.hide()

        self._scanner = FileScanner(self.base_dir, self._scan_id, self)
        self._scanner.signals.batch_ready.connect(self._on_scan_batch)
        self._scanner.signals.progress.connect(self._on_scan_progress)
        self._scanner.signals.finished.connect(self._on_scan_finished)
        self._scanner.signals.error.connect(self._on_scan_error)
        self._scanner.start()

    def _on_scan_batch(self, scan_id: str, files: List[Dict[str, Any]]) -> None:
        """扫描批次回调。"""
        if self._closed or scan_id != self._scan_id:
            return

        self._model.add_files(files)
        self._update_stats()

        if self.list_view.isHidden() and self._model.filtered_count > 0:
            self.loading_label.hide()
            self.list_view.show()
            QTimer.singleShot(100, self._load_visible_thumbnails)

    def _on_scan_progress(self, scan_id: str, count: int) -> None:
        """扫描进度回调。"""
        if self._closed or scan_id != self._scan_id:
            return

        if self.loading_label.isVisible():
            self.loading_label.setText(f"正在扫描... {count} 个文件")

    def _on_scan_finished(self, scan_id: str, total: int) -> None:
        """扫描完成回调。"""
        if self._closed or scan_id != self._scan_id:
            return

        self.loading_label.hide()
        self.list_view.show()
        self._update_stats()
        self._load_visible_thumbnails()
        logger.info("扫描完成，共 %d 个文件", total)

    def _on_scan_error(self, scan_id: str, error: str) -> None:
        """扫描错误回调。"""
        if self._closed or scan_id != self._scan_id:
            return

        self.loading_label.setText(f"扫描失败: {error}")
        logger.error("扫描失败: %s", error)

    def _on_filter_changed(self) -> None:
        """筛选条件变化。"""
        if self._closed:
            return

        category = "All"
        for name, btn in self.filter_buttons.items():
            if btn.isChecked():
                category = name
                break

        query = self.search_input.text()

        self._generation_id = str(uuid.uuid4())
        self._thumb_loader.set_generation_id(self._generation_id)

        self._model.set_filter(category, query)
        self._update_stats()

        QTimer.singleShot(50, self._load_visible_thumbnails)

    def _update_stats(self) -> None:
        """更新统计标签。"""
        self.stats_label.setText(
            f"{self._model.filtered_count} / {self._model.total_count}"
        )

    def _schedule_load_visible(self) -> None:
        """调度加载可见缩略图（防抖）。"""
        if not self._closed:
            self._load_visible_timer.start()

    def _load_visible_thumbnails(self) -> None:
        """加载当前可见区域的缩略图。"""
        if self._closed or not self.list_view.isVisible():
            return

        thumb_size = getattr(CONFIG, "thumbnail_size", (160, 160))
        viewport = self.list_view.viewport()
        if not viewport:
            return

        visible_rect = viewport.rect()

        for row in range(self._model.rowCount()):
            index = self._model.index(row)
            item_rect = self.list_view.visualRect(index)

            if not item_rect.isValid():
                continue

            buffered_rect = visible_rect.adjusted(0, -200, 0, 200)
            if not buffered_rect.intersects(item_rect):
                continue

            if index.data(FileListModel.ThumbnailRole) is not None:
                continue

            path = index.data(FileListModel.PathRole)
            mtime = index.data(FileListModel.MtimeRole)
            size = index.data(FileListModel.SizeRole)

            if path and mtime is not None:
                self._thumb_loader.load(path, mtime, size or 0, thumb_size)

    def _on_thumb_ready(
        self, generation_id: str, path: str, qimage: QImage
    ) -> None:
        """缩略图加载完成。"""
        if self._closed or generation_id != self._generation_id:
            return

        self._thumb_loader.on_complete(path)

        pixmap = QPixmap.fromImage(qimage)
        if not pixmap.isNull():
            self._model.set_thumbnail(path, pixmap)

    def _on_thumb_failed(
        self, generation_id: str, path: str, error: str
    ) -> None:
        """缩略图加载失败。"""
        if self._closed or generation_id != self._generation_id:
            return

        self._thumb_loader.on_complete(path)
        logger.debug("缩略图加载失败 [%s]: %s", path, error)

    def _on_item_clicked(self, index: QModelIndex) -> None:
        """单击项目。"""
        pass

    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """双击项目 - 预览。"""
        file_info = self._model.get_file_info(index)
        if file_info:
            self._preview(file_info)

    def _on_context_menu_requested(self, pos: QPoint) -> None:
        """右键菜单请求。"""
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return

        file_info = self._model.get_file_info(index)
        if file_info:
            self._show_context_menu(file_info)

    def _show_context_menu(self, file_info: Dict[str, Any]) -> None:
        """显示右键菜单。"""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {C.bg_elevated};
                color: {C.text_primary};
                border: 1px solid {C.border_default};
                border-radius: {L.radius_md}px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: {L.radius_sm}px;
            }}
            QMenu::item:selected {{
                background-color: {C.bg_hover};
            }}
        """)

        preview_action = QAction("👁 预览", self)
        preview_action.triggered.connect(lambda: self._preview(file_info))
        menu.addAction(preview_action)

        open_action = QAction("📂 打开位置", self)
        open_action.triggered.connect(
            lambda: self._open_location(file_info.get("path", ""))
        )
        menu.addAction(open_action)

        menu.addSeparator()

        delete_text = "🗑 移到回收站" if HAS_SEND2TRASH else "🗑 删除"
        delete_action = QAction(delete_text, self)
        delete_action.triggered.connect(lambda: self._delete(file_info))
        menu.addAction(delete_action)

        menu.exec(QCursor.pos())

    def _preview(self, file_info: Dict[str, Any]) -> None:
        """预览图片。"""
        try:
            dialog = PreviewDialog(self, file_info)
            dialog.exec()
        except Exception as e:
            logger.error("预览失败: %s", e)
            QMessageBox.warning(self, "错误", f"预览失败: {e}")

    def _open_folder(self) -> None:
        """打开收藏文件夹。"""
        path = os.path.abspath(self.base_dir)
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.run(["open", path], check=False, capture_output=True)
            else:
                subprocess.run(
                    ["xdg-open", path], check=False, capture_output=True
                )
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开: {e}")

    def _open_location(self, filepath: str) -> None:
        """打开文件所在位置。"""
        if not filepath:
            return

        try:
            system = platform.system()
            if system == "Windows":
                subprocess.run(
                    ["explorer", "/select,", os.path.abspath(filepath)],
                    check=False,
                    capture_output=True,
                )
            elif system == "Darwin":
                subprocess.run(
                    ["open", "-R", filepath],
                    check=False,
                    capture_output=True,
                )
            else:
                subprocess.run(
                    ["xdg-open", os.path.dirname(filepath)],
                    check=False,
                    capture_output=True,
                )
        except Exception as e:
            logger.warning("打开位置失败: %s", e)

    def _delete(self, file_info: Dict[str, Any]) -> None:
        """删除文件。"""
        filename = file_info.get("filename", "未知文件")
        path = file_info.get("path", "")

        if not path:
            return

        if HAS_SEND2TRASH:
            msg = f"确定将 {filename} 移到回收站？"
        else:
            msg = f"确定永久删除 {filename}？\n（此操作不可撤销）"

        reply = QMessageBox.question(
            self,
            "确认删除",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if HAS_SEND2TRASH:
                send2trash(path)
                logger.info("已移到回收站: %s", filename)
            else:
                os.remove(path)
                logger.info("已删除: %s", filename)

            self._model.remove_file(path)
            self._update_stats()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除失败: {e}")
            logger.error("删除失败 [%s]: %s", filename, e)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口大小变化。"""
        super().resizeEvent(event)
        self._schedule_load_visible()

    def closeEvent(self, event: QCloseEvent) -> None:
        """窗口关闭。"""
        self._closed = True

        if self._scanner is not None:
            self._scanner.cancel()
            try:
                self._scanner.wait(2000)
            except Exception:
                pass

        self._thumb_loader.shutdown()
        _thumbnail_cache.clear_memory()

        super().closeEvent(event)


# =============================================================================
# 预览对话框
# =============================================================================


class PreviewDialog(QDialog):
    """图片预览对话框。"""

    def __init__(self, parent: QWidget, file_info: Dict[str, Any]) -> None:
        """初始化。"""
        super().__init__(parent)
        self.file_info = file_info
        self._load_pending = False  # 防止重复加载

        self.setWindowTitle(f"预览 - #{file_info.get('id', 'N/A')}")
        self.setMinimumSize(900, 700)
        self.setStyleSheet(f"background-color: {C.bg_base};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel("加载中...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(f"color: {C.text_muted};")
        layout.addWidget(self.image_label)

        info_bar = QFrame()
        info_bar.setFixedHeight(40)
        info_bar.setStyleSheet(f"background-color: {C.bg_elevated};")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(12, 0, 12, 0)

        size_mb = file_info.get("size", 0) / 1024 / 1024
        info_text = (
            f"#{file_info.get('id', 'N/A')} | "
            f"{file_info.get('category', 'N/A')} | "
            f"{size_mb:.1f}MB"
        )
        info_label = QLabel(info_text)
        info_label.setStyleSheet(f"color: {C.text_secondary}; font-size: 12px;")
        info_layout.addWidget(info_label)

        info_layout.addStretch()

        tags = file_info.get("tags", "")
        tags_preview = tags[:80] + ("..." if len(tags) > 80 else "")
        tags_label = QLabel(tags_preview)
        tags_label.setStyleSheet(f"color: {C.text_muted}; font-size: 11px;")
        info_layout.addWidget(tags_label)

        layout.addWidget(info_bar)

        # resize 防抖定时器
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._load_image)

        QTimer.singleShot(50, self._load_image)

    def _load_image(self) -> None:
        """加载预览图。"""
        if self._load_pending:
            return
        self._load_pending = True

        path = self.file_info.get("path", "")
        if not path or not os.path.exists(path):
            self.image_label.setText("文件不存在")
            self.image_label.setStyleSheet(f"color: {C.error};")
            self._load_pending = False
            return

        max_width = max(100, self.width() - 20)
        max_height = max(100, self.height() - 80)

        try:
            pixmap = self._load_image_impl(path, max_width, max_height)
            if pixmap and not pixmap.isNull():
                self.image_label.setPixmap(pixmap)
                self.image_label.setStyleSheet("")
            else:
                self.image_label.setText("加载失败")
                self.image_label.setStyleSheet(f"color: {C.error};")
        except Exception as e:
            logger.error("预览加载失败: %s", e)
            self.image_label.setText(f"加载失败: {e}")
            self.image_label.setStyleSheet(f"color: {C.error};")
        finally:
            self._load_pending = False

    def _load_image_impl(
        self, path: str, max_width: int, max_height: int
    ) -> Optional[QPixmap]:
        """执行图片加载。"""
        if HAS_PIL:
            img: Optional[Image.Image] = None
            try:
                img = Image.open(path)

                if HAS_IMAGEOPS:
                    try:
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        pass

                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

                if img.mode not in ("RGBA", "RGB"):
                    img = img.convert("RGBA")

                if img.mode == "RGBA":
                    data = img.tobytes("raw", "RGBA")
                    qimage = QImage(
                        data,
                        img.width,
                        img.height,
                        img.width * 4,
                        QImage.Format.Format_RGBA8888,
                    )
                else:
                    data = img.tobytes("raw", "RGB")
                    qimage = QImage(
                        data,
                        img.width,
                        img.height,
                        img.width * 3,
                        QImage.Format.Format_RGB888,
                    )

                return QPixmap.fromImage(qimage.copy())
            finally:
                if img is not None:
                    try:
                        img.close()
                    except Exception:
                        pass
        else:
            from PyQt6.QtGui import QImageReader

            reader = QImageReader(path)
            reader.setAutoTransform(True)
            reader.setScaledSize(QSize(max_width, max_height))
            qimage = reader.read()
            return QPixmap.fromImage(qimage)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """按键处理。"""
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口大小变化 - 防抖重新加载。"""
        super().resizeEvent(event)
        self._load_pending = False  # 允许新的加载
        self._resize_timer.start()