"""
安全工具模块

提供路径安全验证和URL验证功能，防止路径遍历和SSRF攻击。
"""

from __future__ import annotations

import socket
import ipaddress
import logging
import re
from pathlib import Path, PurePath
from urllib.parse import urlparse
from typing import Union, Iterable, Set, Optional, FrozenSet
from functools import lru_cache

logger = logging.getLogger(__name__)


class SafePath:
    """
    安全路径工具，防止路径遍历攻击
    
    Example:
        >>> safe_name = SafePath.sanitize_filename("../../../etc/passwd")
        >>> # 返回 "etc_passwd" (移除危险字符)
        >>> 
        >>> path = SafePath.join_under("/app/data", "user/../secret.txt")
        >>> # 抛出 ValueError
    """

    # 危险路径模式
    DANGEROUS_PATTERNS = (
        re.compile(r'\.\.[\\/]'),      # ../
        re.compile(r'[\\/]\.\.[\\/]'), # /../
        re.compile(r'^\.\.[\\/]'),     # 开头的 ../
    )
    
    # Windows 保留名称
    WINDOWS_RESERVED = frozenset({
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10))
    })
    
    # 非法字符（用于文件名）
    ILLEGAL_CHARS = frozenset('\/:*?"<>|')

    @classmethod
    def sanitize_filename(cls, name: str, max_len: int = 200) -> str:
        """
        清理文件名，移除非法字符
        
        Args:
            name: 原始文件名
            max_len: 最大长度
        
        Returns:
            安全的文件名
        """
        if not name:
            return "file"
        
        # 移除非法字符
        name = "".join(
            c for c in name
            if 32 <= ord(c) < 127 
            and c not in cls.ILLEGAL_CHARS
        )
        
        # 移除首尾空格和点（Windows 限制）
        name = name.strip(" .")
        
        if not name:
            return "file"
        
        # 限制长度（保留扩展名）
        if len(name) > max_len:
            if "." in name:
                base, ext = name.rsplit(".", 1)
                max_base = max_len - len(ext) - 1
                if max_base > 0:
                    name = f"{base[:max_base]}.{ext}"
                else:
                    name = name[:max_len]
            else:
                name = name[:max_len]
        
        # 检查 Windows 保留名
        base_name = name.split(".")[0].upper()
        if base_name in cls.WINDOWS_RESERVED:
            name = f"_{name}"
        
        return name

    @classmethod
    def join_under(cls, base: Union[str, Path], *paths: str) -> Path:
        """
        安全路径拼接（防止路径遍历）
        
        Args:
            base: 基础目录
            *paths: 要拼接的子路径
        
        Returns:
            安全的绝对路径
        
        Raises:
            ValueError: 检测到路径遍历
        """
        base = Path(base).resolve()
        
        # 预检查：拒绝包含危险模式的输入
        for p in paths:
            for pattern in cls.DANGEROUS_PATTERNS:
                if pattern.search(p):
                    raise ValueError(f"Dangerous path pattern detected: {p}")
        
        # 拼接并解析
        joined = base.joinpath(*paths)
        
        # 对于不存在的路径，逐级解析
        try:
            resolved = joined.resolve()
        except (OSError, ValueError):
            # 如果 resolve() 失败，使用纯路径检查
            resolved = Path(PurePath(base).joinpath(*paths))
        
        # 确保解析后的路径在 base 下
        try:
            resolved.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Path traversal detected: {joined} is outside {base}"
            )
        
        return resolved

    @classmethod
    def is_safe_path(cls, base: Path, target: Path) -> bool:
        """
        检查 target 是否安全地位于 base 下
        
        Args:
            base: 基础目录
            target: 目标路径
        
        Returns:
            是否安全
        """
        try:
            target.resolve().relative_to(base.resolve())
            return True
        except ValueError:
            return False


class UrlValidator:
    """
    URL 安全验证器（带 SSRF 防护）
    
    验证 URL 是否安全，防止 SSRF 攻击。
    
    Example:
        >>> validator = UrlValidator(
        ...     allowed_schemes=["https"],
        ...     allowed_hosts=["api.example.com"]
        ... )
        >>> validator.validate("https://api.example.com/data")  # True
        >>> validator.validate("http://localhost/admin")  # False
    """
    
    # 私有/保留 IP 段
    PRIVATE_NETWORKS: tuple = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),      # localhost
        ipaddress.ip_network("169.254.0.0/16"),   # link-local
        ipaddress.ip_network("::1/128"),          # IPv6 localhost
        ipaddress.ip_network("fc00::/7"),         # IPv6 私有
        ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
    )
    
    # 危险端口
    BLOCKED_PORTS: FrozenSet[int] = frozenset({
        22, 23, 25, 445, 3389, 6379, 27017
    })

    def __init__(
        self, 
        allowed_schemes: Iterable[str], 
        allowed_hosts: Iterable[str],
        block_private_ips: bool = True,
        resolve_dns: bool = True
    ):
        """
        初始化验证器
        
        Args:
            allowed_schemes: 允许的协议（如 ["https"]）
            allowed_hosts: 允许的域名（如 ["yande.re"]）
            block_private_ips: 是否阻止私有 IP
            resolve_dns: 是否解析 DNS 检查真实 IP
        """
        self.allowed_schemes: FrozenSet[str] = frozenset(allowed_schemes)
        self.allowed_hosts: FrozenSet[str] = frozenset(allowed_hosts)
        self.block_private_ips = block_private_ips
        self.resolve_dns = resolve_dns

    def validate(self, url: str) -> bool:
        """
        验证 URL 是否安全
        
        Args:
            url: 要验证的URL
        
        Returns:
            是否安全
        """
        if not url or not isinstance(url, str):
            return False
        
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        
        # 1. 协议检查
        if parsed.scheme not in self.allowed_schemes:
            logger.debug("Blocked scheme: %s", parsed.scheme)
            return False
        
        # 2. 端口检查
        port = parsed.port
        if port and port in self.BLOCKED_PORTS:
            logger.debug("Blocked port: %d", port)
            return False
        
        # 3. 主机名检查
        host = parsed.hostname or ""
        if not self._is_host_allowed(host):
            logger.debug("Host not in whitelist: %s", host)
            return False
        
        # 4. 私有 IP 检查
        if self.block_private_ips:
            if not self._check_not_private(host):
                logger.warning("Blocked private IP access: %s", host)
                return False
        
        return True

    def _is_host_allowed(self, host: str) -> bool:
        """检查域名是否在白名单"""
        if not host:
            return False
        
        host = host.lower()
        return any(
            host == h or host.endswith("." + h) 
            for h in self.allowed_hosts
        )

    def _check_not_private(self, host: str) -> bool:
        """检查不是私有 IP（包括 DNS 解析后的 IP）"""
        # 直接 IP 地址检查
        if self._is_private_ip(host):
            return False
        
        # DNS 解析检查（可选）
        if self.resolve_dns:
            try:
                resolved_ips = socket.getaddrinfo(
                    host, None, 
                    socket.AF_UNSPEC, 
                    socket.SOCK_STREAM,
                    0,
                    socket.AI_NUMERICHOST  # 避免额外DNS查询
                )
            except socket.gaierror:
                # 不是IP地址，尝试解析
                try:
                    resolved_ips = socket.getaddrinfo(
                        host, None, 
                        socket.AF_UNSPEC, 
                        socket.SOCK_STREAM
                    )
                except socket.gaierror:
                    # DNS 解析失败，保守起见允许
                    logger.debug("DNS resolution skipped for: %s", host)
                    return True
            
            for family, _, _, _, sockaddr in resolved_ips:
                ip = sockaddr[0]
                if self._is_private_ip(ip):
                    logger.warning(
                        "DNS resolved to private IP: %s -> %s", 
                        host, ip
                    )
                    return False
        
        return True

    def _is_private_ip(self, ip_str: str) -> bool:
        """检查是否为私有 IP"""
        try:
            ip = ipaddress.ip_address(ip_str)
            return any(ip in network for network in self.PRIVATE_NETWORKS)
        except ValueError:
            return False


class CachedUrlValidator(UrlValidator):
    """
    带 DNS 缓存的 URL 验证器
    
    注意：缓存可能导致安全问题，仅在性能敏感场景使用。
    """
    
    def __init__(
        self, 
        *args, 
        cache_size: int = 100, 
        cache_ttl: int = 300,
        **kwargs
    ):
        """
        初始化带缓存的验证器
        
        Args:
            cache_size: 缓存大小
            cache_ttl: 缓存过期时间（秒）
            *args, **kwargs: 传递给父类
        """
        super().__init__(*args, **kwargs)
        self._cache_size = cache_size
        # 注意：lru_cache 不支持 TTL，生产环境应使用更完善的缓存
    
    @lru_cache(maxsize=100)
    def _cached_host_check(self, host: str) -> bool:
        """缓存主机检查结果"""
        return self._check_not_private(host)
    
    def validate(self, url: str) -> bool:
        """验证（使用缓存）"""
        if not url or not isinstance(url, str):
            return False
        
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        
        if parsed.scheme not in self.allowed_schemes:
            return False
        
        host = parsed.hostname or ""
        if not self._is_host_allowed(host):
            return False
        
        if self.block_private_ips:
            return self._cached_host_check(host)
        
        return True


class UrlValidatorWrapper:
    """
    URL 验证器包装类
    
    提供简单的验证接口，使用延迟加载配置。
    """
    
    _validator: Optional[UrlValidator] = None
    
    def _get_validator(self) -> UrlValidator:
        """获取或创建验证器实例"""
        if self._validator is None:
            # 延迟导入避免循环依赖
            try:
                from config.app_config import CONFIG
                self._validator = UrlValidator(
                    allowed_schemes=getattr(CONFIG, 'allowed_schemes', ['https']),
                    allowed_hosts=getattr(CONFIG, 'allowed_hosts', [])
                )
            except ImportError:
                # 配置模块不可用时使用默认值
                logger.warning("Config not available, using default validator")
                self._validator = UrlValidator(
                    allowed_schemes=['https', 'http'],
                    allowed_hosts=['yande.re', 'files.yande.re']
                )
        return self._validator
    
    def validate(self, url: str) -> bool:
        """
        验证 URL 安全性
        
        Args:
            url: 要验证的URL
        
        Returns:
            是否安全
        """
        return self._get_validator().validate(url)


# 全局验证器实例
url_validator = UrlValidatorWrapper()