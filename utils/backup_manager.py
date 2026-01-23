"""备份与恢复管理器。

提供用户数据的完整备份和恢复功能，支持数据完整性校验。

主要功能:
    - 创建包含所有用户数据的 JSON 备份文件
    - 从备份文件恢复用户数据
    - SHA256 校验和验证数据完整性
    - 恢复前自动备份当前数据

Example:
    >>> manager = BackupManager()
    >>> manager.create_backup("./backup.json")
    True
    >>> info = manager.get_backup_info("./backup.json")
    >>> manager.restore_backup("./backup.json")
    True
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

from utils.helpers import atomic_write

logger = logging.getLogger(__name__)

# 备份文件格式版本
BACKUP_VERSION: str = "1.0"

# 应用程序版本
APP_VERSION: str = "2.0"

# 默认备份目录名
DEFAULT_BACKUP_DIR: str = "backup_temp"


class BackupStats(TypedDict, total=False):
    """备份统计信息类型定义。"""

    viewed_count: int
    favorites_count: int
    history_count: int


class BackupInfo(TypedDict, total=False):
    """备份信息类型定义。"""

    version: str
    app_version: str
    created_at: str
    stats: BackupStats
    checksum_valid: bool


class BackupFileConfig(TypedDict):
    """备份文件配置类型定义。"""

    key: str
    filename: str
    default: Any


# 需要备份的文件配置列表
BACKUP_FILES: list[BackupFileConfig] = [
    {"key": "viewed", "filename": "viewed.json", "default": []},
    {"key": "favorites", "filename": "favorites.json", "default": {}},
    {"key": "browse_history", "filename": "browse_history.json", "default": []},
    {"key": "session", "filename": "session.json", "default": {}},
    {"key": "user_settings", "filename": "user_settings.json", "default": {}},
]


class BackupError(Exception):
    """备份操作异常基类。"""

    pass


class BackupChecksumError(BackupError):
    """校验和验证失败异常。"""

    pass


class BackupVersionError(BackupError):
    """备份版本不兼容异常。"""

    pass


class BackupManager:
    """备份与恢复管理器。

    管理用户数据文件的备份与恢复操作，支持数据完整性验证。

    Attributes:
        base_path: 数据文件的基础目录路径。

    Example:
        >>> manager = BackupManager(base_path="./data")
        >>> success = manager.create_backup("./my_backup.json")
        >>> if success:
        ...     print("备份成功")
    """

    def __init__(self, base_path: str | Path | None = None) -> None:
        """初始化备份管理器。

        Args:
            base_path: 数据文件的基础目录路径。
                如果为 None，则使用当前工作目录。
        """
        if base_path is None:
            self.base_path = Path.cwd()
        elif isinstance(base_path, str):
            self.base_path = Path(base_path)
        else:
            self.base_path = base_path

        # 验证路径有效性
        if not self.base_path.is_absolute():
            self.base_path = self.base_path.resolve()

    @staticmethod
    def _compute_checksum(data: dict[str, Any]) -> str:
        """计算数据的 SHA256 校验和。

        Args:
            data: 需要计算校验和的字典数据。

        Returns:
            64 位十六进制格式的 SHA256 哈希值。

        Note:
            使用 sort_keys=True 确保相同数据产生相同的校验和。
        """
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_checksum(backup_data: dict[str, Any]) -> bool:
        """验证备份数据的校验和。

        Args:
            backup_data: 完整的备份数据字典，应包含 'checksum' 和 'data' 键。

        Returns:
            如果校验和匹配返回 True，否则返回 False。
        """
        stored_checksum = backup_data.get("checksum", "")
        data = backup_data.get("data", {})

        if not stored_checksum or not isinstance(data, dict):
            return False

        computed = BackupManager._compute_checksum(data)
        return stored_checksum == computed

    def _load_file(self, filename: str, default: Any) -> Any:
        """加载单个 JSON 数据文件。

        Args:
            filename: 相对于 base_path 的文件名。
            default: 文件不存在或加载失败时返回的默认值。

        Returns:
            加载的 JSON 数据，或失败时返回默认值。
        """
        filepath = self.base_path / filename

        if not filepath.exists():
            logger.debug("文件不存在，使用默认值: %s", filename)
            return default

        if not filepath.is_file():
            logger.warning("路径不是文件: %s", filepath)
            return default

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                if not content.strip():
                    logger.debug("文件为空: %s", filename)
                    return default
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("JSON 解析错误 [%s]: %s", filename, e)
            return default
        except PermissionError as e:
            logger.warning("文件权限不足 [%s]: %s", filename, e)
            return default
        except OSError as e:
            logger.warning("文件读取失败 [%s]: %s", filename, e)
            return default

    def _collect_data(self) -> dict[str, Any]:
        """收集所有需要备份的数据。

        Returns:
            包含所有备份数据的字典。
        """
        data: dict[str, Any] = {}

        for file_config in BACKUP_FILES:
            key = file_config["key"]
            filename = file_config["filename"]
            default = file_config["default"]
            data[key] = self._load_file(filename, default)

        return data

    def _calculate_stats(self, data: dict[str, Any]) -> BackupStats:
        """计算备份数据的统计信息。

        Args:
            data: 备份数据字典。

        Returns:
            包含各类数据数量的统计信息。
        """
        viewed = data.get("viewed", [])
        favorites = data.get("favorites", {})
        history = data.get("browse_history", [])

        return BackupStats(
            viewed_count=len(viewed) if isinstance(viewed, list) else 0,
            favorites_count=len(favorites) if isinstance(favorites, dict) else 0,
            history_count=len(history) if isinstance(history, list) else 0,
        )

    def create_backup(
        self,
        save_path: str | Path,
        on_complete: Callable[[bool, str], None] | None = None,
    ) -> bool:
        """创建数据备份文件。

        将所有用户数据打包为单个 JSON 文件，包含校验和用于验证完整性。

        Args:
            save_path: 备份文件的保存路径。
            on_complete: 操作完成后的回调函数。
                接收两个参数: (success: bool, message: str)。

        Returns:
            操作是否成功。

        Raises:
            无异常抛出，错误通过返回值和回调通知。

        Example:
            >>> def callback(success, msg):
            ...     print(f"{'成功' if success else '失败'}: {msg}")
            >>> manager.create_backup("backup.json", on_complete=callback)
        """
        try:
            save_path = Path(save_path)

            # 验证保存路径
            if save_path.is_dir():
                error_msg = f"保存路径是目录而非文件: {save_path}"
                logger.error(error_msg)
                if on_complete:
                    on_complete(False, error_msg)
                return False

            # 确保父目录存在
            save_path.parent.mkdir(parents=True, exist_ok=True)

            # 收集数据
            data = self._collect_data()
            stats = self._calculate_stats(data)

            # 构建备份结构
            backup = {
                "version": BACKUP_VERSION,
                "app_version": APP_VERSION,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "stats": dict(stats),
                "checksum": self._compute_checksum(data),
                "data": data,
            }

            # 序列化并保存
            content = json.dumps(backup, ensure_ascii=False, indent=2)
            atomic_write(str(save_path), content)

            # 构建成功消息
            msg = (
                f"备份成功！\n"
                f"已查看: {stats.get('viewed_count', 0)} 张\n"
                f"收藏: {stats.get('favorites_count', 0)} 张\n"
                f"历史: {stats.get('history_count', 0)} 条\n"
                f"保存至: {save_path.name}"
            )

            logger.info("备份已创建: %s", save_path)

            if on_complete:
                on_complete(True, msg)

            return True

        except PermissionError as e:
            error_msg = f"权限不足，无法写入备份文件: {e}"
            logger.error(error_msg)
            if on_complete:
                on_complete(False, error_msg)
            return False

        except OSError as e:
            error_msg = f"文件系统错误: {e}"
            logger.error(error_msg, exc_info=True)
            if on_complete:
                on_complete(False, error_msg)
            return False

        except Exception as e:
            error_msg = f"备份失败: {e}"
            logger.error(error_msg, exc_info=True)
            if on_complete:
                on_complete(False, error_msg)
            return False

    def restore_backup(
        self,
        backup_path: str | Path,
        skip_checksum: bool = False,
        on_complete: Callable[[bool, str], None] | None = None,
    ) -> bool:
        """从备份文件恢复数据。

        恢复前会自动备份当前数据，以便在恢复失败时可以回滚。

        Args:
            backup_path: 备份文件路径。
            skip_checksum: 是否跳过校验和验证。
                仅在确认备份文件可信时设置为 True。
            on_complete: 操作完成后的回调函数。
                接收两个参数: (success: bool, message: str)。

        Returns:
            操作是否成功。

        Warning:
            恢复操作会覆盖当前的用户数据文件。
            建议在恢复前手动创建当前数据的备份。
        """
        try:
            backup_path = Path(backup_path)

            # 验证备份文件
            if not backup_path.exists():
                raise FileNotFoundError(f"备份文件不存在: {backup_path}")

            if not backup_path.is_file():
                raise ValueError(f"路径不是文件: {backup_path}")

            # 检查文件大小（防止恶意大文件）
            file_size = backup_path.stat().st_size
            max_size = 100 * 1024 * 1024  # 100MB 限制
            if file_size > max_size:
                raise ValueError(f"备份文件过大: {file_size} 字节")

            # 读取备份文件
            with open(backup_path, "r", encoding="utf-8") as f:
                backup = json.load(f)

            # 基础格式验证
            if not isinstance(backup, dict):
                raise ValueError("无效的备份文件格式: 根元素不是对象")

            if "data" not in backup:
                raise ValueError("无效的备份文件格式: 缺少 data 字段")

            # 版本兼容性检查
            backup_version = backup.get("version", "0")
            if backup_version != BACKUP_VERSION:
                logger.warning(
                    "备份版本不匹配: 文件=%s, 当前=%s",
                    backup_version,
                    BACKUP_VERSION,
                )

            # 校验和验证
            if not skip_checksum:
                if not self._verify_checksum(backup):
                    raise BackupChecksumError("备份文件校验失败，数据可能已损坏")

            data = backup.get("data", {})

            # 备份当前数据（保护措施）
            self._backup_current()

            # 恢复各个文件
            restored_count = 0
            failed_files: list[str] = []

            for file_config in BACKUP_FILES:
                key = file_config["key"]
                filename = file_config["filename"]

                if key not in data:
                    logger.debug("备份中不包含: %s", key)
                    continue

                try:
                    filepath = self.base_path / filename
                    content = json.dumps(
                        data[key],
                        ensure_ascii=False,
                        indent=2,
                    )
                    atomic_write(str(filepath), content)
                    restored_count += 1
                    logger.info("已恢复: %s", filename)
                except Exception as e:
                    logger.warning("恢复失败 [%s]: %s", filename, e)
                    failed_files.append(filename)

            # 构建结果消息
            stats = backup.get("stats", {})
            msg_parts = [
                f"恢复完成！",
                f"恢复文件: {restored_count} 个",
                f"已查看: {stats.get('viewed_count', '?')} 张",
                f"收藏: {stats.get('favorites_count', '?')} 张",
            ]

            if failed_files:
                msg_parts.append(f"失败: {', '.join(failed_files)}")

            msg_parts.append("\n请重启程序以加载恢复的数据")
            msg = "\n".join(msg_parts)

            logger.info("备份恢复完成: %s", backup_path)

            if on_complete:
                on_complete(True, msg)

            return True

        except json.JSONDecodeError as e:
            error_msg = f"备份文件 JSON 格式错误: {e}"
            logger.error(error_msg)
            if on_complete:
                on_complete(False, error_msg)
            return False

        except BackupChecksumError as e:
            error_msg = str(e)
            logger.error(error_msg)
            if on_complete:
                on_complete(False, error_msg)
            return False

        except FileNotFoundError as e:
            error_msg = str(e)
            logger.error(error_msg)
            if on_complete:
                on_complete(False, error_msg)
            return False

        except Exception as e:
            error_msg = f"恢复失败: {e}"
            logger.error(error_msg, exc_info=True)
            if on_complete:
                on_complete(False, error_msg)
            return False

    def _backup_current(self) -> None:
        """在恢复前备份当前数据文件。

        创建带时间戳的备份副本，用于恢复失败时的回滚。
        """
        backup_dir = self.base_path / DEFAULT_BACKUP_DIR

        try:
            backup_dir.mkdir(exist_ok=True)
        except OSError as e:
            logger.warning("无法创建备份目录: %s", e)
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        for file_config in BACKUP_FILES:
            key = file_config["key"]
            filename = file_config["filename"]
            src = self.base_path / filename

            if not src.exists():
                continue

            try:
                dst = backup_dir / f"{key}_{timestamp}.bak"
                shutil.copy2(src, dst)
                logger.debug("当前数据已备份: %s -> %s", filename, dst.name)
            except OSError as e:
                logger.warning("备份当前数据失败 [%s]: %s", filename, e)

    def get_backup_info(self, backup_path: str | Path) -> BackupInfo | None:
        """获取备份文件的元信息（不执行恢复操作）。

        Args:
            backup_path: 备份文件路径。

        Returns:
            包含备份信息的字典，解析失败时返回 None。

        Example:
            >>> info = manager.get_backup_info("backup.json")
            >>> if info:
            ...     print(f"创建时间: {info['created_at']}")
            ...     print(f"校验和有效: {info['checksum_valid']}")
        """
        try:
            backup_path = Path(backup_path)

            if not backup_path.exists() or not backup_path.is_file():
                return None

            with open(backup_path, "r", encoding="utf-8") as f:
                backup = json.load(f)

            if not isinstance(backup, dict):
                return None

            return BackupInfo(
                version=backup.get("version", "?"),
                app_version=backup.get("app_version", "?"),
                created_at=backup.get("created_at", "?"),
                stats=backup.get("stats", {}),
                checksum_valid=self._verify_checksum(backup),
            )

        except json.JSONDecodeError:
            logger.debug("获取备份信息失败: JSON 解析错误")
            return None
        except OSError as e:
            logger.debug("获取备份信息失败: %s", e)
            return None