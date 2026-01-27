# 📄 ui/favorites_manager.py
"""收藏管理器模块 - 性能优化版。

本模块提供收藏图片的浏览、预览、删除等功能，
支持分类筛选、标签搜索和缩略图显示。

性能优化:
    - 异步文件扫描（后台线程）
    - 异步缩略图加载（线程池）
    - 虚拟滚动（只渲染可见区域）
    - 分批渲染（避免主线程阻塞）
    - 磁盘缓存（避免重复生成缩略图）

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
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from PyQt6.QtCore import (
    Qt,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QCursor, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import CONFIG
from config.design_tokens import TOKENS

if TYPE_CHECKING:
    from PyQt6.QtGui import QMouseEvent

logger = logging.getLogger(__name__)

# 设计令牌快捷引用
C = TOKENS.colors
T = TOKENS.typography
S = TOKENS.spacing
L = TOKENS.layout

# 检测 PIL 可用性
try:
    from PIL import Image
    from PIL.ImageQt import ImageQt

    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PIL 不可用，缩略图生成功能受限")


# =============================================================================
# 磁盘缩略图缓存
# =============================================================================


class ThumbnailCache:
    """磁盘缩略图缓存管理器。

    使用文件路径+修改时间的哈希作为缓存键，
    避免重复生成缩略图。

    Attributes:
        cache_dir: 缓存目录路径。
    """

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        """初始化缓存管理器。

        Args:
            cache_dir: 缓存目录路径，默认使用应用数据目录。
        """
        if cache_dir is None:
            # 使用应用数据目录下的缓存文件夹
            app_data = Path(os.environ.get("APPDATA", Path.home() / ".cache"))
            cache_dir = str(app_data / "yande_viewer" / "thumb_cache")

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存（LRU 简化版）
        self._memory_cache: Dict[str, QPixmap] = {}
        self._memory_order: List[str] = []
        self._max_memory_items = 150

    def _get_cache_key(self, path: str, mtime: float) -> str:
        """生成缓存键。

        Args:
            path: 文件路径。
            mtime: 文件修改时间。

        Returns:
            MD5 哈希字符串。
        """
        content = f"{path}:{mtime}:{CONFIG.thumbnail_size}".encode()
        return hashlib.md5(content).hexdigest()

    def get(self, path: str, mtime: float) -> Optional[QPixmap]:
        """获取缓存的缩略图。

        Args:
            path: 文件路径。
            mtime: 文件修改时间。

        Returns:
            缓存的 QPixmap，不存在返回 None。
        """
        key = self._get_cache_key(path, mtime)

        # 先检查内存缓存
        if key in self._memory_cache:
            # 移动到列表末尾（LRU）
            if key in self._memory_order:
                self._memory_order.remove(key)
                self._memory_order.append(key)
            return self._memory_cache[key]

        # 检查磁盘缓存
        cache_path = self.cache_dir / f"{key}.jpg"
        if cache_path.exists():
            try:
                pixmap = QPixmap(str(cache_path))
                if not pixmap.isNull():
                    self._add_to_memory(key, pixmap)
                    return pixmap
            except Exception as e:
                logger.debug("读取缓存失败 [%s]: %s", cache_path, e)

        return None

    def put(self, path: str, mtime: float, pixmap: QPixmap) -> None:
        """存储缩略图到缓存。

        Args:
            path: 文件路径。
            mtime: 文件修改时间。
            pixmap: 缩略图。
        """
        key = self._get_cache_key(path, mtime)

        # 存入内存缓存
        self._add_to_memory(key, pixmap)

        # 存入磁盘缓存
        cache_path = self.cache_dir / f"{key}.jpg"
        try:
            pixmap.save(str(cache_path), "JPEG", 85)
        except Exception as e:
            logger.debug("保存缓存失败: %s", e)

    def _add_to_memory(self, key: str, pixmap: QPixmap) -> None:
        """添加到内存缓存，必要时淘汰旧条目。"""
        # 如果已存在，先移除
        if key in self._memory_cache:
            self._memory_order.remove(key)

        # 检查容量，淘汰最旧的
        while len(self._memory_cache) >= self._max_memory_items:
            if self._memory_order:
                oldest = self._memory_order.pop(0)
                self._memory_cache.pop(oldest, None)
            else:
                break

        self._memory_cache[key] = pixmap
        self._memory_order.append(key)

    def clear_memory(self) -> None:
        """清空内存缓存。"""
        self._memory_cache.clear()
        self._memory_order.clear()


# 全局缓存实例
_thumbnail_cache = ThumbnailCache()


# =============================================================================
# 异步文件扫描器
# =============================================================================


class FileScannerSignals(QObject):
    """文件扫描器信号定义。"""

    progress = pyqtSignal(int, int)  # (已扫描, 总数)
    finished = pyqtSignal(list)  # 完成，携带文件列表
    error = pyqtSignal(str)  # 错误信息


class FileScanner(QThread):
    """异步文件扫描线程。

    在后台扫描收藏目录，避免阻塞主线程。
    """

    SUPPORTED_FORMATS: frozenset[str] = frozenset(
        {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    )

    def __init__(self, base_dir: str, parent: Optional[QObject] = None) -> None:
        """初始化扫描器。

        Args:
            base_dir: 收藏根目录。
            parent: 父对象。
        """
        super().__init__(parent)
        self.base_dir = base_dir
        self.signals = FileScannerSignals()
        self._cancelled = False

    def cancel(self) -> None:
        """取消扫描。"""
        self._cancelled = True

    def run(self) -> None:
        """执行扫描任务。"""
        try:
            all_files: List[Dict[str, Any]] = []
            categories = ["Safe", "Questionable", "Explicit"]

            # 首先计算总数
            total_count = 0
            for category in categories:
                folder = Path(self.base_dir) / category
                if folder.exists():
                    for f in folder.iterdir():
                        if (
                            f.suffix.lower() in self.SUPPORTED_FORMATS
                            and f.suffix != ".tmp"
                        ):
                            total_count += 1

            scanned = 0
            for category in categories:
                if self._cancelled:
                    return

                folder = Path(self.base_dir) / category
                if not folder.exists():
                    continue

                for file_path in folder.iterdir():
                    if self._cancelled:
                        return

                    if file_path.suffix == ".tmp":
                        continue
                    if file_path.suffix.lower() not in self.SUPPORTED_FORMATS:
                        continue

                    try:
                        stat = file_path.stat()
                    except OSError:
                        continue

                    name = file_path.stem
                    parts = name.split("_", 1)

                    file_info = {
                        "path": str(file_path),
                        "filename": file_path.name,
                        "category": category,
                        "id": parts[0],
                        "tags": parts[1].replace("_", " ") if len(parts) > 1 else "",
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }

                    all_files.append(file_info)
                    scanned += 1

                    # 每 20 个文件发送一次进度
                    if scanned % 20 == 0:
                        self.signals.progress.emit(scanned, total_count)

            # 按修改时间降序排序
            all_files.sort(key=lambda x: x["mtime"], reverse=True)
            self.signals.finished.emit(all_files)

        except Exception as e:
            logger.error("文件扫描失败: %s", e)
            self.signals.error.emit(str(e))


# =============================================================================
# 异步缩略图加载器
# =============================================================================


class ThumbnailSignals(QObject):
    """缩略图加载信号。"""

    ready = pyqtSignal(str, object)  # (路径, QPixmap)
    failed = pyqtSignal(str, str)  # (路径, 错误信息)


class ThumbnailTask(QRunnable):
    """缩略图加载任务。

    在线程池中执行，完成后通过信号通知主线程。
    """

    def __init__(
        self,
        path: str,
        mtime: float,
        size: tuple[int, int],
        signals: ThumbnailSignals,
    ) -> None:
        """初始化任务。

        Args:
            path: 文件路径。
            mtime: 修改时间。
            size: 目标尺寸。
            signals: 信号对象。
        """
        super().__init__()
        self.path = path
        self.mtime = mtime
        self.size = size
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        """执行加载任务。"""
        try:
            # 检查缓存
            cached = _thumbnail_cache.get(self.path, self.mtime)
            if cached is not None:
                self.signals.ready.emit(self.path, cached)
                return

            # 生成缩略图
            pixmap = self._generate_thumbnail()
            if pixmap is not None:
                _thumbnail_cache.put(self.path, self.mtime, pixmap)
                self.signals.ready.emit(self.path, pixmap)
            else:
                self.signals.failed.emit(self.path, "生成失败")

        except Exception as e:
            self.signals.failed.emit(self.path, str(e))

    def _generate_thumbnail(self) -> Optional[QPixmap]:
        """生成缩略图。

        Returns:
            QPixmap 或 None。
        """
        if not os.path.exists(self.path):
            return None

        try:
            if HAS_PIL:
                with Image.open(self.path) as img:
                    img.thumbnail(self.size, Image.Resampling.LANCZOS)
                    if img.mode not in ("RGBA", "RGB"):
                        img = img.convert("RGBA")
                    qimg = ImageQt(img)
                    return QPixmap.fromImage(qimg)
            else:
                pixmap = QPixmap(self.path)
                if pixmap.isNull():
                    return None
                return pixmap.scaled(
                    self.size[0],
                    self.size[1],
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        except Exception as e:
            logger.debug("缩略图生成失败 [%s]: %s", self.path, e)
            return None


class ThumbnailLoader(QObject):
    """缩略图加载管理器。

    使用线程池异步加载，支持优先级和去重。
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """初始化加载器。"""
        super().__init__(parent)
        self.signals = ThumbnailSignals()
        self._pending: Set[str] = set()

        # 使用全局线程池，限制并发
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(min(4, self._pool.maxThreadCount()))

    def load(self, path: str, mtime: float, size: tuple[int, int]) -> bool:
        """请求加载缩略图。

        Args:
            path: 文件路径。
            mtime: 修改时间。
            size: 目标尺寸。

        Returns:
            是否成功提交请求（False 表示已在队列中）。
        """
        if path in self._pending:
            return False

        # 先检查内存缓存，同步返回
        cached = _thumbnail_cache.get(path, mtime)
        if cached is not None:
            self.signals.ready.emit(path, cached)
            return True

        self._pending.add(path)
        task = ThumbnailTask(path, mtime, size, self.signals)
        self._pool.start(task)
        return True

    def on_complete(self, path: str) -> None:
        """任务完成回调，清理 pending 状态。"""
        self._pending.discard(path)

    def clear(self) -> None:
        """清空等待队列。"""
        self._pending.clear()


# =============================================================================
# 懒加载卡片
# =============================================================================


class LazyCard(QFrame):
    """懒加载卡片组件。

    初始只显示占位符，进入可视区域后再加载缩略图。

    Signals:
        clicked: 左键点击信号。
        context_menu: 右键菜单信号。
    """

    clicked = pyqtSignal(dict)
    context_menu = pyqtSignal(dict, object)

    CATEGORY_COLORS: Dict[str, str] = {
        "Safe": C.success,
        "Questionable": C.warning,
        "Explicit": C.accent,
    }

    def __init__(
        self,
        file_info: Dict[str, Any],
        thumb_size: tuple[int, int],
        parent: Optional[QWidget] = None,
    ) -> None:
        """初始化卡片。

        Args:
            file_info: 文件信息字典。
            thumb_size: 缩略图尺寸。
            parent: 父组件。
        """
        super().__init__(parent)

        self.file_info = file_info
        self.thumb_size = thumb_size
        self._loaded = False

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {C.bg_surface};
                border-radius: {L.radius_md}px;
            }}
        """)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 缩略图区域
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(*self.thumb_size)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {C.bg_hover};
                border-radius: {L.radius_sm}px;
                color: {C.text_muted};
                font-size: 20px;
            }}
        """)
        self.thumb_label.setText("⏳")
        layout.addWidget(self.thumb_label)

        # ID 标签
        id_label = QLabel(f"#{self.file_info['id']}")
        id_label.setStyleSheet(f"""
            color: {C.text_primary};
            font-family: {T.font_mono};
            font-size: 9px;
        """)
        id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(id_label)

        # 分类和大小
        color = self.CATEGORY_COLORS.get(self.file_info["category"], C.text_muted)
        size_mb = self.file_info["size"] / 1024 / 1024
        info_label = QLabel(f"{self.file_info['category'][:1]} · {size_mb:.1f}MB")
        info_label.setStyleSheet(f"color: {color}; font-size: 8px;")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        """设置缩略图。"""
        self._loaded = True
        scaled = pixmap.scaled(
            *self.thumb_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)
        self.thumb_label.setStyleSheet("")

    def set_failed(self) -> None:
        """设置加载失败状态。"""
        self._loaded = True
        self.thumb_label.setText("⚠")
        self.thumb_label.setStyleSheet(f"""
            color: {C.warning};
            font-size: 24px;
            background-color: {C.bg_hover};
            border-radius: {L.radius_sm}px;
        """)

    def is_loaded(self) -> bool:
        """是否已加载。"""
        return self._loaded

    def mousePressEvent(self, event: "QMouseEvent") -> None:
        """鼠标点击事件。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.file_info)
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_menu.emit(self.file_info, event)
        super().mousePressEvent(event)


# =============================================================================
# 虚拟滚动容器
# =============================================================================


class VirtualScrollArea(QScrollArea):
    """虚拟滚动区域。

    只渲染可见区域的卡片，大幅减少内存和 CPU 占用。

    Signals:
        thumbnail_needed: 需要加载缩略图信号。
        card_clicked: 卡片点击信号。
        card_context_menu: 卡片右键菜单信号。
    """

    thumbnail_needed = pyqtSignal(list)
    card_clicked = pyqtSignal(dict)
    card_context_menu = pyqtSignal(dict, object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """初始化虚拟滚动区域。"""
        super().__init__(parent)

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {C.bg_base};
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
        """)

        # 数据
        self._files: List[Dict[str, Any]] = []
        self._cards: Dict[str, LazyCard] = {}  # path -> card
        self._visible_paths: Set[str] = set()

        # 布局参数
        self._card_width = 180
        self._card_height = 220
        self._spacing = 10
        self._cols = 5
        self._padding = 12

        # 内容容器
        self.content = QWidget()
        self.content.setStyleSheet("background: transparent;")
        self.setWidget(self.content)

        # 防抖更新定时器
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(30)
        self._update_timer.timeout.connect(self._update_visible)

        self.verticalScrollBar().valueChanged.connect(self._schedule_update)

    def set_files(self, files: List[Dict[str, Any]]) -> None:
        """设置文件列表。

        Args:
            files: 文件信息列表。
        """
        # 清除所有卡片
        for card in self._cards.values():
            card.deleteLater()
        self._cards.clear()
        self._visible_paths.clear()

        self._files = files
        self._recalculate_layout()
        self._schedule_update()

    def _recalculate_layout(self) -> None:
        """重新计算布局参数。"""
        viewport_width = self.viewport().width()
        usable_width = viewport_width - 2 * self._padding

        self._cols = max(1, usable_width // (self._card_width + self._spacing))

        # 重新计算卡片宽度以填满
        total_spacing = (self._cols - 1) * self._spacing
        self._card_width = (usable_width - total_spacing) // self._cols

        # 计算总高度
        rows = (len(self._files) + self._cols - 1) // self._cols if self._files else 0
        content_height = (
            2 * self._padding
            + rows * self._card_height
            + max(0, rows - 1) * self._spacing
        )

        self.content.setFixedSize(viewport_width, max(content_height, 100))

    def _schedule_update(self) -> None:
        """调度可见区域更新。"""
        self._update_timer.start()

    def _update_visible(self) -> None:
        """更新可见区域的卡片。"""
        if not self._files:
            return

        scroll_y = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()

        row_height = self._card_height + self._spacing
        buffer = 2  # 缓冲行数

        first_row = max(0, (scroll_y - self._padding) // row_height - buffer)
        last_row = (scroll_y + viewport_height - self._padding) // row_height + buffer

        start_idx = first_row * self._cols
        end_idx = min((last_row + 1) * self._cols, len(self._files))

        # 计算当前应该可见的路径
        new_visible = set()
        for i in range(start_idx, end_idx):
            if i < len(self._files):
                new_visible.add(self._files[i]["path"])

        # 移除不再可见的卡片
        to_remove = self._visible_paths - new_visible
        for path in to_remove:
            if path in self._cards:
                self._cards[path].deleteLater()
                del self._cards[path]

        # 创建新可见的卡片
        thumb_size = CONFIG.thumbnail_size
        need_load = []

        for i in range(start_idx, end_idx):
            if i >= len(self._files):
                break

            file_info = self._files[i]
            path = file_info["path"]

            if path in self._cards:
                continue

            row = i // self._cols
            col = i % self._cols
            x = self._padding + col * (self._card_width + self._spacing)
            y = self._padding + row * (self._card_height + self._spacing)

            card = LazyCard(file_info, thumb_size, self.content)
            card.setGeometry(x, y, self._card_width, self._card_height)
            card.clicked.connect(self.card_clicked.emit)
            card.context_menu.connect(self.card_context_menu.emit)
            card.show()

            self._cards[path] = card
            need_load.append({"path": path, "mtime": file_info["mtime"]})

        self._visible_paths = new_visible

        if need_load:
            self.thumbnail_needed.emit(need_load)

    def set_thumbnail(self, path: str, pixmap: QPixmap) -> None:
        """设置卡片缩略图。"""
        if path in self._cards:
            self._cards[path].set_thumbnail(pixmap)

    def set_failed(self, path: str) -> None:
        """设置卡片加载失败。"""
        if path in self._cards:
            self._cards[path].set_failed()

    def resizeEvent(self, event) -> None:
        """窗口大小变化。"""
        super().resizeEvent(event)
        self._recalculate_layout()
        # 重新定位所有可见卡片
        for path in list(self._cards.keys()):
            self._cards[path].deleteLater()
            del self._cards[path]
        self._visible_paths.clear()
        self._schedule_update()


# =============================================================================
# 收藏管理器
# =============================================================================


class FavoritesManager:
    """收藏管理器入口类。"""

    def __init__(self, parent: QWidget, base_dir: str) -> None:
        """初始化。

        Args:
            parent: 父窗口。
            base_dir: 收藏根目录。
        """
        self.parent = parent
        self.base_dir = base_dir
        self.window: Optional[FavoritesWindow] = None

    def show(self) -> None:
        """显示管理器窗口。"""
        if self.window is not None and self.window.isVisible():
            self.window.raise_()
            self.window.activateWindow()
            return

        self.window = FavoritesWindow(self.parent, self.base_dir, self)
        self.window.show()


class FavoritesWindow(QMainWindow):
    """收藏管理器窗口 - 性能优化版。"""

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
        self.all_files: List[Dict[str, Any]] = []
        self.filtered_files: List[Dict[str, Any]] = []

        # 异步组件
        self._scanner: Optional[FileScanner] = None
        self._thumb_loader = ThumbnailLoader(self)
        self._thumb_loader.signals.ready.connect(self._on_thumb_ready)
        self._thumb_loader.signals.failed.connect(self._on_thumb_failed)

        # 窗口配置
        self.setWindowTitle("📁 收藏管理器")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(f"background-color: {C.bg_base};")

        self._setup_ui()
        self._start_scan()

        # 居中
        if parent:
            self.move(
                parent.x() + (parent.width() - 1000) // 2,
                parent.y() + (parent.height() - 700) // 2,
            )

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

        # 虚拟滚动区域
        self.scroll_area = VirtualScrollArea()
        self.scroll_area.thumbnail_needed.connect(self._load_thumbnails)
        self.scroll_area.card_clicked.connect(self._preview)
        self.scroll_area.card_context_menu.connect(self._show_context_menu)
        self.scroll_area.hide()
        layout.addWidget(self.scroll_area)

    def _create_toolbar(self) -> QFrame:
        """创建工具栏。"""
        toolbar = QFrame()
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet(f"background-color: {C.bg_elevated};")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(12, 8, 12, 8)

        # 过滤按钮
        self.filter_group = QButtonGroup(self)
        self.filter_buttons: Dict[str, QRadioButton] = {}

        for name in ["All", "Safe", "Questionable", "Explicit"]:
            rb = QRadioButton(name)
            rb.setStyleSheet(f"color: {C.text_primary}; font-size: 11px;")
            if name == "All":
                rb.setChecked(True)
            rb.toggled.connect(self._apply_filter)
            self.filter_group.addButton(rb)
            self.filter_buttons[name] = rb
            layout.addWidget(rb)

        layout.addSpacing(20)

        # 搜索框
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
        # 搜索防抖
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._apply_filter)
        self.search_input.textChanged.connect(lambda: self._search_timer.start())
        layout.addWidget(self.search_input)

        layout.addStretch()

        # 统计
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet(f"color: {C.text_muted}; font-size: 12px;")
        layout.addWidget(self.stats_label)

        # 刷新按钮
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

        # 打开文件夹
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
        if self._scanner is not None:
            self._scanner.cancel()
            self._scanner.wait()

        self.loading_label.setText("正在扫描文件...")
        self.loading_label.show()
        self.scroll_area.hide()

        self._scanner = FileScanner(self.base_dir, self)
        self._scanner.signals.progress.connect(self._on_scan_progress)
        self._scanner.signals.finished.connect(self._on_scan_finished)
        self._scanner.signals.error.connect(self._on_scan_error)
        self._scanner.start()

    def _on_scan_progress(self, done: int, total: int) -> None:
        """扫描进度回调。"""
        self.loading_label.setText(f"正在扫描... {done}/{total}")

    def _on_scan_finished(self, files: List[Dict[str, Any]]) -> None:
        """扫描完成回调。"""
        self.all_files = files
        self.loading_label.hide()
        self.scroll_area.show()
        self._apply_filter()
        logger.info("扫描完成，共 %d 个文件", len(files))

    def _on_scan_error(self, error: str) -> None:
        """扫描错误回调。"""
        self.loading_label.setText(f"扫描失败: {error}")
        logger.error("扫描失败: %s", error)

    def _apply_filter(self) -> None:
        """应用筛选。"""
        category = "All"
        for name, btn in self.filter_buttons.items():
            if btn.isChecked():
                category = name
                break

        query = self.search_input.text().lower().strip()

        self.filtered_files = [
            f
            for f in self.all_files
            if (category == "All" or f["category"] == category)
            and (not query or query in f["tags"].lower())
        ]

        self.stats_label.setText(
            f"{len(self.filtered_files)} / {len(self.all_files)}"
        )
        self.scroll_area.set_files(self.filtered_files)

    def _load_thumbnails(self, items: List[Dict[str, Any]]) -> None:
        """加载缩略图请求。"""
        thumb_size = CONFIG.thumbnail_size
        for item in items:
            self._thumb_loader.load(item["path"], item["mtime"], thumb_size)

    def _on_thumb_ready(self, path: str, pixmap: QPixmap) -> None:
        """缩略图加载完成。"""
        self._thumb_loader.on_complete(path)
        self.scroll_area.set_thumbnail(path, pixmap)

    def _on_thumb_failed(self, path: str, error: str) -> None:
        """缩略图加载失败。"""
        self._thumb_loader.on_complete(path)
        self.scroll_area.set_failed(path)

    def _preview(self, file_info: Dict[str, Any]) -> None:
        """预览图片。"""
        try:
            dialog = PreviewDialog(self, file_info)
            dialog.exec()
        except Exception as e:
            logger.error("预览失败: %s", e)
            QMessageBox.warning(self, "错误", f"预览失败: {e}")

    def _show_context_menu(
        self,
        file_info: Dict[str, Any],
        event: "QMouseEvent",
    ) -> None:
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
            lambda: self._open_location(file_info["path"])
        )
        menu.addAction(open_action)

        menu.addSeparator()

        delete_action = QAction("🗑 删除", self)
        delete_action.triggered.connect(lambda: self._delete(file_info))
        menu.addAction(delete_action)

        menu.exec(self.cursor().pos())

    def _open_folder(self) -> None:
        """打开收藏文件夹。"""
        path = os.path.abspath(self.base_dir)
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(path)
            elif system == "Darwin":
                subprocess.run(["open", path], check=False, capture_output=True)
            else:
                subprocess.run(["xdg-open", path], check=False, capture_output=True)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开: {e}")

    def _open_location(self, filepath: str) -> None:
        """打开文件所在位置。"""
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
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除 {file_info['filename']} ？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(file_info["path"])
                self.all_files.remove(file_info)
                self._apply_filter()
                logger.info("已删除: %s", file_info["filename"])
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    def closeEvent(self, event) -> None:
        """窗口关闭。"""
        if self._scanner is not None:
            self._scanner.cancel()
            self._scanner.wait()

        self._thumb_loader.clear()
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

        self.setWindowTitle(f"预览 - #{file_info['id']}")
        self.setMinimumSize(900, 700)
        self.setStyleSheet(f"background-color: {C.bg_base};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel("加载中...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(f"color: {C.text_muted};")
        layout.addWidget(self.image_label)

        # 延迟加载避免阻塞
        QTimer.singleShot(50, self._load_image)

    def _load_image(self) -> None:
        """加载预览图。"""
        path = self.file_info["path"]
        try:
            if HAS_PIL:
                with Image.open(path) as img:
                    img.thumbnail((880, 650), Image.Resampling.LANCZOS)
                    if img.mode not in ("RGBA", "RGB"):
                        img = img.convert("RGBA")
                    qimg = ImageQt(img)
                    pixmap = QPixmap.fromImage(qimg)
            else:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        880,
                        650,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

            if pixmap and not pixmap.isNull():
                self.image_label.setPixmap(pixmap)
                self.image_label.setStyleSheet("")
            else:
                self.image_label.setText("加载失败")
                self.image_label.setStyleSheet(f"color: {C.error};")
        except Exception as e:
            logger.error("预览加载失败: %s", e)
            self.image_label.setText("加载失败")
            self.image_label.setStyleSheet(f"color: {C.error};")

    def keyPressEvent(self, event) -> None:
        """按键处理。"""
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.accept()
        else:
            super().keyPressEvent(event)