"""
Yande.re Ultimate Viewer - 主窗口模块

本模块实现了应用程序的主窗口界面，提供图像浏览、收藏管理、
筛选控制等核心功能。基于 PyQt6 构建，支持键盘快捷键操作。

版权所有 (c) 2024 Yande Viewer Team
遵循 MIT 许可证发布

模块功能:
    - 图像浏览与展示
    - 收藏与下载管理
    - 评级与分数筛选
    - 浏览历史记录
    - 后台预加载优化

依赖:
    - PyQt6: GUI框架
    - Pillow: 图像处理
    - requests: 网络请求（通过session模块）

示例:
    >>> from ui.main_window import MainWindow
    >>> window = MainWindow()
    >>> window.show()
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import (
    QMutex,
    QObject,
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# 本地模块导入
from config.app_config import CONFIG, logger
from config.design_tokens import TOKENS
from config.user_settings import FilterSettings, UserSettings
from core.cache import LRUCache
from core.download_manager import DownloadManager
from core.preloader import TurboPreloader
from core.session import SESSION
from ui.components import (
    ActionButton,
    ButtonStyle,
    FavoriteButton,
    IconButton,
    MetadataBar,
    NavButton,
    ScoreSelector,
    SegmentedControl,
    ShortcutOverlay,
    StatBadge,
    TagCloud,
    Toast,
)
from ui.dialogs.backup_dialog import BackupRestoreDialog
from ui.dialogs.mode_select import ModeSelectDialog
from ui.dialogs.settings_dialog import SettingsDialog
from ui.favorites_manager import FavoritesManager
from ui.widgets.loading_widget import LoadingWidget
from utils.helpers import safe_json_load, safe_json_save
from utils.ime_controller import IMEController
from utils.security import url_validator

if TYPE_CHECKING:
    from PyQt6.QtGui import QCloseEvent, QResizeEvent

# =============================================================================
# 模块级常量
# =============================================================================

MODE_LATEST: int = 1
"""最新模式：浏览最新发布的图片"""

MODE_CONTINUE: int = 2
"""续看模式：从上次浏览位置继续"""


# =============================================================================
# 辅助类
# =============================================================================

class QMutexLocker:
    """
    QMutex 的上下文管理器封装。
    
    PyQt6 移除了内置的 QMutexLocker 类，此类提供相同功能，
    确保互斥锁在代码块结束时自动释放。
    
    Attributes:
        _mutex: 被管理的互斥锁对象
    
    Example:
        >>> mutex = QMutex()
        >>> with QMutexLocker(mutex):
        ...     # 临界区代码
        ...     pass
    """
    
    def __init__(self, mutex: QMutex) -> None:
        """
        初始化锁管理器。
        
        Args:
            mutex: 需要管理的 QMutex 实例
        """
        self._mutex = mutex
    
    def __enter__(self) -> "QMutexLocker":
        """进入上下文时获取锁。"""
        self._mutex.lock()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """退出上下文时释放锁。"""
        self._mutex.unlock()
        return False


class WorkerSignals(QObject):
    """
    工作线程信号集合。
    
    定义后台线程与主线程通信的所有信号。遵循 Qt 的信号槽机制，
    确保跨线程操作的线程安全性。
    
    Signals:
        image_loaded: 图像加载完成信号，参数为 (PIL.Image, post_id)
        posts_loaded: 帖子列表加载完成信号，参数为 [post_dict, ...]
        error: 错误发生信号，参数为错误消息字符串
        log: 日志输出信号，参数为 (message, color)
        download_complete: 下载完成信号，参数为 (post_id, path)
        download_error: 下载错误信号，参数为 (post_id, error)
        request_reload: 请求重新加载数据信号
        update_ui_signal: UI 更新信号，参数为包含更新数据的字典
    """
    
    image_loaded = pyqtSignal(object, str)
    posts_loaded = pyqtSignal(list)
    error = pyqtSignal(str)
    log = pyqtSignal(str, str)
    download_complete = pyqtSignal(str, str)
    download_error = pyqtSignal(str, str)
    request_reload = pyqtSignal()
    update_ui_signal = pyqtSignal(dict)


# =============================================================================
# 主窗口类
# =============================================================================

class MainWindow(QMainWindow):
    """
    Yande.re Ultimate Viewer 主窗口。
    
    应用程序的核心窗口类，负责整合所有 UI 组件并协调各子系统的工作。
    采用 MVC 架构思想，将数据管理、业务逻辑与界面展示分离。
    
    Attributes:
        MAX_EMPTY_PAGE_RETRIES: 空页面最大重试次数，防止无限循环
        signals: 工作线程信号对象
        user_settings: 用户设置对象
        post_queue: 待浏览的帖子队列
        browse_history: 浏览历史记录
        current_post: 当前显示的帖子
        image_cache: 图像 LRU 缓存
        preloader: 图像预加载器
        download_manager: 下载管理器
    
    Example:
        >>> app = QApplication(sys.argv)
        >>> window = MainWindow()
        >>> window.show()
        >>> sys.exit(app.exec())
    """
    
    MAX_EMPTY_PAGE_RETRIES: int = 5
    """连续空页面的最大重试次数"""
    
    def __init__(self) -> None:
        """
        初始化主窗口。
        
        执行以下初始化步骤：
        1. 设置窗口基本属性（标题、尺寸、样式）
        2. 初始化信号连接
        3. 加载用户数据（设置、历史、收藏）
        4. 初始化缓存与下载系统
        5. 延迟显示模式选择对话框
        """
        super().__init__()
        
        # 窗口基本设置
        self.setWindowTitle("Yande.re Ultimate Viewer")
        self.setGeometry(100, 100, 1300, 900)
        self.setMinimumSize(800, 600)
        
        # 应用背景色以防止启动时闪烁
        bg_color = CONFIG.colors.bg_base
        self.setStyleSheet(f"background-color: {bg_color};")
        
        # 初始化信号系统
        self.signals = WorkerSignals()
        self._connect_signals()
        
        # 输入法控制器
        self.ime = IMEController()
        
        # 创建必要的文件夹
        self._init_folders()
        
        # 加载用户设置
        self.user_settings = UserSettings.load(CONFIG.settings_file)
        
        # 扫描待恢复的临时文件
        self.pending_tmp_files: List[Dict] = self._scan_tmp_files()
        
        # 线程同步锁（使用 Qt 的 QMutex 替代 threading.Lock）
        self._state_mutex = QMutex()
        self._api_mutex = QMutex()
        self._page_mutex = QMutex()
        
        # 加载持久化数据
        self.viewed_ids: Set[str] = safe_json_load(
            CONFIG.history_file, default=set, as_set=True
        )
        self.favorites: Dict = safe_json_load(
            CONFIG.favorites_file, default=dict
        )
        self.saved_browse_history: List = safe_json_load(
            CONFIG.browse_history_file, default=list
        )
        self.session: Dict = safe_json_load(
            CONFIG.session_file, default=dict
        )
        
        # 构建已下载文件的 ID 集合
        self.downloaded_ids: Set[str] = self._build_downloaded_ids()
        
        # 运行时状态
        self.post_queue: deque = deque()
        self.browse_history: List[dict] = []
        self.history_index: int = -1
        self.current_post: Optional[dict] = None
        
        # 分页状态（私有，通过属性访问以确保线程安全）
        self._page: int = 1
        self.mode: int = MODE_LATEST
        self._empty_page_retries: int = 0
        
        # 缓存与后台服务
        self.image_cache = LRUCache(self.user_settings.performance.max_image_cache)
        self.preloader = TurboPreloader(self.image_cache)
        self.download_manager = DownloadManager(
            max_workers=self.user_settings.performance.download_workers
        )
        
        # 图像引用保持（防止 GC 过早回收）
        self._current_display_image: Optional[Image.Image] = None
        self.original_pil_image: Optional[Image.Image] = None
        
        # UI 状态
        self.resize_timer: Optional[QTimer] = None
        self._is_loading_api: bool = False
        self.is_fullscreen: bool = False
        self.last_next_time: float = 0.0
        
        # 收藏夹管理器
        self.fav_manager = FavoritesManager(self, CONFIG.base_dir)
        
        # 筛选状态
        self.filter_active: bool = self._is_filter_active()
        self.filtered_out_count: int = 0
        
        # UI 初始化完成标志
        self._ui_initialized: bool = False
        
        # 状态更新定时器
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status_loop)
        
        # 延迟显示模式对话框（确保窗口先创建完成）
        self.hide()
        QTimer.singleShot(100, self._show_mode_dialog)
    
    # =========================================================================
    # 信号连接
    # =========================================================================
    
    def _connect_signals(self) -> None:
        """
        连接所有工作线程信号到对应槽函数。
        
        集中管理信号连接，便于维护和调试。
        """
        self.signals.image_loaded.connect(self._on_image_loaded_slot)
        self.signals.posts_loaded.connect(self._on_posts_loaded_slot)
        self.signals.error.connect(self._on_error_slot)
        self.signals.log.connect(self._on_log_slot)
        self.signals.download_complete.connect(self._on_download_complete_slot)
        self.signals.download_error.connect(self._on_download_error_slot)
        self.signals.request_reload.connect(self._on_request_reload_slot)
        self.signals.update_ui_signal.connect(self.update_ui)
    
    # =========================================================================
    # 线程安全属性
    # =========================================================================
    
    @property
    def page(self) -> int:
        """
        当前 API 分页页码（线程安全）。
        
        Returns:
            当前页码，从 1 开始
        """
        with QMutexLocker(self._page_mutex):
            return self._page
    
    @page.setter
    def page(self, value: int) -> None:
        """设置当前页码。"""
        with QMutexLocker(self._page_mutex):
            self._page = max(1, value)  # 确保页码不小于 1
    
    @property
    def is_loading_api(self) -> bool:
        """
        API 是否正在加载中（线程安全）。
        
        Returns:
            True 表示正在加载，False 表示空闲
        """
        with QMutexLocker(self._api_mutex):
            return self._is_loading_api
    
    @is_loading_api.setter
    def is_loading_api(self, value: bool) -> None:
        """设置 API 加载状态。"""
        with QMutexLocker(self._api_mutex):
            self._is_loading_api = value
    
    @contextmanager
    def _state_lock(self):
        """
        状态数据访问的上下文管理器。
        
        用于保护 viewed_ids、favorites、downloaded_ids 等共享数据的访问。
        
        Yields:
            无返回值，仅提供锁保护
        
        Example:
            >>> with self._state_lock():
            ...     self.viewed_ids.add(post_id)
        """
        self._state_mutex.lock()
        try:
            yield
        finally:
            self._state_mutex.unlock()
    
    # =========================================================================
    # 初始化方法
    # =========================================================================
    
    def _init_folders(self) -> None:
        """
        创建必要的存储目录。
        
        根据图片评级创建三个子目录：Safe、Questionable、Explicit。
        """
        for sub in ["Safe", "Questionable", "Explicit"]:
            Path(CONFIG.base_dir, sub).mkdir(parents=True, exist_ok=True)
    
    def _scan_tmp_files(self) -> List[Dict]:
        """
        扫描未完成的下载文件。
        
        遍历下载目录，查找 .tmp 后缀的临时文件，用于恢复中断的下载。
        
        Returns:
            临时文件信息列表，每项包含 path、id、folder 键
        """
        tmp_files = []
        
        for sub in ["Safe", "Questionable", "Explicit"]:
            folder = os.path.join(CONFIG.base_dir, sub)
            
            if not os.path.exists(folder):
                continue
            
            try:
                for filename in os.listdir(folder):
                    if not filename.endswith('.tmp'):
                        continue
                    
                    path = os.path.join(folder, filename)
                    base_name = filename[:-4]  # 移除 .tmp 后缀
                    parts = base_name.split('_', 1)
                    
                    if parts and parts[0].isdigit():
                        tmp_files.append({
                            'path': path,
                            'id': parts[0],
                            'folder': sub
                        })
            except OSError as e:
                logger.warning("扫描临时文件失败 [%s]: %s", folder, e)
        
        return tmp_files
    
    def _build_downloaded_ids(self) -> Set[str]:
        """
        构建已下载文件的 ID 集合。
        
        遍历下载目录，提取所有已完成下载文件的帖子 ID。
        
        Returns:
            已下载帖子 ID 的集合
        """
        downloaded = set()
        
        for sub in ["Safe", "Questionable", "Explicit"]:
            folder = os.path.join(CONFIG.base_dir, sub)
            
            if not os.path.exists(folder):
                continue
            
            try:
                for filename in os.listdir(folder):
                    # 跳过临时文件
                    if filename.endswith('.tmp'):
                        continue
                    
                    parts = filename.split('_', 1)
                    if parts and parts[0].isdigit():
                        downloaded.add(parts[0])
            except OSError:
                pass
        
        return downloaded
    
    def _thread_safe_get_viewed_ids_copy(self) -> Set[str]:
        """
        获取已浏览 ID 集合的线程安全副本。
        
        Returns:
            viewed_ids 的浅拷贝
        """
        with self._state_lock():
            return self.viewed_ids.copy()
    
    def _is_filter_active(self) -> bool:
        """
        检查筛选器是否处于激活状态。
        
        Returns:
            True 表示有筛选条件生效
        """
        f = self.user_settings.filter
        return f.min_score > 0 or len(f.ratings) < 3
    
    # =========================================================================
    # 启动流程
    # =========================================================================
    
    def _show_mode_dialog(self) -> None:
        """
        显示启动模式选择对话框。
        
        根据用户选择决定进入最新模式还是续看模式。
        """
        self.show()
        
        has_history = len(self.saved_browse_history) > 0 or len(self.viewed_ids) > 0
        
        dialog = ModeSelectDialog(
            self,
            has_history,
            self.session,
            len(self.pending_tmp_files)
        )
        dialog.exec()
        
        self.mode = dialog.result if dialog.result else MODE_LATEST
        self._start_with_mode()
    
    def _resume_tmp_downloads(self) -> None:
        """恢复未完成的下载任务。"""
        if not self.pending_tmp_files:
            return
        
        self.log(
            f"🔄 恢复 {len(self.pending_tmp_files)} 个下载...",
            TOKENS.colors.warning
        )
        
        for tmp_info in self.pending_tmp_files:
            self.download_manager.submit_resume(
                tmp_info['id'],
                tmp_info['folder'],
                CONFIG.base_dir,
                on_complete=self._on_download_complete,
                on_error=self._on_download_error
            )

    def _check_missing_favorites(self) -> List[Dict]:
        """
        检测收藏夹中缺失的图片。
        
        对比 favorites.json 与 love 文件夹中的实际文件，
        找出已收藏但未完成下载的项目。
        
        Returns:
            缺失项目列表，每项包含 id, data, has_tmp 键
        """
        missing = []
        
        with self._state_lock():
            favorites_copy = dict(self.favorites)
            downloaded_copy = set(self.downloaded_ids)
        
        # 构建 tmp 文件 ID 集合
        tmp_ids = {tmp['id'] for tmp in self.pending_tmp_files}
        
        for post_id, fav_data in favorites_copy.items():
            # 跳过已下载的
            if post_id in downloaded_copy:
                continue
            
            missing.append({
                'id': post_id,
                'data': fav_data,
                'has_tmp': post_id in tmp_ids
            })
        
        return missing

    def _recover_missing_favorites(self) -> None:
        """
        恢复缺失的收藏下载。
        
        自动检测 favorites.json 中存在但 love 文件夹中缺失的图片，
        并启动下载任务。优先使用已保存的 file_url，否则从 API 获取。
        """
        missing = self._check_missing_favorites()
        
        if not missing:
            logger.info("所有收藏已完整下载")
            return
        
        # 区分有 tmp 文件的和完全缺失的
        with_tmp = [m for m in missing if m['has_tmp']]
        without_tmp = [m for m in missing if not m['has_tmp']]
        
        total = len(missing)
        self.log(
            f"🔍 发现 {total} 个缺失收藏 "
            f"({len(with_tmp)} 个有断点, {len(without_tmp)} 个需重新下载)",
            TOKENS.colors.warning
        )
        
        # 记录到日志
        logger.info(
            "检测到 %d 个缺失的收藏: %d 个可断点续传, %d 个需重新下载",
            total, len(with_tmp), len(without_tmp)
        )
        
        recovered_count = 0
        
        for item in missing:
            post_id = item['id']
            fav_data = item['data']
            
            # 确定评级对应的文件夹
            rating = fav_data.get('rating', 'q')
            folder = {'s': 'Safe', 'q': 'Questionable', 'e': 'Explicit'}.get(
                rating, 'Questionable'
            )
            
            # 如果收藏数据包含完整的 file_url，直接构造 post 对象下载
            file_url = fav_data.get('file_url', '')
            
            if file_url and url_validator.validate(file_url):
                # 构造完整的 post 对象
                post = {
                    'id': int(post_id),
                    'file_url': file_url,
                    'tags': fav_data.get('tags', ''),
                    'rating': rating,
                }
                
                self.download_manager.submit_download(
                    post,
                    CONFIG.base_dir,
                    on_complete=self._on_download_complete,
                    on_error=self._on_download_error
                )
                recovered_count += 1
            else:
                # 需要从 API 获取完整信息
                self.download_manager.submit_resume(
                    post_id,
                    folder,
                    CONFIG.base_dir,
                    on_complete=self._on_download_complete,
                    on_error=self._on_download_error
                )
                recovered_count += 1
        
        if recovered_count > 0:
            self.log(
                f"✅ 已提交 {recovered_count} 个恢复任务",
                TOKENS.colors.success
            )

    def _start_with_mode(self) -> None:
        """
        根据选定模式启动应用。
        
        完成 UI 初始化、快捷键设置、历史恢复等工作。
        """
        self.setup_ui()
        self._ui_initialized = True
        self.setup_shortcuts()
        
        if self.mode == MODE_CONTINUE:
            self._restore_browse_history()
            self.log(
                f"📖 续看模式 - 已加载 {len(self.browse_history)} 条历史",
                TOKENS.colors.success
            )
        else:
            self.log("🆕 最新模式", TOKENS.colors.info)
        
        # 延迟恢复未完成的下载（tmp 文件）
        if self.pending_tmp_files:
            QTimer.singleShot(1000, self._resume_tmp_downloads)
        
        # 延迟检测并恢复缺失的收藏（在 tmp 恢复之后）
        QTimer.singleShot(2000, self._recover_missing_favorites)
        
        # 开始加载数据
        self.load_more_posts(is_startup=True)
        self.status_timer.start(300)
    
    # =========================================================================
    # 快捷键设置
    # =========================================================================
    
    def setup_shortcuts(self) -> None:
        """
        配置键盘快捷键。
        
        快捷键映射：
        - 左右箭头：上一张/下一张
        - 空格/L：切换收藏
        - F：全屏切换
        - ESC：退出全屏
        - R：重新加载
        - M：收藏夹
        - S：切换模式
        - P：设置
        - B：备份
        - C：检测并恢复缺失的收藏
        - 1-5：快速设置分数筛选
        - F1/?：帮助
        """
        shortcuts = {
            Qt.Key.Key_Right: self.next_image,
            Qt.Key.Key_Left: self.prev_image,
            Qt.Key.Key_Space: self.toggle_like,
            Qt.Key.Key_L: self.toggle_like,
            Qt.Key.Key_F: self.toggle_fullscreen,
            Qt.Key.Key_Escape: self.exit_fullscreen,
            Qt.Key.Key_Z: self.minimize_window,
            Qt.Key.Key_R: self.reload_current,
            Qt.Key.Key_M: lambda: self.fav_manager.show(),
            Qt.Key.Key_S: self.switch_mode,
            Qt.Key.Key_P: self.show_settings,
            Qt.Key.Key_B: self.show_backup_dialog,
            Qt.Key.Key_C: self._recover_missing_favorites,  # 新增：手动检测缺失
            Qt.Key.Key_1: lambda: self._quick_set_score(0),
            Qt.Key.Key_2: lambda: self._quick_set_score(5),
            Qt.Key.Key_3: lambda: self._quick_set_score(15),
            Qt.Key.Key_4: lambda: self._quick_set_score(30),
            Qt.Key.Key_5: lambda: self._quick_set_score(50),
            Qt.Key.Key_F1: self._show_shortcut_help,
            Qt.Key.Key_Question: self._show_shortcut_help,
        }
        
        for key, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
    
    def _quick_set_score(self, score: int) -> None:
        """
        快速设置分数筛选值。
        
        Args:
            score: 最低分数阈值
        """
        self.user_settings.filter.min_score = score
        self._update_filter_indicator()
        self._apply_filter_to_queue()
        
        labels = {0: "不限", 5: "≥5", 15: "≥15", 30: "≥30", 50: "≥50"}
        self.log(f"🎯 分数: {labels.get(score, f'≥{score}')}", TOKENS.colors.info)
    
    # =========================================================================
    # 筛选器逻辑
    # =========================================================================
    
    def _apply_filter_to_queue(self) -> None:
        """
        将当前筛选条件应用到待浏览队列。
        
        移除不符合筛选条件的帖子，并在队列过短时触发加载更多。
        """
        self.filter_active = self._is_filter_active()
        
        if not self.filter_active:
            return
        
        f = self.user_settings.filter
        original_len = len(self.post_queue)
        
        # 筛选符合条件的帖子
        filtered = deque()
        for post in self.post_queue:
            if self._post_matches_filter(post, f):
                filtered.append(post)
        
        self.filtered_out_count = original_len - len(filtered)
        self.post_queue = filtered
        
        # 队列不足时加载更多
        if len(self.post_queue) < 10:
            self.load_more_posts()
    
    def _post_matches_filter(self, post: dict, f: FilterSettings) -> bool:
        """
        检查帖子是否符合筛选条件。
        
        Args:
            post: 帖子数据字典
            f: 筛选设置对象
        
        Returns:
            True 表示符合条件
        """
        # 分数检查
        if f.min_score > 0 and post.get('score', 0) < f.min_score:
            return False
        
        # 评级检查
        if post.get('rating', 'q') not in f.ratings:
            return False
        
        return True
    
    def _update_filter_indicator(self) -> None:
        """更新筛选状态指示器的显示文本。"""
        f = self.user_settings.filter
        active = f.min_score > 0 or len(f.ratings) < 3
        
        if active:
            parts = []
            if f.min_score > 0:
                parts.append(f"≥{f.min_score}")
            if len(f.ratings) < 3:
                parts.append(''.join(sorted(r.upper() for r in f.ratings)))
            self.filter_indicator.setText(f"🔍 {' '.join(parts)}")
        else:
            self.filter_indicator.setText("")
    
    # =========================================================================
    # 对话框交互
    # =========================================================================
    
    def show_settings(self) -> None:
        """显示设置对话框。"""
        dialog = SettingsDialog(self, self.user_settings)
        dialog.settings_saved.connect(self._on_settings_save)
        dialog.preview_requested.connect(self._on_settings_preview)
        dialog.exec()
    
    def show_backup_dialog(self) -> None:
        """显示备份/恢复对话框。"""
        dialog = BackupRestoreDialog(
            self,
            download_manager=self.download_manager,
            on_restore_complete=self._on_restore_complete
        )
        dialog.exec()
    
    def _on_settings_preview(self, settings: UserSettings) -> None:
        """
        处理设置预览请求。
        
        Args:
            settings: 预览用的设置对象
        """
        # 可扩展：实现实时预览功能
        pass
    
    def _on_settings_save(self, new_settings: UserSettings) -> None:
        """
        处理设置保存。
        
        Args:
            new_settings: 新的设置对象
        """
        old_cache_size = self.user_settings.performance.max_image_cache
        self.user_settings = new_settings
        self.user_settings.save(CONFIG.settings_file)
        
        # 更新缓存大小
        if new_settings.performance.max_image_cache != old_cache_size:
            self.image_cache.maxsize = new_settings.performance.max_image_cache
        
        # 更新筛选状态
        self.filter_active = self._is_filter_active()
        self._update_filter_indicator()
        self._apply_filter_to_queue()
        
        self.log("✅ 设置已保存", TOKENS.colors.success)
    
    def _on_restore_complete(self) -> None:
        """处理数据恢复完成。"""
        self.log("✅ 数据已恢复，建议重启程序", TOKENS.colors.success)
    
    def switch_mode(self) -> None:
        """切换浏览模式（最新/续看）。"""
        if self.mode == MODE_LATEST:
            self.mode = MODE_CONTINUE
            self.log("📖 切换到续看模式", TOKENS.colors.success)
        else:
            self.mode = MODE_LATEST
            self.log("🆕 切换到最新模式", TOKENS.colors.info)
        
        self._update_mode_display()
    
    # =========================================================================
    # UI 构建
    # =========================================================================
    
    def setup_ui(self) -> None:
        """
        构建主界面 UI。
        
        界面采用三段式布局：
        - 顶部工具栏：统计信息、筛选控件、功能按钮
        - 中间主区域：图像展示区
        - 底部信息栏：标签云、元数据、导航按钮
        """
        C = TOKENS.colors
        
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet(f"background-color: {C.bg_base};")
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 顶部工具栏
        self._setup_toolbar(main_layout)
        
        # 主图像区
        self._setup_main_view(main_layout)
        
        # 底部信息栏
        self._setup_footer(main_layout)
        
        # 覆盖层组件（Toast、快捷键帮助等）
        self._setup_overlays()
        
        # 更新模式显示
        self._update_mode_display()
    
    def _setup_toolbar(self, parent_layout: QVBoxLayout) -> None:
        """
        构建顶部工具栏。
        
        Args:
            parent_layout: 父布局
        """
        C = TOKENS.colors
        S = TOKENS.spacing
        T = TOKENS.typography
        L = TOKENS.layout
        
        toolbar = QFrame()
        toolbar.setFixedHeight(L.toolbar_height)
        toolbar.setStyleSheet(f"""
            QFrame {{
                background-color: {C.bg_elevated};
                border-bottom: 1px solid {C.border_subtle};
            }}
        """)
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(S.md, 0, S.md, 0)
        layout.setSpacing(0)
        
        # 左侧：数据监控
        left_section = self._create_toolbar_left_section()
        layout.addWidget(left_section)
        
        # 中间：筛选控件
        center_section = self._create_toolbar_center_section()
        layout.addWidget(center_section, 1)
        
        # 右侧：功能按钮
        right_section = self._create_toolbar_right_section()
        layout.addWidget(right_section)
        
        parent_layout.addWidget(toolbar)
    
    def _create_toolbar_left_section(self) -> QFrame:
        """创建工具栏左侧区域（统计信息）。"""
        C = TOKENS.colors
        S = TOKENS.spacing
        T = TOKENS.typography
        
        section = QFrame()
        section.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.lg)
        
        # 模式标签
        self.lbl_mode = QLabel("🆕 最新")
        self.lbl_mode.setStyleSheet(f"""
            color: {C.accent};
            font-family: {T.font_primary};
            font-size: {T.size_lg}px;
            font-weight: bold;
        """)
        layout.addWidget(self.lbl_mode)
        
        # 分隔线
        layout.addWidget(self._create_vseparator())
        
        # 统计徽章
        self.stat_viewed = StatBadge("👁", "0", color=C.text_secondary)
        self.stat_liked = StatBadge("❤", "0", color=C.accent)
        self.stat_queue = StatBadge("📦", "0", color=C.text_muted)
        
        layout.addWidget(self.stat_viewed)
        layout.addWidget(self.stat_liked)
        layout.addWidget(self.stat_queue)
        
        return section
    
    def _create_toolbar_center_section(self) -> QFrame:
        """创建工具栏中间区域（筛选控件）。"""
        C = TOKENS.colors
        S = TOKENS.spacing
        T = TOKENS.typography
        
        section = QFrame()
        section.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(section)
        layout.setContentsMargins(S.xxl, 0, S.xxl, 0)
        layout.setSpacing(S.lg)
        
        # 评级选择器
        self.rating_selector = SegmentedControl(
            options=[
                ('s', 'S', C.rating_safe),
                ('q', 'Q', C.rating_questionable),
                ('e', 'E', C.rating_explicit),
            ],
            multi_select=True
        )
        self.rating_selector.set_selection(self.user_settings.filter.ratings)
        self.rating_selector.selectionChanged.connect(self._on_rating_change)
        layout.addWidget(self.rating_selector)
        
        layout.addWidget(self._create_vseparator())
        
        # 分数选择器
        self.score_selector = ScoreSelector()
        self.score_selector.set_value(self.user_settings.filter.min_score)
        self.score_selector.valueChanged.connect(self._on_score_change)
        layout.addWidget(self.score_selector)
        
        # 筛选指示器
        self.filter_indicator = QLabel()
        self.filter_indicator.setStyleSheet(f"""
            color: {C.warning};
            font-size: {T.size_xs}px;
        """)
        layout.addWidget(self.filter_indicator)
        
        return section
    
    def _create_toolbar_right_section(self) -> QFrame:
        """创建工具栏右侧区域（功能按钮）。"""
        S = TOKENS.spacing
        
        section = QFrame()
        section.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.sm)
        
        # 模式切换按钮
        self.btn_mode = ActionButton(
            "续看" if self.mode == MODE_LATEST else "最新",
            icon="📖",
            style=ButtonStyle.GHOST,
            compact=True
        )
        self.btn_mode.clicked.connect(self.switch_mode)
        layout.addWidget(self.btn_mode)
        
        layout.addWidget(self._create_vseparator())
        
        # 功能按钮组
        self.btn_folder = IconButton("📁", tooltip="收藏夹", style=ButtonStyle.DEFAULT)
        self.btn_folder.clicked.connect(lambda: self.fav_manager.show())
        layout.addWidget(self.btn_folder)
        
        self.btn_settings = IconButton("⚙", tooltip="设置 (P)", style=ButtonStyle.DEFAULT)
        self.btn_settings.clicked.connect(self.show_settings)
        layout.addWidget(self.btn_settings)
        
        self.btn_backup = IconButton("📦", tooltip="备份 (B)", style=ButtonStyle.DEFAULT)
        self.btn_backup.clicked.connect(self.show_backup_dialog)
        layout.addWidget(self.btn_backup)
        
        self.btn_help = IconButton("?", tooltip="快捷键 (F1)", style=ButtonStyle.GHOST)
        self.btn_help.clicked.connect(self._show_shortcut_help)
        layout.addWidget(self.btn_help)
        
        return section
    
    def _setup_main_view(self, parent_layout: QVBoxLayout) -> None:
        """
        构建主图像展示区。
        
        Args:
            parent_layout: 父布局
        """
        C = TOKENS.colors
        S = TOKENS.spacing
        T = TOKENS.typography
        L = TOKENS.layout
        
        self.main_frame = QFrame()
        self.main_frame.setStyleSheet(f"background-color: {C.bg_base};")
        
        frame_layout = QVBoxLayout(self.main_frame)
        frame_layout.setContentsMargins(S.lg, S.md, S.lg, S.md)
        
        # 图片标签
        self.lbl_image = QLabel()
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setStyleSheet(f"""
            background-color: transparent;
            color: {C.text_muted};
            font-size: 48px;
        """)
        self.lbl_image.setText("🎨")
        self.lbl_image.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        frame_layout.addWidget(self.lbl_image)
        
        # 加载动画组件
        self.loading_widget = LoadingWidget(self.main_frame)
        self.loading_widget.hide()
        
        parent_layout.addWidget(self.main_frame, 1)
        
        # 悬浮位置指示器
        self.lbl_pos = QLabel("", self.main_frame)
        self.lbl_pos.setStyleSheet(f"""
            background-color: {C.bg_overlay};
            color: {C.text_secondary};
            font-family: {T.font_mono};
            font-size: {T.size_sm}px;
            padding: {S.xs}px {S.md}px;
            border-radius: {L.radius_md}px;
        """)
        
        # 收藏徽章
        self.lbl_saved_badge = QLabel("⭐ 已收藏", self.main_frame)
        self.lbl_saved_badge.setStyleSheet(f"""
            background-color: {C.success};
            color: {C.text_primary};
            font-size: {T.size_sm}px;
            font-weight: bold;
            padding: {S.xs}px {S.md}px;
            border-radius: {L.radius_md}px;
        """)
        self.lbl_saved_badge.hide()
        
        # 预加载状态指示器
        self.lbl_preload = QLabel("", self.main_frame)
        self.lbl_preload.setStyleSheet(f"""
            color: {C.info};
            font-family: {T.font_mono};
            font-size: {T.size_sm}px;
        """)
    
    def _setup_footer(self, parent_layout: QVBoxLayout) -> None:
        """
        构建底部信息栏。
        
        Args:
            parent_layout: 父布局
        """
        C = TOKENS.colors
        S = TOKENS.spacing
        L = TOKENS.layout
        
        footer = QFrame()
        footer.setFixedHeight(L.statusbar_height)
        footer.setStyleSheet(f"""
            QFrame {{
                background-color: {C.bg_elevated};
                border-top: 1px solid {C.border_subtle};
            }}
        """)
        
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(S.lg, S.sm, S.lg, S.sm)
        layout.setSpacing(S.xl)
        
        # 左侧：标签与元数据
        info_section = QFrame()
        info_section.setStyleSheet("background: transparent;")
        info_layout = QVBoxLayout(info_section)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(S.xs)
        
        self.tag_cloud = TagCloud(max_tags=10)
        self.tag_cloud.tag_clicked.connect(self._on_tag_clicked)
        info_layout.addWidget(self.tag_cloud)
        
        self.metadata_bar = MetadataBar()
        info_layout.addWidget(self.metadata_bar)
        
        layout.addWidget(info_section, 1)
        
        # 右侧：导航控件
        nav_section = QFrame()
        nav_section.setStyleSheet("background: transparent;")
        nav_layout = QHBoxLayout(nav_section)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(S.md)
        
        self.btn_prev = NavButton("prev")
        self.btn_prev.clicked.connect(self.prev_image)
        nav_layout.addWidget(self.btn_prev)
        
        self.btn_like = FavoriteButton()
        self.btn_like.clicked.connect(self.toggle_like)
        nav_layout.addWidget(self.btn_like)
        
        self.btn_next = NavButton("next")
        self.btn_next.clicked.connect(self.next_image)
        nav_layout.addWidget(self.btn_next)
        
        layout.addWidget(nav_section)
        
        parent_layout.addWidget(footer)
    
    def _setup_overlays(self) -> None:
        """设置覆盖层组件（Toast、快捷键帮助）。"""
        self.toast = Toast(self)
        self.shortcut_overlay = ShortcutOverlay(self)
    
    def _create_vseparator(self) -> QFrame:
        """
        创建垂直分隔线。
        
        Returns:
            配置好样式的分隔线组件
        """
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {TOKENS.colors.border_subtle};")
        return sep
    
    # =========================================================================
    # UI 回调
    # =========================================================================
    
    def _on_rating_change(self, ratings: set) -> None:
        """
        处理评级筛选变化。
        
        Args:
            ratings: 选中的评级集合
        """
        self.user_settings.filter.ratings = ratings
        self._update_filter_indicator()
        self._apply_filter_to_queue()
        
        rating_text = ''.join(sorted(r.upper() for r in ratings))
        self.toast.show_message(f"评级: {rating_text}", "🏷", style="info")
    
    def _on_score_change(self, score: int) -> None:
        """
        处理分数筛选变化。
        
        Args:
            score: 新的最低分数阈值
        """
        self.user_settings.filter.min_score = score
        self._update_filter_indicator()
        self._apply_filter_to_queue()
        
        label = "不限" if score == 0 else f"≥{score}"
        self.toast.show_message(f"分数: {label}", "★", style="info")
    
    def _on_tag_clicked(self, tag: str) -> None:
        """
        处理标签点击事件（复制到剪贴板）。
        
        Args:
            tag: 被点击的标签文本
        """
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(tag)
        self.toast.show_message(f"已复制: {tag}", "📋", style="success")
    
    def _show_shortcut_help(self) -> None:
        """显示快捷键帮助覆盖层。"""
        self.shortcut_overlay.show()
        self.shortcut_overlay.raise_()
    
    # =========================================================================
    # 界面更新
    # =========================================================================
    
    @pyqtSlot(dict)
    def update_ui(self, post: dict) -> None:
        """
        更新界面显示。
        
        Args:
            post: 当前帖子数据
        """
        if not self._ui_initialized:
            return
        
        with self._state_lock():
            viewed_count = len(self.viewed_ids)
            fav_count = len(self.favorites)
        
        # 更新统计
        self.stat_viewed.set_value(str(viewed_count))
        self.stat_liked.set_value(str(fav_count))
        self.stat_queue.set_value(str(len(self.post_queue)))
        
        # 更新位置指示
        total = len(self.browse_history)
        current = self.history_index + 1
        self.lbl_pos.setText(f"{current}/{total}  +{len(self.post_queue)}")
        self.lbl_pos.adjustSize()
        self._center_pos_label()
        
        # 更新标签云
        self.tag_cloud.set_tags(post.get('tags', ''))
        
        # 更新元数据
        is_saved = self._is_already_saved(post)
        self.metadata_bar.update_data(
            post_id=post['id'],
            score=post.get('score', 0),
            width=post.get('width', 0),
            height=post.get('height', 0),
            file_size=post.get('file_size', 0),
            is_saved=is_saved
        )
        
        # 更新收藏按钮状态
        self.btn_like.set_favorited(is_saved, animate=False)
        
        # 更新收藏徽章
        if is_saved and self.user_settings.ui.show_saved_badge:
            self.lbl_saved_badge.show()
            self.lbl_saved_badge.move(TOKENS.spacing.md, TOKENS.spacing.md)
        else:
            self.lbl_saved_badge.hide()
    
    def _center_pos_label(self) -> None:
        """将位置标签居中显示。"""
        if hasattr(self, 'lbl_pos') and self.main_frame:
            x = (self.main_frame.width() - self.lbl_pos.width()) // 2
            self.lbl_pos.move(x, TOKENS.spacing.md)
    
    def _center_loading_widget(self) -> None:
        """将加载动画组件居中显示。"""
        if self.loading_widget and self.main_frame:
            lw = self.loading_widget
            mf = self.main_frame
            x = (mf.width() - lw.width()) // 2
            y = (mf.height() - lw.height()) // 2
            lw.move(max(0, x), max(0, y))
    
    def _update_mode_display(self) -> None:
        """更新模式标签和按钮的显示状态。"""
        C = TOKENS.colors
        T = TOKENS.typography
        
        if not hasattr(self, 'lbl_mode'):
            return
        
        if self.mode == MODE_LATEST:
            self.lbl_mode.setText("🆕 最新")
            self.lbl_mode.setStyleSheet(f"""
                color: {C.accent};
                font-size: {T.size_lg}px;
                font-weight: bold;
            """)
            if hasattr(self, 'btn_mode'):
                self.btn_mode.setText("📖  续看")
        else:
            self.lbl_mode.setText("📖 续看")
            self.lbl_mode.setStyleSheet(f"""
                color: {C.success};
                font-size: {T.size_lg}px;
                font-weight: bold;
            """)
            if hasattr(self, 'btn_mode'):
                self.btn_mode.setText("🆕  最新")
    
    def log(self, msg: str, color: str = None) -> None:
        """
        显示日志消息（通过 Toast）。
        
        Args:
            msg: 消息内容
            color: 颜色（用于判断消息类型）
        """
        if not hasattr(self, 'toast'):
            return
        
        # 根据颜色和内容判断消息类型
        style = "info"
        icon = "ℹ️"
        
        if color == TOKENS.colors.success or "✅" in msg or "❤" in msg:
            style = "success"
            icon = "✅"
        elif color == TOKENS.colors.warning or "⚠" in msg:
            style = "warning"
            icon = "⚠️"
        elif color == TOKENS.colors.error or "❌" in msg:
            style = "error"
            icon = "❌"
        elif "🆕" in msg or "📡" in msg:
            icon = msg[:2] if len(msg) >= 2 else "📡"
        
        self.toast.show_message(msg, icon, duration=2500, style=style)
    
    def show_loading(self) -> None:
        """显示加载动画。"""
        if hasattr(self, 'loading_widget') and self.loading_widget:
            self._center_loading_widget()
            self.loading_widget.show()
    
    def hide_loading(self) -> None:
        """隐藏加载动画。"""
        if hasattr(self, 'loading_widget') and self.loading_widget:
            self.loading_widget.hide()
    
    # =========================================================================
    # 状态更新
    # =========================================================================
    
    def _update_status_loop(self) -> None:
        """定时更新状态信息（下载进度、缓存状态等）。"""
        # 下载状态
        dl_status = self.download_manager.get_status()
        download_text = ""
        if dl_status['resuming'] > 0:
            download_text = f"🔄{dl_status['resuming']} "
        if dl_status['pending'] > 0:
            download_text += f"⬇{dl_status['pending']}"
        if dl_status['failed'] > 0:
            download_text += f" ❌{dl_status['failed']}"
        
        # 缓存状态
        stats = self.preloader.get_stats()
        cache_max = self.user_settings.performance.max_image_cache
        
        if stats['pending'] > 0:
            self.lbl_preload.setText(f"预加载: {stats['pending']} 张")
        else:
            self.lbl_preload.setText("✅ 缓存就绪")
    
    # =========================================================================
    # 核心功能
    # =========================================================================
    
    def _is_already_saved(self, post: dict) -> bool:
        """
        检查帖子是否已收藏或已下载。
        
        Args:
            post: 帖子数据
        
        Returns:
            True 表示已保存
        """
        pid = str(post['id'])
        with self._state_lock():
            return pid in self.favorites or pid in self.downloaded_ids
    
    def minimize_window(self) -> None:
        """最小化窗口。"""
        self.showMinimized()
    
    def toggle_fullscreen(self) -> None:
        """切换全屏模式。"""
        if self.is_fullscreen:
            self.showNormal()
        else:
            self.showFullScreen()
        self.is_fullscreen = not self.is_fullscreen
    
    def exit_fullscreen(self) -> None:
        """退出全屏模式。"""
        if self.is_fullscreen:
            self.toggle_fullscreen()
    
    # =========================================================================
    # 图像显示
    # =========================================================================
    
    def do_resize(self) -> None:
        """根据当前窗口大小调整图像显示。"""
        if not self.original_pil_image:
            return
        
        w = self.main_frame.width() - 30
        h = self.main_frame.height() - 30
        
        if w < 50 or h < 50:
            return
        
        # 保持长宽比缩放
        img = self.original_pil_image.copy()
        img.thumbnail((w, h), Image.Resampling.LANCZOS)
        self._display_image(img)
    
    def _display_image(self, img: Image.Image) -> None:
        """
        将 PIL 图像显示到界面上。
        
        采用深拷贝策略，避免 PIL 内存与 Qt 内存的生命周期冲突。
        
        Args:
            img: 要显示的 PIL 图像
        """
        try:
            # 转换为 RGBA 格式
            rgba_img = img.convert('RGBA')
            
            # 保持强引用，防止 GC 回收
            self._current_display_image = rgba_img
            
            # 转换为 QImage
            qimg = ImageQt(rgba_img)
            
            # 创建深拷贝，断开与 PIL 内存的关联
            pixmap = QPixmap.fromImage(qimg).copy()
            
            self.lbl_image.setPixmap(pixmap)
            self.lbl_image.setText("")
        except Exception as e:
            logger.error("图像显示失败: %s", e)
            self.lbl_image.setText("❌ 显示错误")
    
    # 兼容旧接口
    def show_image(self, img: Image.Image) -> None:
        """显示图像（兼容旧接口）。"""
        self._display_image(img)
    
    # =========================================================================
    # 数据获取
    # =========================================================================
    
    def load_more_posts(self, is_startup: bool = False) -> None:
        """
        从 API 加载更多帖子。
        
        在后台线程中执行网络请求，通过信号通知主线程处理结果。
        
        Args:
            is_startup: 是否为启动时的首次加载
        """
        if self.is_loading_api:
            return
        
        self.is_loading_api = True
        self.log("📡 加载中...", TOKENS.colors.info)
        
        # 预先拷贝数据供后台线程使用
        current_page = self.page
        viewed_ids_copy = self._thread_safe_get_viewed_ids_copy()
        current_mode = self.mode
        filter_settings = copy.deepcopy(self.user_settings.filter)
        high_score_first = self.user_settings.filter.high_score_first
        high_score_threshold = self.user_settings.ui.high_score_threshold
        
        def fetch():
            """后台获取数据。"""
            try:
                params = {'limit': CONFIG.limit, 'page': current_page}
                
                # 构造评级筛选标签
                ratings = filter_settings.ratings
                if 0 < len(ratings) < 3:
                    rating_map = {'s': 'safe', 'q': 'questionable', 'e': 'explicit'}
                    rating_tags = [
                        f"rating:{rating_map[r]}"
                        for r in ratings if r in rating_map
                    ]
                    if rating_tags:
                        params['tags'] = ' '.join(rating_tags)
                
                resp = SESSION.get(CONFIG.api_url, params=params)
                
                if resp.status_code != 200:
                    self.signals.error.emit(f"HTTP {resp.status_code}")
                    return
                
                data = resp.json()
                
                # 启动时显示新图数量
                if is_startup and data:
                    new_count = sum(
                        1 for p in data[:30]
                        if str(p['id']) not in viewed_ids_copy
                    )
                    self.signals.log.emit(
                        f"🆕 {new_count}+ 新图" if new_count else "✅ 已是最新",
                        TOKENS.colors.info
                    )
                
                # 去重处理
                if current_mode == MODE_CONTINUE:
                    new_posts = [
                        p for p in data
                        if str(p['id']) not in viewed_ids_copy
                    ]
                else:
                    new_posts = data
                
                # 分数筛选
                if filter_settings.min_score > 0:
                    new_posts = [
                        p for p in new_posts
                        if p.get('score', 0) >= filter_settings.min_score
                    ]
                
                # 空结果处理（限制重试次数防止无限循环）
                if not new_posts and data:
                    self.signals.log.emit(
                        "🔄 筛选后空结果，尝试下一页...",
                        TOKENS.colors.warning
                    )
                    self.page = current_page + 1
                    self._empty_page_retries += 1
                    
                    if self._empty_page_retries < self.MAX_EMPTY_PAGE_RETRIES:
                        self.is_loading_api = False
                        self.signals.request_reload.emit()
                    else:
                        self._empty_page_retries = 0
                        self.is_loading_api = False
                        self.signals.log.emit(
                            "⚠ 连续多页无结果，请放宽筛选",
                            TOKENS.colors.warning
                        )
                    return
                
                self._empty_page_retries = 0
                
                # 高分优先排序
                if high_score_first:
                    high = [
                        p for p in new_posts
                        if p.get('score', 0) >= high_score_threshold
                    ]
                    normal = [
                        p for p in new_posts
                        if p.get('score', 0) < high_score_threshold
                    ]
                    ordered = high + normal
                else:
                    ordered = new_posts
                
                self.page = current_page + 1
                self.signals.posts_loaded.emit(ordered)
                
            except Exception as e:
                logger.exception("API 请求失败")
                self.signals.error.emit(str(e)[:25])
            finally:
                self.is_loading_api = False
        
        # 启动后台线程
        thread = threading.Thread(target=fetch, daemon=True, name="API_Worker")
        thread.start()
    
    @pyqtSlot(list)
    def _on_posts_loaded_slot(self, posts: list) -> None:
        """
        处理帖子加载完成事件。
        
        Args:
            posts: 新加载的帖子列表
        """
        self.post_queue.extend(posts)
        self.log(f"✅ +{len(posts)}", TOKENS.colors.success)
        
        # 自动开始显示
        if self.mode == MODE_CONTINUE and self.browse_history and self.history_index >= 0:
            if not self.current_post:
                self._show_post(self.browse_history[self.history_index])
        elif self.history_index == -1 and not self.current_post:
            self.next_image()
        
        self._trigger_preload()
    
    # =========================================================================
    # 导航功能
    # =========================================================================
    
    def next_image(self) -> None:
        """显示下一张图像。"""
        now = time.time()
        
        # 快速翻页时增强预加载
        if now - self.last_next_time < 0.5:
            self._trigger_preload(extra=5)
        self.last_next_time = now
        
        # 浏览历史中的前进
        if self.history_index < len(self.browse_history) - 1:
            self.history_index += 1
            self._show_post(self.browse_history[self.history_index])
            return
        
        # 队列为空，请求更多
        if not self.post_queue:
            self.log("📭 正在获取更多...", TOKENS.colors.warning)
            self.load_more_posts()
            return
        
        # 正常前进
        post = self.post_queue.popleft()
        self.browse_history.append(post)
        self.history_index = len(self.browse_history) - 1
        
        with self._state_lock():
            self.viewed_ids.add(str(post['id']))
        
        self._show_post(post)
        
        # 队列不足时预加载
        if len(self.post_queue) < 20:
            self.load_more_posts()
    
    def prev_image(self) -> None:
        """显示上一张图像。"""
        if self.history_index <= 0:
            self.log("⚠ 已是第一张", TOKENS.colors.warning)
            return
        
        self.history_index -= 1
        self._show_post(self.browse_history[self.history_index])
        self.log(
            f"◀ {self.history_index + 1}/{len(self.browse_history)}",
            TOKENS.colors.text_muted
        )
    
    def reload_current(self) -> None:
        """重新加载当前图像。"""
        if not self.current_post:
            return
        
        pid = str(self.current_post['id'])
        
        # 移除缓存（不显式关闭，防止当前显示失效）
        with self.image_cache.lock:
            self.image_cache.cache.pop(pid, None)
        
        self.original_pil_image = None
        self._current_display_image = None
        
        self._show_post(self.current_post)
        self.log("🔄 重新加载", TOKENS.colors.info)
    
    def _show_post(self, post: dict) -> None:
        """
        显示指定帖子。
        
        Args:
            post: 帖子数据
        """
        if self.resize_timer:
            self.resize_timer.stop()
        
        self.current_post = post
        self.update_ui(post)
        
        pid = str(post['id'])
        cached = self.image_cache.get(pid)
        
        if cached:
            self.original_pil_image = cached
            self.do_resize()
            self._trigger_preload()
            return
        
        # 显示加载状态
        self.lbl_image.setPixmap(QPixmap())
        self.lbl_image.setText("")
        self.show_loading()
        self.lbl_saved_badge.hide()
        
        # 启动后台加载
        size = (self.main_frame.width(), self.main_frame.height())
        thread = threading.Thread(
            target=self._load_image,
            args=(post, size),
            daemon=True,
            name="ImgLoader"
        )
        thread.start()
    
    def _load_image(self, post: dict, size: tuple) -> None:
        """
        后台加载图像。
        
        Args:
            post: 帖子数据
            size: 目标显示尺寸
        """
        pid = str(post['id'])
        
        try:
            url = post.get('sample_url') or post.get('preview_url')
            
            if not url or not url_validator.validate(url):
                raise ValueError("无效的 URL")
            
            resp = SESSION.get(
                url,
                timeout=self.user_settings.performance.load_timeout,
                verify=True
            )
            
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            
            # 加载并缓存图像
            with Image.open(BytesIO(resp.content)) as img:
                img.load()
                cached_img = img.copy()
            
            self.image_cache.put(pid, cached_img)
            self.signals.image_loaded.emit(cached_img, pid)
            
        except Exception as e:
            logger.warning("图像加载失败 [%s]: %s", pid, e)
            self.signals.error.emit("图片加载失败")
    
    @pyqtSlot(object, str)
    def _on_image_loaded_slot(self, img: Image.Image, pid: str) -> None:
        """
        处理图像加载完成事件。
        
        Args:
            img: 加载的 PIL 图像
            pid: 帖子 ID
        """
        if self.current_post and str(self.current_post['id']) == pid:
            self.original_pil_image = img
            self.do_resize()
            self.update_ui(self.current_post)
            self._trigger_preload()
        
        self.hide_loading()
    
    def _trigger_preload(self, extra: int = 0) -> None:
        """
        触发图像预加载。
        
        Args:
            extra: 额外预加载数量
        """
        count = self.user_settings.performance.preload_count + extra
        posts = list(self.post_queue)[:count]
        
        # 智能预加载：当前位置前后都加载
        if self.history_index > 0:
            start = max(0, self.history_index - 3)
            posts.extend(self.browse_history[start:self.history_index])
        
        if self.history_index < len(self.browse_history) - 1:
            end = min(len(self.browse_history), self.history_index + 4)
            posts.extend(self.browse_history[self.history_index + 1:end])
        
        self.preloader.preload_batch(posts)
    
    # =========================================================================
    # 收藏功能
    # =========================================================================
    
    def toggle_like(self) -> None:
        """切换当前帖子的收藏状态。"""
        if not self.current_post:
            return
        
        pid = str(self.current_post['id'])
        
        with self._state_lock():
            if pid in self.favorites:
                # 取消收藏
                del self.favorites[pid]
                self.downloaded_ids.discard(pid)
                is_saved = False
            else:
                # 添加收藏
                self.favorites[pid] = {
                    'id': self.current_post['id'],
                    'tags': self.current_post.get('tags', ''),
                    'rating': self.current_post.get('rating', 'q'),
                    'file_url': self.current_post.get('file_url', ''),
                    'added': time.strftime('%Y-%m-%d %H:%M')
                }
                self.downloaded_ids.add(pid)
                is_saved = True
            
            safe_json_save(CONFIG.favorites_file, self.favorites)
        
        self.update_ui(self.current_post)
        
        if is_saved:
            self.log("❤ 加入下载队列...", TOKENS.colors.success)
            self.download_manager.submit_download(
                self.current_post,
                CONFIG.base_dir,
                on_complete=self._on_download_complete,
                on_error=self._on_download_error
            )
        else:
            self.log("💔 已取消收藏", TOKENS.colors.text_muted)
    
    # =========================================================================
    # 下载回调
    # =========================================================================
    
    def _on_download_complete(self, post_id: str, path: str) -> None:
        """
        下载完成回调（后台线程调用）。
        
        Args:
            post_id: 帖子 ID
            path: 保存路径
        """
        self.signals.download_complete.emit(post_id, path)
    
    @pyqtSlot(str, str)
    def _on_download_complete_slot(self, post_id: str, path: str) -> None:
        """
        下载完成槽函数（主线程）。
        
        Args:
            post_id: 帖子 ID
            path: 保存路径
        """
        with self._state_lock():
            self.downloaded_ids.add(post_id)
        
        if self.current_post and str(self.current_post['id']) == post_id:
            self.update_ui(self.current_post)
    
    def _on_download_error(self, post_id: str, error: str) -> None:
        """
        下载错误回调（后台线程调用）。
        
        Args:
            post_id: 帖子 ID
            error: 错误信息
        """
        self.signals.download_error.emit(post_id, error)
    
    @pyqtSlot(str, str)
    def _on_download_error_slot(self, post_id: str, error: str) -> None:
        """
        下载错误槽函数（主线程）。
        
        Args:
            post_id: 帖子 ID
            error: 错误信息
        """
        logger.warning("下载失败 [%s]: %s", post_id, error)
    
    @pyqtSlot(str)
    def _on_error_slot(self, error_msg: str) -> None:
        """
        通用错误槽函数。
        
        Args:
            error_msg: 错误消息
        """
        self.log(f"❌ {error_msg}", TOKENS.colors.error)
        self.hide_loading()
    
    @pyqtSlot(str, str)
    def _on_log_slot(self, message: str, color: str) -> None:
        """
        日志槽函数。
        
        Args:
            message: 日志消息
            color: 颜色
        """
        self.log(message, color)
    
    @pyqtSlot()
    def _on_request_reload_slot(self) -> None:
        """重新加载请求槽函数。"""
        self.load_more_posts()
    
    # =========================================================================
    # 窗口事件
    # =========================================================================
    
    def resizeEvent(self, event: "QResizeEvent") -> None:
        """
        窗口大小变化事件。
        
        Args:
            event: 事件对象
        """
        super().resizeEvent(event)
        
        if not self._ui_initialized:
            return
        
        # 更新覆盖层尺寸
        if hasattr(self, 'shortcut_overlay'):
            self.shortcut_overlay.setGeometry(self.rect())
        
        # 更新加载动画位置
        if hasattr(self, 'loading_widget') and hasattr(self, 'main_frame'):
            self._center_loading_widget()
        
        # 居中位置标签
        self._center_pos_label()
        
        # 防抖调整图片（延迟执行以避免频繁重绘）
        if self.original_pil_image:
            if self.resize_timer:
                self.resize_timer.stop()
            self.resize_timer = QTimer(self)
            self.resize_timer.setSingleShot(True)
            self.resize_timer.timeout.connect(self.do_resize)
            self.resize_timer.start(80)
    
    def closeEvent(self, event: "QCloseEvent") -> None:
        """
        窗口关闭事件。
        
        按正确顺序释放资源，确保数据保存和后台任务正确终止。
        
        Args:
            event: 事件对象
        """
        # 1. 停止定时器
        self.status_timer.stop()
        if self.resize_timer:
            self.resize_timer.stop()
        
        # 2. 保存状态
        self._save_all_state()
        
        # 3. 关闭后台管理器
        self.download_manager.shutdown()
        
        if hasattr(self.preloader, 'shutdown'):
            self.preloader.shutdown()
        
        # 4. 清理缓存
        self.image_cache.clear()
        
        # 5. 释放图像引用
        self._current_display_image = None
        self.original_pil_image = None
        
        # 6. 关闭网络会话
        SESSION.close()
        
        event.accept()
    
    def _save_all_state(self) -> None:
        """保存所有运行时状态到文件。"""
        with self._state_lock():
            # 保存浏览历史
            safe_json_save(CONFIG.history_file, self.viewed_ids, as_list=True)
            
            # 保存收藏
            safe_json_save(CONFIG.favorites_file, self.favorites)
            
            # 保存浏览历史（限制大小）
            history_to_save = []
            for post in self.browse_history[-CONFIG.max_browse_history:]:
                history_to_save.append({
                    'id': post['id'],
                    'tags': post.get('tags', ''),
                    'rating': post.get('rating', 'q'),
                    'score': post.get('score', 0),
                    'sample_url': post.get('sample_url', ''),
                    'preview_url': post.get('preview_url', ''),
                    'file_url': post.get('file_url', ''),
                    'file_size': post.get('file_size', 0),
                    'width': post.get('width', 0),
                    'height': post.get('height', 0),
                })
            safe_json_save(CONFIG.browse_history_file, history_to_save)
            
            # 保存会话信息
            session = {
                'mode': self.mode,
                'page': self.page,
                'history_index': self.history_index,
                'viewed_count': len(self.viewed_ids),
                'last_viewed_id': (
                    str(self.current_post['id'])
                    if self.current_post else None
                ),
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            safe_json_save(CONFIG.session_file, session)
            
            # 保存用户设置
            self.user_settings.save(CONFIG.settings_file)