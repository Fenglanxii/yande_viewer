"""工具模块。

提供安全路径验证、URL 校验、输入法控制、文件原子操作等通用工具函数。

模块结构:
    - security: 路径安全、URL 验证
    - ime_controller: 输入法控制（Windows）
    - helpers: 文件操作、JSON 处理、DPI 支持
    - backup_manager: 数据备份与恢复

Example:
    >>> from utils import safe_json_load, safe_json_save
    >>> config = safe_json_load("config.json", default=dict)
    >>> safe_json_save("config.json", config)
"""

from __future__ import annotations

from .security import SafePath, UrlValidator, url_validator
from .ime_controller import IMEController, create_ime_controller, IME
from .helpers import (
    atomic_write,
    clean_tags,
    safe_json_load,
    safe_json_save,
    file_lock,
    format_file_size,
    ensure_dir,
    get_system_scale_factor,
    init_dpi_awareness,
    scaled_size,
)
from .backup_manager import BackupManager

__all__ = [
    # 安全工具
    "SafePath",
    "UrlValidator",
    "url_validator",
    # 输入法控制
    "IMEController",
    "create_ime_controller",
    "IME",
    # 文件工具
    "atomic_write",
    "clean_tags",
    "safe_json_load",
    "safe_json_save",
    "file_lock",
    "format_file_size",
    "ensure_dir",
    "get_system_scale_factor",
    "init_dpi_awareness",
    "scaled_size",
    # 备份管理
    "BackupManager",
]

__version__ = "2.0.0"
__author__ = "YandeViewer Contributors"