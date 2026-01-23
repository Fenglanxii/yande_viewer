"""
用户设置模块。

提供可持久化的用户偏好设置管理，包括：
- 筛选设置 (FilterSettings)
- 性能设置 (PerformanceSettings)
- 界面设置 (UISettings)

所有设置都支持序列化到 JSON 文件，并可随时恢复。

Example
-------
>>> settings = UserSettings.load()
>>> settings.filter.min_score = 10
>>> settings.save()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Set, Tuple

logger = logging.getLogger("YandeViewer")


# =============================================================================
# 筛选设置
# =============================================================================

@dataclass
class FilterSettings:
    """
    内容筛选设置。

    Attributes
    ----------
    min_score : int
        最低分数阈值，默认为 0
    ratings : set of str
        允许的评级集合，可选值: 's'(safe), 'q'(questionable), 'e'(explicit)
    high_score_first : bool
        是否优先显示高分内容，默认为 True
    """

    min_score: int = 0
    ratings: Set[str] = field(default_factory=lambda: {"s", "q", "e"})
    high_score_first: bool = True

    def __post_init__(self) -> None:
        """验证并规范化设置。"""
        # 确保 min_score 为非负整数
        if not isinstance(self.min_score, int):
            self.min_score = int(self.min_score)
        self.min_score = max(0, self.min_score)

        # 确保 ratings 是集合且只包含有效值
        valid_ratings = {"s", "q", "e"}
        if isinstance(self.ratings, (list, tuple)):
            self.ratings = set(self.ratings)
        self.ratings = self.ratings & valid_ratings

        # 如果 ratings 为空，设置为全部
        if not self.ratings:
            self.ratings = valid_ratings.copy()

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为可序列化的字典。

        Returns
        -------
        dict
            可用于 JSON 序列化的字典
        """
        return {
            "min_score": self.min_score,
            "ratings": sorted(list(self.ratings)),
            "high_score_first": self.high_score_first,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FilterSettings":
        """
        从字典创建实例。

        Parameters
        ----------
        data : dict
            配置字典

        Returns
        -------
        FilterSettings
            设置实例
        """
        return cls(
            min_score=data.get("min_score", 0),
            ratings=set(data.get("ratings", ["s", "q", "e"])),
            high_score_first=data.get("high_score_first", True),
        )

    def copy(self) -> "FilterSettings":
        """
        创建深拷贝。

        Returns
        -------
        FilterSettings
            新的设置实例
        """
        return FilterSettings(
            min_score=self.min_score,
            ratings=self.ratings.copy(),
            high_score_first=self.high_score_first,
        )

    def matches(self, score: int, rating: str) -> bool:
        """
        检查内容是否符合筛选条件。

        Parameters
        ----------
        score : int
            内容分数
        rating : str
            内容评级

        Returns
        -------
        bool
            是否符合条件
        """
        if score < self.min_score:
            return False
        if rating.lower() not in self.ratings:
            return False
        return True


# =============================================================================
# 性能设置
# =============================================================================

@dataclass
class PerformanceSettings:
    """
    性能相关设置。

    Attributes
    ----------
    preload_count : int
        预加载图片数量，范围 1-50
    max_image_cache : int
        最大图片缓存数量，范围 10-200
    download_workers : int
        下载工作线程数，范围 1-10
    load_timeout : int
        加载超时时间（秒），范围 5-120
    """

    preload_count: int = 15
    max_image_cache: int = 50
    download_workers: int = 3
    load_timeout: int = 15

    # 配置范围限制
    _LIMITS: ClassVar[Dict[str, Tuple[int, int]]] = {
        "preload_count": (1, 50),
        "max_image_cache": (10, 200),
        "download_workers": (1, 10),
        "load_timeout": (5, 120),
    }

    def __post_init__(self) -> None:
        """验证并规范化设置。"""
        for attr, (min_val, max_val) in self._LIMITS.items():
            value = getattr(self, attr)
            if not isinstance(value, int):
                value = int(value)
            value = max(min_val, min(max_val, value))
            object.__setattr__(self, attr, value)

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为可序列化的字典。

        Returns
        -------
        dict
            可用于 JSON 序列化的字典
        """
        return {
            "preload_count": self.preload_count,
            "max_image_cache": self.max_image_cache,
            "download_workers": self.download_workers,
            "load_timeout": self.load_timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PerformanceSettings":
        """
        从字典创建实例。

        Parameters
        ----------
        data : dict
            配置字典

        Returns
        -------
        PerformanceSettings
            设置实例
        """
        return cls(
            preload_count=data.get("preload_count", 15),
            max_image_cache=data.get("max_image_cache", 50),
            download_workers=data.get("download_workers", 3),
            load_timeout=data.get("load_timeout", 15),
        )

    def copy(self) -> "PerformanceSettings":
        """
        创建深拷贝。

        Returns
        -------
        PerformanceSettings
            新的设置实例
        """
        return PerformanceSettings(
            preload_count=self.preload_count,
            max_image_cache=self.max_image_cache,
            download_workers=self.download_workers,
            load_timeout=self.load_timeout,
        )


# =============================================================================
# 界面设置
# =============================================================================

@dataclass
class UISettings:
    """
    界面相关设置。

    Attributes
    ----------
    thumbnail_size : tuple of int
        缩略图尺寸 (宽, 高)，范围 50-500
    show_saved_badge : bool
        是否显示已保存标记
    show_score_highlight : bool
        是否高亮高分内容
    high_score_threshold : int
        高分阈值
    """

    thumbnail_size: Tuple[int, int] = (200, 200)
    show_saved_badge: bool = True
    show_score_highlight: bool = True
    high_score_threshold: int = 10

    def __post_init__(self) -> None:
        """验证并规范化设置。"""
        # 确保 thumbnail_size 是元组
        if isinstance(self.thumbnail_size, list):
            self.thumbnail_size = tuple(self.thumbnail_size)

        # 验证缩略图尺寸
        if len(self.thumbnail_size) != 2:
            self.thumbnail_size = (200, 200)

        # 确保尺寸在合理范围内
        w, h = self.thumbnail_size
        w = max(50, min(500, int(w)))
        h = max(50, min(500, int(h)))
        self.thumbnail_size = (w, h)

        # 验证高分阈值
        self.high_score_threshold = max(0, int(self.high_score_threshold))

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为可序列化的字典。

        Returns
        -------
        dict
            可用于 JSON 序列化的字典
        """
        return {
            "thumbnail_size": list(self.thumbnail_size),
            "show_saved_badge": self.show_saved_badge,
            "show_score_highlight": self.show_score_highlight,
            "high_score_threshold": self.high_score_threshold,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UISettings":
        """
        从字典创建实例。

        Parameters
        ----------
        data : dict
            配置字典

        Returns
        -------
        UISettings
            设置实例
        """
        return cls(
            thumbnail_size=tuple(data.get("thumbnail_size", [200, 200])),
            show_saved_badge=data.get("show_saved_badge", True),
            show_score_highlight=data.get("show_score_highlight", True),
            high_score_threshold=data.get("high_score_threshold", 10),
        )

    def copy(self) -> "UISettings":
        """
        创建深拷贝。

        Returns
        -------
        UISettings
            新的设置实例
        """
        return UISettings(
            thumbnail_size=self.thumbnail_size,
            show_saved_badge=self.show_saved_badge,
            show_score_highlight=self.show_score_highlight,
            high_score_threshold=self.high_score_threshold,
        )


# =============================================================================
# 用户设置汇总
# =============================================================================

@dataclass
class UserSettings:
    """
    用户设置汇总类。

    包含所有用户可配置的设置项，并提供加载/保存功能。

    Attributes
    ----------
    filter : FilterSettings
        筛选设置
    performance : PerformanceSettings
        性能设置
    ui : UISettings
        界面设置

    Example
    -------
    >>> settings = UserSettings.load()
    >>> settings.filter.min_score = 10
    >>> settings.save()
    """

    filter: FilterSettings = field(default_factory=FilterSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    ui: UISettings = field(default_factory=UISettings)

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为可序列化的字典。

        Returns
        -------
        dict
            可用于 JSON 序列化的字典，包含版本标记
        """
        return {
            "filter": self.filter.to_dict(),
            "performance": self.performance.to_dict(),
            "ui": self.ui.to_dict(),
            "_version": 1,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserSettings":
        """
        从字典创建实例。

        Parameters
        ----------
        data : dict
            配置字典

        Returns
        -------
        UserSettings
            设置实例
        """
        return cls(
            filter=FilterSettings.from_dict(data.get("filter", {})),
            performance=PerformanceSettings.from_dict(data.get("performance", {})),
            ui=UISettings.from_dict(data.get("ui", {})),
        )

    def save(self, path: str = "user_settings.json") -> bool:
        """
        保存设置到文件。

        使用原子写入操作确保数据完整性。

        Parameters
        ----------
        path : str
            保存路径，默认为 "user_settings.json"

        Returns
        -------
        bool
            是否保存成功
        """
        try:
            parent = Path(path).parent
            if parent and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)

            temp_path = f"{path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

            os.replace(temp_path, path)

            logger.debug("设置已保存到 %s", path)
            return True

        except PermissionError:
            logger.error("无权写入设置文件: %s", path)
        except OSError as e:
            logger.error("保存设置失败: %s", e)
        except Exception as e:
            logger.exception("保存设置时发生意外错误: %s", e)

        return False

    @classmethod
    def load(cls, path: str = "user_settings.json") -> "UserSettings":
        """
        从文件加载设置。

        Parameters
        ----------
        path : str
            设置文件路径，默认为 "user_settings.json"

        Returns
        -------
        UserSettings
            设置实例，加载失败时返回默认设置
        """
        if not os.path.exists(path):
            logger.debug("设置文件未找到，使用默认设置")
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                logger.warning("设置文件为空，使用默认设置")
                return cls()

            data = json.loads(content)

            if not isinstance(data, dict):
                logger.warning("设置文件根元素不是字典，使用默认设置")
                return cls()

            logger.debug("从 %s 加载设置成功", path)
            return cls.from_dict(data)

        except json.JSONDecodeError as e:
            logger.warning("设置文件 JSON 格式无效: %s", e)
        except PermissionError:
            logger.warning("无权读取设置文件: %s", path)
        except OSError as e:
            logger.warning("读取设置文件失败: %s", e)
        except Exception as e:
            logger.exception("加载设置时发生意外错误: %s", e)

        return cls()

    def copy(self) -> "UserSettings":
        """
        创建设置的深拷贝。

        Returns
        -------
        UserSettings
            新的设置实例
        """
        return UserSettings(
            filter=self.filter.copy(),
            performance=self.performance.copy(),
            ui=self.ui.copy(),
        )

    def reset(self) -> None:
        """重置为默认设置。"""
        self.filter = FilterSettings()
        self.performance = PerformanceSettings()
        self.ui = UISettings()

    def validate(self) -> List[str]:
        """
        验证设置有效性。

        Returns
        -------
        list of str
            错误消息列表，空列表表示验证通过
        """
        errors: List[str] = []

        if not self.filter.ratings:
            errors.append("至少需要选择一个评级")

        if self.performance.preload_count > self.performance.max_image_cache:
            errors.append(
                f"preload_count ({self.performance.preload_count}) 不应超过 "
                f"max_image_cache ({self.performance.max_image_cache})"
            )

        return errors