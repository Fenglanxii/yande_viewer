"""
应用配置模块。

提供应用程序的核心配置管理，与设计令牌（UI 视觉配置）分离。
支持从 JSON 文件加载/保存配置，并提供完整的类型安全和验证。

设计原则
--------
- AppConfig: 应用逻辑配置（路径、API、性能、安全）
- DesignTokens: UI 设计配置（颜色、间距、字体）- 见 design_tokens.py

Example
-------
>>> config = AppConfig.load()
>>> print(config.api_url)
>>> config.save()
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .design_tokens import TOKENS, ColorTokens, DesignTokens


# =============================================================================
# 日志配置
# =============================================================================

def _setup_logging() -> logging.Logger:
    """
    配置并返回应用日志器。

    Returns
    -------
    logging.Logger
        配置完成的日志器实例
    """
    logger = logging.getLogger("YandeViewer")

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # 文件处理器
        try:
            file_handler = logging.FileHandler(
                "yande_viewer.log",
                encoding="utf-8",
                delay=True,
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(threadName)s] "
                "%(name)s: %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except (OSError, PermissionError) as e:
            logger.warning("无法创建日志文件: %s", e)

    return logger


logger = _setup_logging()


# =============================================================================
# 下载配置
# =============================================================================

@dataclass
class DownloadConfig:
    """
    下载相关配置类。

    提供类型安全的下载参数配置。

    Attributes
    ----------
    max_retries : int
        最大重试次数，默认为 3
    timeout : int
        请求超时时间（秒），默认为 30
    retry_delay : float
        重试延迟时间（秒），默认为 2.0
    chunk_size : int
        分块下载大小（字节），默认为 8192
    max_file_mb : int
        单文件最大大小（MB），默认为 200
    disk_min_free_gb : float
        最小磁盘剩余空间（GB），默认为 1.0

    Raises
    ------
    ValueError
        当配置值超出有效范围时抛出
    """

    max_retries: int = 3
    timeout: int = 30
    retry_delay: float = 2.0
    chunk_size: int = 8192
    max_file_mb: int = 200
    disk_min_free_gb: float = 1.0

    def __post_init__(self) -> None:
        """验证配置值的有效性。"""
        if self.max_retries < 0:
            raise ValueError(f"max_retries 必须 >= 0，当前值: {self.max_retries}")
        if self.timeout <= 0:
            raise ValueError(f"timeout 必须 > 0，当前值: {self.timeout}")
        if self.retry_delay < 0:
            raise ValueError(f"retry_delay 必须 >= 0，当前值: {self.retry_delay}")
        if self.chunk_size <= 0:
            raise ValueError(f"chunk_size 必须 > 0，当前值: {self.chunk_size}")
        if self.max_file_mb <= 0:
            raise ValueError(f"max_file_mb 必须 > 0，当前值: {self.max_file_mb}")
        if self.disk_min_free_gb < 0:
            raise ValueError(
                f"disk_min_free_gb 必须 >= 0，当前值: {self.disk_min_free_gb}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式。

        Returns
        -------
        dict
            可用于 JSON 序列化的字典
        """
        return {
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "retry_delay": self.retry_delay,
            "chunk_size": self.chunk_size,
            "max_file_mb": self.max_file_mb,
            "disk_min_free_gb": self.disk_min_free_gb,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DownloadConfig":
        """
        从字典创建配置实例。

        Parameters
        ----------
        data : dict
            配置字典

        Returns
        -------
        DownloadConfig
            配置实例
        """
        return cls(
            max_retries=int(data.get("max_retries", 3)),
            timeout=int(data.get("timeout", 30)),
            retry_delay=float(data.get("retry_delay", 2.0)),
            chunk_size=int(data.get("chunk_size", 8192)),
            max_file_mb=int(data.get("max_file_mb", 200)),
            disk_min_free_gb=float(data.get("disk_min_free_gb", 1.0)),
        )


# =============================================================================
# 应用配置
# =============================================================================

@dataclass
class AppConfig:
    """
    应用配置类。

    职责分离设计：
    - AppConfig: 应用逻辑配置（路径、API、性能、安全）
    - DesignTokens: UI 设计配置（颜色、间距、字体）

    通过组合模式整合两者，保持向后兼容。

    Attributes
    ----------
    base_dir : str
        下载文件的基础目录
    api_url : str
        API 请求地址
    limit : int
        每页加载数量
    max_download_workers : int
        最大下载并发数

    Example
    -------
    >>> config = AppConfig.load()
    >>> print(config.api_url)
    >>> config.colors.accent  # 访问颜色配置
    """

    # 文件路径配置
    base_dir: str = "love"
    history_file: str = "viewed.json"
    favorites_file: str = "favorites.json"
    browse_history_file: str = "browse_history.json"
    session_file: str = "session.json"
    settings_file: str = "user_settings.json"
    config_file: str = "config.json"

    # API 配置
    api_url: str = "https://yande.re/post.json"
    limit: int = 100
    request_timeout: Tuple[int, int] = (10, 30)

    # 性能配置
    max_download_workers: int = 3
    preload_workers: int = 8
    preload_count: int = 15
    max_image_cache: int = 50
    max_browse_history: int = 500
    high_score_threshold: int = 10

    # 下载配置
    download: DownloadConfig = field(default_factory=DownloadConfig)
    max_file_mb: int = 512

    # 资源限制
    max_memory_mb: int = 500
    disk_max_gb: int = 20

    # 安全配置
    allowed_schemes: Set[str] = field(
        default_factory=lambda: {"https"}
    )
    allowed_hosts: Set[str] = field(
        default_factory=lambda: {"yande.re", "files.yande.re"}
    )

    # UI 配置
    thumbnail_size: Tuple[int, int] = (200, 200)
    window_default_size: Tuple[int, int] = (1300, 900)
    window_min_size: Tuple[int, int] = (800, 600)

    # 设计令牌（组合模式）
    _tokens: DesignTokens = field(default_factory=lambda: TOKENS, repr=False)

    # =========================================================================
    # 设计令牌访问代理
    # =========================================================================

    @property
    def tokens(self) -> DesignTokens:
        """获取设计令牌对象。"""
        return self._tokens

    @property
    def colors(self) -> ColorTokens:
        """获取颜色配置对象。"""
        return self._tokens.colors

    # =========================================================================
    # 向后兼容：旧版颜色别名（带废弃警告）
    # =========================================================================

    def _deprecated_color_warning(self, old_name: str, new_path: str) -> None:
        """发出颜色属性废弃警告。"""
        warnings.warn(
            f"CONFIG.{old_name} 已废弃，请使用 CONFIG.colors.{new_path}",
            DeprecationWarning,
            stacklevel=3,
        )

    @property
    def bg(self) -> str:
        """背景色（已废弃，请使用 colors.bg_base）。"""
        self._deprecated_color_warning("bg", "bg_base")
        return self.colors.bg_base

    @property
    def panel(self) -> str:
        """面板色（已废弃，请使用 colors.bg_elevated）。"""
        self._deprecated_color_warning("panel", "bg_elevated")
        return self.colors.bg_elevated

    @property
    def text(self) -> str:
        """文字色（已废弃，请使用 colors.text_primary）。"""
        self._deprecated_color_warning("text", "text_primary")
        return self.colors.text_primary

    @property
    def accent(self) -> str:
        """强调色（已废弃，请使用 colors.accent）。"""
        self._deprecated_color_warning("accent", "accent")
        return self.colors.accent

    @property
    def safe(self) -> str:
        """安全色（已废弃，请使用 colors.success）。"""
        self._deprecated_color_warning("safe", "success")
        return self.colors.success

    @property
    def warn(self) -> str:
        """警告色（已废弃，请使用 colors.warning）。"""
        self._deprecated_color_warning("warn", "warning")
        return self.colors.warning

    @property
    def highlight(self) -> str:
        """高亮色（已废弃，请使用 colors.info）。"""
        self._deprecated_color_warning("highlight", "info")
        return self.colors.info

    @property
    def muted(self) -> str:
        """弱化色（已废弃，请使用 colors.text_muted）。"""
        self._deprecated_color_warning("muted", "text_muted")
        return self.colors.text_muted

    @property
    def card_bg(self) -> str:
        """卡片背景（已废弃，请使用 colors.bg_elevated）。"""
        self._deprecated_color_warning("card_bg", "bg_elevated")
        return self.colors.bg_elevated

    # =========================================================================
    # 字典式访问（兼容旧代码）
    # =========================================================================

    def __getitem__(self, key: str) -> Any:
        """
        支持 CONFIG['key'] 访问（已废弃）。

        Parameters
        ----------
        key : str
            配置键名

        Returns
        -------
        Any
            配置值

        Raises
        ------
        KeyError
            当键名不存在时抛出

        Warns
        -----
        DeprecationWarning
            此访问方式已废弃
        """
        warnings.warn(
            f"CONFIG['{key}'] 已废弃，请使用 CONFIG.{key}",
            DeprecationWarning,
            stacklevel=2,
        )

        # 映射旧键名到新结构
        mapping: Dict[str, Tuple[str, str]] = {
            "download_max_retries": ("download", "max_retries"),
            "download_timeout": ("download", "timeout"),
            "download_retry_delay": ("download", "retry_delay"),
            "download_chunk_size": ("download", "chunk_size"),
            "disk_min_free_gb": ("download", "disk_min_free_gb"),
        }

        if key in mapping:
            section, attr = mapping[key]
            section_obj = getattr(self, section, None)
            if section_obj is not None:
                return getattr(section_obj, attr)

        if hasattr(self, key):
            return getattr(self, key)

        raise KeyError(f"未知的配置键: {key}")

    def __setitem__(self, key: str, value: Any) -> None:
        """
        支持 CONFIG['key'] = value（已废弃）。

        Warns
        -----
        DeprecationWarning
            此访问方式已废弃
        """
        warnings.warn(
            f"CONFIG['{key}'] = value 已废弃，请使用 CONFIG.{key} = value",
            DeprecationWarning,
            stacklevel=2,
        )

        if hasattr(self, key) and not key.startswith("_"):
            setattr(self, key, value)
        else:
            raise KeyError(f"无法设置配置键: {key}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        安全获取配置项。

        Parameters
        ----------
        key : str
            配置键名
        default : Any, optional
            默认值，默认为 None

        Returns
        -------
        Any
            配置值或默认值
        """
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default

    # =========================================================================
    # 序列化
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为可序列化的字典。

        Returns
        -------
        dict
            可用于 JSON 序列化的配置字典
        """
        result: Dict[str, Any] = {}

        for key, value in self.__dict__.items():
            if key.startswith("_"):
                continue

            if isinstance(value, DownloadConfig):
                result[key] = value.to_dict()
            elif isinstance(value, (tuple, frozenset)):
                result[key] = list(value)
            elif isinstance(value, set):
                result[key] = sorted(list(value))
            elif isinstance(value, (str, int, float, bool, list, dict, type(None))):
                result[key] = value

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """
        从字典创建配置实例。

        Parameters
        ----------
        data : dict
            配置字典

        Returns
        -------
        AppConfig
            配置实例
        """
        tuple_fields = {
            "request_timeout",
            "thumbnail_size",
            "window_default_size",
            "window_min_size",
        }
        set_fields = {"allowed_schemes", "allowed_hosts"}

        processed: Dict[str, Any] = {}

        for key, value in data.items():
            if key.startswith("_"):
                continue

            try:
                if key in tuple_fields and isinstance(value, (list, tuple)):
                    processed[key] = tuple(value)
                elif key in set_fields and isinstance(value, (list, set)):
                    processed[key] = set(value)
                elif key == "download" and isinstance(value, dict):
                    processed[key] = DownloadConfig.from_dict(value)
                else:
                    processed[key] = value
            except (TypeError, ValueError) as e:
                logger.warning("跳过无效的配置键 '%s': %s", key, e)
                continue

        return cls(**processed)

    # =========================================================================
    # 文件操作
    # =========================================================================

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AppConfig":
        """
        从文件加载配置。

        Parameters
        ----------
        path : str, optional
            配置文件路径，默认为 "config.json"

        Returns
        -------
        AppConfig
            配置实例，加载失败时返回默认配置
        """
        path = path or "config.json"

        if not os.path.exists(path):
            logger.info("配置文件未找到，使用默认配置")
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                logger.warning("配置文件为空，使用默认配置")
                return cls()

            data = json.loads(content)

            if not isinstance(data, dict):
                logger.warning("配置文件根元素不是字典，使用默认配置")
                return cls()

            logger.info("从 %s 加载配置成功", path)
            return cls.from_dict(data)

        except json.JSONDecodeError as e:
            logger.warning("配置文件 JSON 格式无效: %s", e)
        except PermissionError:
            logger.warning("无权读取配置文件: %s", path)
        except OSError as e:
            logger.warning("读取配置文件失败: %s", e)
        except Exception as e:
            logger.exception("加载配置时发生意外错误: %s", e)

        return cls()

    def save(self, path: Optional[str] = None) -> bool:
        """
        保存配置到文件。

        使用原子写入操作确保数据完整性。

        Parameters
        ----------
        path : str, optional
            配置文件路径，默认使用 self.config_file

        Returns
        -------
        bool
            是否保存成功
        """
        path = path or self.config_file

        try:
            data = self.to_dict()

            parent = Path(path).parent
            if parent and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)

            temp_path = f"{path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            os.replace(temp_path, path)

            logger.info("配置已保存到 %s", path)
            return True

        except PermissionError:
            logger.error("无权写入配置文件: %s", path)
        except OSError as e:
            logger.error("保存配置失败: %s", e)
        except Exception as e:
            logger.exception("保存配置时发生意外错误: %s", e)

        return False

    # =========================================================================
    # 验证
    # =========================================================================

    def validate(self) -> List[str]:
        """
        验证配置有效性。

        Returns
        -------
        list of str
            错误消息列表，空列表表示验证通过
        """
        errors: List[str] = []

        # 检查路径
        if not self.base_dir:
            errors.append("base_dir 不能为空")
        elif any(c in self.base_dir for c in '<>:"|?*'):
            errors.append(f"base_dir 包含无效字符: {self.base_dir}")

        # 检查数值范围
        if not (1 <= self.limit <= 1000):
            errors.append(f"limit 必须在 1-1000 之间，当前值: {self.limit}")

        if not (1 <= self.max_download_workers <= 10):
            errors.append(
                f"max_download_workers 必须在 1-10 之间，"
                f"当前值: {self.max_download_workers}"
            )

        if self.max_image_cache < 10:
            errors.append(
                f"max_image_cache 必须 >= 10，当前值: {self.max_image_cache}"
            )

        if self.preload_count < 0:
            errors.append(f"preload_count 必须 >= 0，当前值: {self.preload_count}")

        # 检查元组格式
        if len(self.request_timeout) != 2:
            errors.append("request_timeout 必须是 (connect, read) 格式的元组")

        if len(self.thumbnail_size) != 2:
            errors.append("thumbnail_size 必须是 (width, height) 格式的元组")

        # 检查安全设置
        if "http" in self.allowed_schemes:
            errors.append("不建议使用 HTTP 协议，存在安全风险")

        if not self.api_url.startswith("https://"):
            errors.append("api_url 应使用 HTTPS 协议以确保安全")

        return errors

    def ensure_dirs(self) -> None:
        """
        确保必要的目录存在。

        创建以下目录：
        - base_dir
        - base_dir/Safe
        - base_dir/Questionable
        - base_dir/Explicit
        """
        dirs = [
            self.base_dir,
            os.path.join(self.base_dir, "Safe"),
            os.path.join(self.base_dir, "Questionable"),
            os.path.join(self.base_dir, "Explicit"),
        ]

        for d in dirs:
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error("创建目录 '%s' 失败: %s", d, e)

    def is_url_allowed(self, url: str) -> bool:
        """
        检查 URL 是否在允许范围内。

        Parameters
        ----------
        url : str
            要检查的 URL

        Returns
        -------
        bool
            URL 是否允许访问
        """
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)

            if parsed.scheme not in self.allowed_schemes:
                return False

            if parsed.netloc not in self.allowed_hosts:
                return False

            return True
        except Exception:
            return False


# =============================================================================
# 全局实例
# =============================================================================

def _create_config() -> AppConfig:
    """创建并验证全局配置实例。"""
    config = AppConfig.load()

    errors = config.validate()
    for err in errors:
        logger.warning("配置验证警告: %s", err)

    try:
        config.ensure_dirs()
    except Exception as e:
        logger.warning("创建目录失败: %s", e)

    return config


CONFIG = _create_config()