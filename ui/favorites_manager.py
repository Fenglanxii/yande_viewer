"""收藏管理器模块。

本模块提供收藏图片的浏览、预览、删除等功能，
支持分类筛选、标签搜索和缩略图显示。

Example:
    基本使用示例::

        manager = FavoritesManager(parent=main_window, base_dir="./favorites")
        manager.show()

Note:
    如果 PIL 库可用，将使用 PIL 生成高质量缩略图，
    否则回退到 Qt 原生缩放。
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QCursor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
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


def _load_thumbnail(
    path: str,
    size: tuple[int, int],
) -> Optional[QPixmap]:
    """加载并生成缩略图。

    Args:
        path: 图片文件路径。
        size: 目标尺寸，格式为 (width, height)。

    Returns:
        成功返回 QPixmap 对象，失败返回 None。

    Note:
        优先使用 PIL 生成高质量缩略图，若 PIL 不可用则使用 Qt 原生方法。
    """
    if not os.path.exists(path):
        logger.debug("文件不存在: %s", path)
        return None

    try:
        if HAS_PIL:
            with Image.open(path) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                # 转换为 RGBA 确保兼容性
                if img.mode not in ("RGBA", "RGB"):
                    img = img.convert("RGBA")
                qimg = ImageQt(img)
                return QPixmap.fromImage(qimg)
        else:
            # 使用 Qt 原生加载
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return None
            return pixmap.scaled(
                size[0],
                size[1],
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    except Exception as e:
        logger.debug("缩略图加载失败 [%s]: %s", path, e)
        return None


class FavoritesManager:
    """收藏管理器。

    管理收藏窗口的显示和生命周期。

    Attributes:
        parent: 父窗口引用。
        base_dir: 收藏文件根目录。
        window: 当前打开的收藏窗口实例。

    Example:
        创建并显示收藏管理器::

            manager = FavoritesManager(parent=self, base_dir="./favorites")
            manager.show()
    """

    def __init__(self, parent: QWidget, base_dir: str) -> None:
        """初始化收藏管理器。

        Args:
            parent: 父窗口。
            base_dir: 收藏文件根目录。
        """
        self.parent = parent
        self.base_dir = base_dir
        self.window: Optional[FavoritesWindow] = None

    def show(self) -> None:
        """显示收藏管理器窗口。

        如果窗口已存在且可见，则将其激活并置于前台。
        """
        if self.window is not None and self.window.isVisible():
            self.window.raise_()
            self.window.activateWindow()
            return

        self.window = FavoritesWindow(self.parent, self.base_dir, self)
        self.window.show()


class FavoritesWindow(QMainWindow):
    """收藏管理器窗口。

    提供图片浏览、预览、过滤和管理功能。

    Attributes:
        SUPPORTED_FORMATS: 支持的图片格式集合。
        CATEGORY_COLORS: 分类颜色映射字典。
    """

    # 支持的图片格式
    SUPPORTED_FORMATS: frozenset[str] = frozenset(
        {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    )

    # 分类颜色映射
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
        """初始化收藏窗口。

        Args:
            parent: 父窗口。
            base_dir: 收藏文件根目录。
            manager: 收藏管理器实例。
        """
        super().__init__(parent)

        self.base_dir = base_dir
        self.manager = manager
        self.thumbnails: Dict[str, QPixmap] = {}
        self.all_files: List[Dict[str, Any]] = []
        self.filtered_files: List[Dict[str, Any]] = []
        self.card_widgets: List[QWidget] = []

        # 窗口设置
        self.setWindowTitle("📁 收藏管理器")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(f"background-color: {C.bg_base};")

        self._setup_ui()
        self._load_files()

        # 居中显示
        if parent is not None:
            self.move(
                parent.x() + (parent.width() - 1000) // 2,
                parent.y() + (parent.height() - 700) // 2,
            )

    def _setup_ui(self) -> None:
        """构建用户界面。"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 工具栏
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)

        # 滚动区域
        scroll = self._create_scroll_area()
        main_layout.addWidget(scroll)

    def _create_toolbar(self) -> QFrame:
        """创建工具栏。

        Returns:
            工具栏 QFrame 组件。
        """
        toolbar = QFrame()
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet(f"background-color: {C.bg_elevated};")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)

        # 过滤按钮组
        filter_frame = self._create_filter_buttons()
        toolbar_layout.addWidget(filter_frame)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索标签...")
        self.search_input.setFixedWidth(200)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {C.bg_surface};
                color: {C.text_primary};
                border: none;
                border-radius: {L.radius_md}px;
                padding: 6px 10px;
            }}
        """)
        self.search_input.textChanged.connect(self._apply_filter)
        toolbar_layout.addWidget(self.search_input)

        toolbar_layout.addStretch()

        # 统计标签
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet(f"color: {C.text_muted};")
        toolbar_layout.addWidget(self.stats_label)

        # 刷新按钮
        refresh_btn = self._create_tool_button("🔄", self._load_files, C.info)
        toolbar_layout.addWidget(refresh_btn)

        # 打开文件夹按钮
        folder_btn = self._create_tool_button(
            "📂", self._open_folder, C.bg_surface
        )
        toolbar_layout.addWidget(folder_btn)

        return toolbar

    def _create_filter_buttons(self) -> QFrame:
        """创建过滤按钮组。

        Returns:
            包含过滤按钮的 QFrame 组件。
        """
        filter_frame = QFrame()
        filter_frame.setStyleSheet("background-color: transparent;")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(5)

        self.filter_group = QButtonGroup(self)
        self.filter_buttons: Dict[str, QRadioButton] = {}

        filter_options = ["All", "Safe", "Questionable", "Explicit"]
        for filter_name in filter_options:
            rb = QRadioButton(filter_name)
            rb.setStyleSheet(f"""
                QRadioButton {{
                    color: {C.text_primary};
                    font-size: 10px;
                }}
            """)
            if filter_name == "All":
                rb.setChecked(True)
            rb.toggled.connect(self._apply_filter)
            self.filter_group.addButton(rb)
            self.filter_buttons[filter_name] = rb
            filter_layout.addWidget(rb)

        return filter_frame

    def _create_tool_button(
        self,
        icon: str,
        callback: Any,
        bg_color: str,
    ) -> QPushButton:
        """创建工具栏按钮。

        Args:
            icon: 按钮图标（emoji）。
            callback: 点击回调函数。
            bg_color: 背景颜色。

        Returns:
            配置好的 QPushButton 实例。
        """
        btn = QPushButton(icon)
        btn.setFixedSize(32, 32)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: {C.text_primary};
                border: none;
                border-radius: {L.radius_md}px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                opacity: 0.8;
            }}
        """)
        btn.clicked.connect(callback)
        return btn

    def _create_scroll_area(self) -> QScrollArea:
        """创建滚动区域。

        Returns:
            配置好的 QScrollArea 实例。
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
            }}
            QScrollBar:vertical {{
                background: {C.bg_surface};
                width: 12px;
            }}
            QScrollBar::handle:vertical {{
                background: {C.bg_hover};
                min-height: 20px;
                border-radius: 6px;
            }}
        """)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet(f"background-color: {C.bg_base};")
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)

        scroll.setWidget(self.scroll_content)
        return scroll

    def _load_files(self) -> None:
        """加载收藏文件列表。

        扫描所有分类目录，收集图片文件信息。
        """
        self.all_files = []
        categories = ["Safe", "Questionable", "Explicit"]

        for category in categories:
            folder = Path(self.base_dir) / category
            if not folder.exists():
                continue

            for file_path in folder.iterdir():
                # 跳过临时文件和非图片文件
                if file_path.suffix == ".tmp":
                    continue
                if file_path.suffix.lower() not in self.SUPPORTED_FORMATS:
                    continue

                try:
                    stat = file_path.stat()
                except OSError as e:
                    logger.debug("无法获取文件状态 [%s]: %s", file_path, e)
                    continue

                # 解析文件名
                name = file_path.stem
                parts = name.split("_", 1)

                self.all_files.append({
                    "path": str(file_path),
                    "filename": file_path.name,
                    "category": category,
                    "id": parts[0],
                    "tags": parts[1].replace("_", " ") if len(parts) > 1 else "",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })

        # 按修改时间降序排序
        self.all_files.sort(key=lambda x: x["mtime"], reverse=True)
        self._apply_filter()

        logger.debug("已加载 %d 个收藏文件", len(self.all_files))

    def _apply_filter(self) -> None:
        """应用筛选条件。

        根据分类选择和搜索关键词筛选文件。
        """
        # 获取选中的分类
        selected_category: Optional[str] = None
        for name, btn in self.filter_buttons.items():
            if btn.isChecked():
                selected_category = name
                break

        query = self.search_input.text().lower().strip()

        # 执行筛选
        self.filtered_files = [
            f
            for f in self.all_files
            if (selected_category == "All" or f["category"] == selected_category)
            and (not query or query in f["tags"].lower())
        ]

        # 更新统计
        self.stats_label.setText(
            f"{len(self.filtered_files)} / {len(self.all_files)}"
        )
        self._display_files()

    def _display_files(self) -> None:
        """显示筛选后的文件列表。"""
        # 清除旧卡片
        for widget in self.card_widgets:
            widget.deleteLater()
        self.card_widgets.clear()

        # 清除布局中的所有项
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 处理空列表情况
        if not self.filtered_files:
            empty_label = QLabel("📭 无图片")
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {C.text_muted};
                    font-size: 14px;
                }}
            """)
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid_layout.addWidget(empty_label, 0, 0)
            return

        # 计算列数
        cols = max(1, self.width() // 220)

        # 创建卡片
        for i, file_info in enumerate(self.filtered_files):
            row = i // cols
            col = i % cols
            card = self._create_card(file_info)
            self.grid_layout.addWidget(card, row, col)
            self.card_widgets.append(card)

    def _create_card(self, file_info: Dict[str, Any]) -> QFrame:
        """创建文件卡片。

        Args:
            file_info: 文件信息字典。

        Returns:
            卡片 QFrame 组件。
        """
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {C.bg_surface};
                border-radius: {L.radius_md}px;
                padding: 4px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(4)

        # 缩略图
        thumb_label = QLabel()
        thumb_size = CONFIG.thumbnail_size
        thumb_label.setFixedSize(*thumb_size)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # 加载或获取缓存的缩略图
        path = file_info["path"]
        if path not in self.thumbnails:
            pixmap = _load_thumbnail(path, thumb_size)
            if pixmap is not None:
                self.thumbnails[path] = pixmap

        if path in self.thumbnails:
            thumb_label.setPixmap(
                self.thumbnails[path].scaled(
                    *thumb_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            thumb_label.setText("⚠")
            thumb_label.setStyleSheet(f"color: {C.warning}; font-size: 24px;")

        # 绑定点击事件
        thumb_label.mousePressEvent = lambda e, f=file_info: self._on_thumb_click(e, f)
        card_layout.addWidget(thumb_label)

        # ID 标签
        id_label = QLabel(f"ID:{file_info['id']}")
        id_label.setStyleSheet(f"""
            QLabel {{
                color: {C.text_primary};
                font-family: {T.font_mono};
                font-size: 8px;
            }}
        """)
        id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(id_label)

        # 分类和大小标签
        color = self.CATEGORY_COLORS.get(file_info["category"], C.text_muted)
        size_mb = file_info["size"] / 1024 / 1024
        info_label = QLabel(f"{file_info['category']} {size_mb:.1f}MB")
        info_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 8px;
            }}
        """)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(info_label)

        return card

    def _on_thumb_click(
        self,
        event: "QMouseEvent",
        file_info: Dict[str, Any],
    ) -> None:
        """处理缩略图点击事件。

        Args:
            event: 鼠标事件。
            file_info: 文件信息字典。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._preview(file_info)
        elif event.button() == Qt.MouseButton.RightButton:
            self._context_menu(event, file_info)

    def _preview(self, file_info: Dict[str, Any]) -> None:
        """预览图片。

        Args:
            file_info: 文件信息字典。
        """
        try:
            preview = PreviewDialog(self, file_info)
            preview.exec()
        except Exception as e:
            logger.error("预览失败: %s", e)
            QMessageBox.warning(self, "错误", f"预览失败: {e}")

    def _context_menu(
        self,
        event: "QMouseEvent",
        file_info: Dict[str, Any],
    ) -> None:
        """显示右键菜单。

        Args:
            event: 鼠标事件。
            file_info: 文件信息字典。
        """
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {C.bg_elevated};
                color: {C.text_primary};
                border: 1px solid {C.border_default};
                border-radius: {L.radius_md}px;
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
                subprocess.run(
                    ["open", path],
                    check=False,
                    capture_output=True,
                )
            else:
                subprocess.run(
                    ["xdg-open", path],
                    check=False,
                    capture_output=True,
                )
        except Exception as e:
            logger.warning("打开文件夹失败: %s", e)
            QMessageBox.warning(self, "错误", f"无法打开文件夹: {e}")

    def _open_location(self, filepath: str) -> None:
        """在文件管理器中打开文件位置。

        Args:
            filepath: 文件路径。
        """
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
            logger.warning("打开文件位置失败: %s", e)

    def _delete(self, file_info: Dict[str, Any]) -> None:
        """删除文件。

        Args:
            file_info: 文件信息字典。
        """
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 {file_info['filename']} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(file_info["path"])
                self.all_files.remove(file_info)
                self.thumbnails.pop(file_info["path"], None)
                self._apply_filter()
                logger.info("已删除文件: %s", file_info["filename"])
            except Exception as e:
                logger.error("删除失败: %s", e)
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    def resizeEvent(self, event: Any) -> None:
        """处理窗口大小改变事件。

        Args:
            event: 调整大小事件。
        """
        super().resizeEvent(event)
        if self.filtered_files:
            self._display_files()

    def closeEvent(self, event: Any) -> None:
        """处理窗口关闭事件。

        Args:
            event: 关闭事件。
        """
        self.thumbnails.clear()
        super().closeEvent(event)


class PreviewDialog(QDialog):
    """图片预览对话框。

    提供大尺寸图片预览功能。
    """

    def __init__(self, parent: QWidget, file_info: Dict[str, Any]) -> None:
        """初始化预览对话框。

        Args:
            parent: 父窗口。
            file_info: 文件信息字典。
        """
        super().__init__(parent)
        self.file_info = file_info

        self.setWindowTitle(f"预览 - {file_info['id']}")
        self.setMinimumSize(900, 700)
        self.setStyleSheet(f"background-color: {C.bg_base};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pixmap = _load_thumbnail(file_info["path"], (880, 650))
        if pixmap is not None:
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("加载失败")
            image_label.setStyleSheet(f"color: {C.error};")

        layout.addWidget(image_label)

    def keyPressEvent(self, event: Any) -> None:
        """处理按键事件。

        Args:
            event: 按键事件。

        Note:
            按 Escape 或 Space 键关闭对话框。
        """
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.accept()
        else:
            super().keyPressEvent(event)