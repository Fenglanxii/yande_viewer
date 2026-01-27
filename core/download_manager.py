"""
下载管理器模块。

提供带断点续传、重试机制和取消能力的下载管理：
- 断点续传：自动检测已下载部分并继续
- 指数退避重试：网络故障时自动重试
- 取消支持：单任务取消和全局取消
- 进度回调：实时下载进度通知
- 磁盘空间检查：防止磁盘写满

线程安全性
----------
所有公共方法均为线程安全。

Example
-------
>>> manager = DownloadManager(max_workers=3)
>>> token = manager.submit_download(
...     post={"id": 123, "file_url": "https://..."},
...     base_dir="/downloads",
...     on_progress=lambda pid, pct: print(f"{pid}: {pct:.1f}%"),
... )
>>> manager.cancel_download("123")
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Tuple

import requests

from config import CONFIG
from core.event_bus import EVENT_BUS, Event, EventType
from utils.security import SafePath, url_validator

logger = logging.getLogger("YandeViewer")


@dataclass
class CancellationToken:
    """
    取消令牌。

    用于协作式取消下载任务。下载循环会定期检查此令牌状态。

    Attributes
    ----------
    is_cancelled : bool
        是否已请求取消
    reason : str or None
        取消原因
    """

    _event: threading.Event = field(default_factory=threading.Event)
    reason: Optional[str] = None

    @property
    def is_cancelled(self) -> bool:
        """检查是否已请求取消。"""
        return self._event.is_set()

    def cancel(self, reason: str = "用户请求取消") -> None:
        """
        请求取消。

        Parameters
        ----------
        reason : str
            取消原因，用于日志和错误回调
        """
        self.reason = reason
        self._event.set()


@dataclass
class DownloadTask:
    """
    下载任务记录。

    Attributes
    ----------
    post_id : str
        帖子 ID
    post : dict
        原始帖子数据
    base_dir : str
        下载基础目录
    cancel_token : CancellationToken
        取消令牌
    on_progress : callable or None
        进度回调
    on_complete : callable or None
        完成回调
    on_error : callable or None
        错误回调
    created_at : float
        任务创建时间戳
    """

    post_id: str
    post: dict
    base_dir: str
    cancel_token: CancellationToken
    on_progress: Optional[Callable[[str, float], None]] = None
    on_complete: Optional[Callable[[str, str], None]] = None
    on_error: Optional[Callable[[str, str], None]] = None
    created_at: float = field(default_factory=time.time)


class DownloadManager:
    """
    下载管理器。

    提供带断点续传和取消机制的并发下载功能。

    Attributes
    ----------
    pending_count : int
        等待中的下载任务数量
    resuming_count : int
        恢复中的下载任务数量
    active_downloads : set of str
        活动下载的 post_id 集合

    Example
    -------
    >>> manager = DownloadManager(max_workers=3)
    >>> token = manager.submit_download(post, base_dir, on_progress=callback)
    >>> token.cancel()  # 取消下载
    """

    def __init__(self, max_workers: int = 3) -> None:
        """
        初始化下载管理器。

        Parameters
        ----------
        max_workers : int
            最大并发下载线程数，默认为 3
        """
        if max_workers < 1:
            raise ValueError(f"max_workers 必须 >= 1，当前值: {max_workers}")

        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="DL",
        )
        self.pending_count = 0
        self.resuming_count = 0
        self.active_downloads: Set[str] = set()
        self.failed_downloads: Dict[str, int] = {}

        self._tasks: Dict[str, DownloadTask] = {}
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()

        from core.session import SESSION

        self.session = SESSION
        self.base_path = Path(CONFIG.base_dir).resolve()

    def submit_download(
        self,
        post: dict,
        base_dir: str,
        on_progress: Optional[Callable[[str, float], None]] = None,
        on_complete: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> Optional[CancellationToken]:
        """
        提交下载任务。

        Parameters
        ----------
        post : dict
            帖子数据字典，必须包含 'id' 和 'file_url' 字段
        base_dir : str
            下载文件保存的基础目录
        on_progress : callable, optional
            进度回调，签名为 (post_id, percentage) -> None
        on_complete : callable, optional
            完成回调，签名为 (post_id, file_path) -> None
        on_error : callable, optional
            错误回调，签名为 (post_id, error_message) -> None

        Returns
        -------
        CancellationToken or None
            取消令牌，任务已存在时返回 None
        """
        post_id = str(post.get("id", ""))
        if not post_id:
            logger.warning("无效的帖子数据：缺少 id 字段")
            return None

        with self._lock:
            if post_id in self.active_downloads:
                logger.debug("下载任务已存在: %s", post_id)
                return None

            self.active_downloads.add(post_id)
            self.pending_count += 1

            cancel_token = CancellationToken()
            task = DownloadTask(
                post_id=post_id,
                post=post,
                base_dir=base_dir,
                cancel_token=cancel_token,
                on_progress=on_progress,
                on_complete=on_complete,
                on_error=on_error,
            )
            self._tasks[post_id] = task

        EVENT_BUS.publish(
            Event(EventType.DOWNLOAD_STARTED, {"post_id": post_id})
        )

        self.executor.submit(self._execute_download, task)
        return cancel_token

    def cancel_download(
        self, post_id: str, reason: str = "用户取消"
    ) -> bool:
        """
        取消指定的下载任务。

        Parameters
        ----------
        post_id : str
            要取消的帖子 ID
        reason : str
            取消原因

        Returns
        -------
        bool
            是否成功发起取消
        """
        with self._lock:
            task = self._tasks.get(post_id)
            if task:
                task.cancel_token.cancel(reason)
                logger.info("已请求取消下载 %s: %s", post_id, reason)
                return True
        return False

    def cancel_all(self, reason: str = "批量取消") -> int:
        """
        取消所有进行中的下载任务。

        Parameters
        ----------
        reason : str
            取消原因

        Returns
        -------
        int
            发起取消的任务数量
        """
        with self._lock:
            count = 0
            for task in self._tasks.values():
                if not task.cancel_token.is_cancelled:
                    task.cancel_token.cancel(reason)
                    count += 1
            logger.info("已请求取消 %d 个任务: %s", count, reason)
            return count

    def submit_resume(
        self,
        post_id: str,
        folder: str,
        base_dir: str,
        on_complete: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """
        恢复未完成的下载。

        从 API 获取帖子信息后，利用断点续传机制恢复下载。
        已下载的 .tmp 文件会被自动检测并续传。

        Parameters
        ----------
        post_id : str
            帖子 ID
        folder : str
            目标文件夹名称 (Safe/Questionable/Explicit)
        base_dir : str
            基础下载目录
        on_complete : callable, optional
            完成回调，签名为 (post_id, file_path) -> None
        on_error : callable, optional
            错误回调，签名为 (post_id, error_message) -> None
        """
        with self._lock:
            if post_id in self.active_downloads:
                logger.debug("恢复任务已存在: %s", post_id)
                return

            self.resuming_count += 1

        def do_resume():
            try:
                # 从 API 获取帖子信息
                resp = self.session.get(
                    CONFIG.api_url,
                    params={"tags": f"id:{post_id}"},
                    timeout=CONFIG.download.timeout,
                )

                if resp.status_code != 200:
                    raise Exception(f"API 错误: HTTP {resp.status_code}")

                posts = resp.json()
                if not posts:
                    raise Exception(f"未找到帖子: {post_id}")

                post = posts[0]

                # 提交下载任务（断点续传会自动检测 tmp 文件）
                self.submit_download(
                    post,
                    base_dir,
                    on_complete=on_complete,
                    on_error=on_error,
                )

            except Exception as e:
                logger.error("恢复下载失败 [%s]: %s", post_id, e)
                if on_error:
                    try:
                        on_error(post_id, str(e))
                    except Exception:
                        pass
            finally:
                with self._lock:
                    self.resuming_count = max(0, self.resuming_count - 1)

        self.executor.submit(do_resume)

    def _execute_download(self, task: DownloadTask) -> None:
        """执行下载任务（内部方法）。"""
        post_id = task.post_id
        url = task.post.get("file_url")

        # URL 验证
        if not url or not url_validator.validate(url):
            self._finish_download(
                task, success=False, error="无效的文件 URL"
            )
            return

        # 路径解析
        try:
            path = self._get_file_path(task.post, task.base_dir)
        except Exception as e:
            self._finish_download(
                task, success=False, error=f"路径错误: {e}"
            )
            return

        tmp_path = path.with_suffix(path.suffix + ".tmp")

        # 检查文件是否已存在
        if path.exists():
            logger.debug("文件已存在: %s", path)
            self._finish_download(task, success=True, file_path=str(path))
            return

        # 执行下载
        success, error_msg = self._do_download(url, path, tmp_path, task)

        if success:
            self._finish_download(task, success=True, file_path=str(path))
        else:
            self._finish_download(task, success=False, error=error_msg)

    def _do_download(
        self,
        url: str,
        path: Path,
        tmp_path: Path,
        task: DownloadTask,
    ) -> Tuple[bool, Optional[str]]:
        """执行实际下载（带重试和取消检查）。"""
        post_id = task.post_id
        cancel_token = task.cancel_token

        for attempt in range(CONFIG.download.max_retries):
            if cancel_token.is_cancelled:
                return False, f"已取消: {cancel_token.reason}"

            try:
                context = {
                    "url": url,
                    "path": path,
                    "tmp_path": tmp_path,
                    "task": task,
                    "session": self.session,
                    "headers": {},
                    "downloaded_size": 0,
                    "total_size": None,
                    "file_mode": "wb",
                }

                self._prepare_resume(context)
                resp = self._send_request(context)
                if resp is None:
                    return True, None

                self._write_chunks(context, resp)
                self._verify_and_finalize(context)

                return True, None

            except Exception as e:
                if not self._handle_retry_exception(task, attempt, e):
                    return False, str(e)

        return False, "已达到最大重试次数"

    def _prepare_resume(self, context: dict) -> None:
        """准备断点续传。"""
        tmp_path = context["tmp_path"]
        if tmp_path.exists():
            try:
                context["downloaded_size"] = tmp_path.stat().st_size
            except OSError:
                context["downloaded_size"] = 0

        if context["downloaded_size"] > 0:
            context["headers"]["Range"] = f'bytes={context["downloaded_size"]}-'
            logger.info(
                "从 %.1fMB 处恢复下载 %s",
                context["downloaded_size"] / 1024 / 1024,
                context["task"].post_id,
            )

    def _send_request(
        self, context: dict
    ) -> Optional[requests.Response]:
        """发起 HTTP 请求并处理响应。"""
        session = context["session"]
        url = context["url"]
        headers = context["headers"]

        resp = session.get(
            url,
            headers=headers,
            stream=True,
            timeout=CONFIG.download.timeout,
            verify=True,
            allow_redirects=False,
        )

        if resp.status_code == 416:
            if (
                context["tmp_path"].exists()
                and context["tmp_path"].stat().st_size > 0
            ):
                context["tmp_path"].rename(context["path"])
                logger.info(
                    "下载完成 %s（文件已完整）",
                    context["task"].post_id,
                )
                return None
            else:
                context["downloaded_size"] = 0
                resp = session.get(
                    url,
                    stream=True,
                    timeout=CONFIG.download.timeout,
                    verify=True,
                )

        if resp.status_code == 206:
            context["file_mode"] = "ab"
        elif resp.status_code == 200:
            context["file_mode"] = "wb"
            context["downloaded_size"] = 0
        elif 300 <= resp.status_code < 400:
            raise Exception(f"不允许重定向 ({resp.status_code})")
        else:
            raise Exception(f"HTTP {resp.status_code}")

        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                context["total_size"] = (
                    int(content_length) + context["downloaded_size"]
                )
            except ValueError:
                pass

        if context["total_size"] and not self._check_disk_space(
            context["total_size"]
        ):
            raise Exception("磁盘空间不足或文件超过大小限制")

        return resp

    def _write_chunks(self, context: dict, resp: requests.Response) -> None:
        """流式写入文件。"""
        tmp_path = context["tmp_path"]
        task = context["task"]
        cancel_token = task.cancel_token
        post_id = task.post_id
        on_progress = task.on_progress

        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        last_progress_time = time.time()

        with open(tmp_path, context["file_mode"]) as f:
            for chunk in resp.iter_content(
                chunk_size=CONFIG.download.chunk_size
            ):
                if cancel_token.is_cancelled:
                    raise Exception(f"已取消: {cancel_token.reason}")

                if not chunk:
                    continue

                f.write(chunk)
                bytes_written += len(chunk)

                now = time.time()
                if (
                    on_progress
                    and context["total_size"]
                    and (now - last_progress_time) > 0.1
                ):
                    current = context["downloaded_size"] + bytes_written
                    percentage = (current / context["total_size"]) * 100
                    try:
                        on_progress(post_id, percentage)
                    except Exception as e:
                        logger.warning("进度回调错误: %s", e)
                    last_progress_time = now

                if context["total_size"] and (
                    context["downloaded_size"] + bytes_written
                ) > context["total_size"] + 5 * 1024:
                    raise Exception("下载大小超过 Content-Length")

    def _verify_and_finalize(self, context: dict) -> None:
        """校验文件完整性并完成下载。"""
        tmp_path = context["tmp_path"]
        path = context["path"]
        task = context["task"]
        post_id = task.post_id
        on_progress = task.on_progress

        final_size = tmp_path.stat().st_size

        if context["total_size"] and final_size < context["total_size"]:
            progress = (final_size / context["total_size"]) * 100
            raise Exception(f"下载不完整: {progress:.1f}%")

        tmp_path.rename(path)

        if on_progress:
            try:
                on_progress(post_id, 100.0)
            except Exception:
                pass

        logger.info(
            "下载完成 %s (%.1fMB)",
            post_id,
            final_size / 1024 / 1024,
        )

    def _handle_retry_exception(
        self, task: DownloadTask, attempt: int, error: Exception
    ) -> bool:
        """处理下载异常并决定是否重试。"""
        post_id = task.post_id
        max_retries = CONFIG.download.max_retries

        logger.warning(
            "%s 尝试 %d/%d 失败: %s",
            post_id,
            attempt + 1,
            max_retries,
            error,
        )

        if attempt >= max_retries - 1:
            logger.error(
                "%s 下载失败，已重试 %d 次: %s",
                post_id,
                max_retries,
                error,
            )
            return False

        delay = min(CONFIG.download.retry_delay * (2**attempt), 60)

        for _ in range(int(delay * 10)):
            if task.cancel_token.is_cancelled:
                return False
            time.sleep(0.1)

        return True

    def _finish_download(
        self,
        task: DownloadTask,
        success: bool,
        file_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """完成下载（清理状态并触发回调）。"""
        post_id = task.post_id

        with self._lock:
            self.active_downloads.discard(post_id)
            self.pending_count = max(0, self.pending_count - 1)
            self._tasks.pop(post_id, None)

            if not success:
                self.failed_downloads[post_id] = (
                    self.failed_downloads.get(post_id, 0) + 1
                )

        if success:
            if task.on_complete:
                try:
                    task.on_complete(post_id, file_path)
                except Exception as e:
                    logger.warning("完成回调错误: %s", e)

            EVENT_BUS.publish(
                Event(
                    EventType.DOWNLOAD_COMPLETED,
                    {"post_id": post_id, "path": file_path},
                )
            )
        else:
            if task.on_error:
                try:
                    task.on_error(post_id, error or "未知错误")
                except Exception as e:
                    logger.warning("错误回调错误: %s", e)

            is_cancelled = task.cancel_token.is_cancelled
            event_type = (
                EventType.DOWNLOAD_CANCELLED
                if is_cancelled
                else EventType.DOWNLOAD_FAILED
            )

            EVENT_BUS.publish(
                Event(event_type, {"post_id": post_id, "error": error})
            )

    def _get_file_path(self, post: dict, base_dir: str) -> Path:
        """生成安全的文件保存路径。"""
        folder = {"s": "Safe", "q": "Questionable", "e": "Explicit"}.get(
            post.get("rating", "q"), "Questionable"
        )

        url = post.get("file_url", "")
        if not url_validator.validate(url):
            raise ValueError("无效的 file_url")

        ext = os.path.splitext(url.split("?", 1)[0])[1] or ".jpg"

        raw_tags = post.get("tags", "")
        raw_tags = "".join(
            c for c in raw_tags if c.isalnum() or c in " _-"
        )
        tags = raw_tags[:50]
        filename = f"{post['id']}_{tags.replace(' ', '_')}{ext}"
        safe_filename = SafePath.sanitize_filename(filename)

        base = Path(base_dir)
        return SafePath.join_under(base, folder, safe_filename)

    def _check_disk_space(self, needed_bytes: int) -> bool:
        """检查磁盘空间是否充足。"""
        try:
            total, used, free = shutil.disk_usage(self.base_path)

            if free < CONFIG.download.disk_min_free_gb * 1024**3:
                logger.warning(
                    "磁盘剩余空间不足: %.2f GB",
                    free / 1024**3,
                )
                return False

            if needed_bytes > CONFIG.max_file_mb * 1024**2:
                logger.warning("单文件超过大小限制")
                return False

            return True

        except Exception as e:
            logger.warning("磁盘空间检查失败: %s", e)
            return False

    def get_status(self) -> Dict[str, int]:
        """
        获取下载管理器状态。

        Returns
        -------
        dict
            包含 pending, resuming, active, failed 计数的字典
        """
        with self._lock:
            return {
                "pending": self.pending_count,
                "resuming": self.resuming_count,
                "active": len(self.active_downloads),
                "failed": len(self.failed_downloads),
            }

    def shutdown(self, wait: bool = False, timeout: float = 5.0) -> None:
        """
        关闭下载管理器。

        Parameters
        ----------
        wait : bool
            是否等待所有任务完成
        timeout : float
            等待超时时间（秒）
        """
        self._shutdown_event.set()
        self.cancel_all("正在关闭")
        self.executor.shutdown(wait=wait, cancel_futures=True)
        logger.info("下载管理器已关闭")