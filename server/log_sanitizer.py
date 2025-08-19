"""
日志信息脱敏模块
用于保护敏感信息不被记录到日志中
"""

import re
import logging
from typing import Dict, Pattern, Callable, Match, Optional


class LogSanitizer:
    """日志脱敏器"""
    
    def __init__(self):
        self.patterns: Dict[str, Pattern] = {}
        self.replacers: Dict[str, Callable[[Match], str]] = {}
        self._setup_default_patterns()
    
    def _setup_default_patterns(self):
        """设置默认的脱敏模式"""
        
        # API密钥脱敏 (保留前4位和后2位)
        self.patterns['api_key'] = re.compile(
            r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9+/]{8,})',
            re.IGNORECASE
        )
        self.replacers['api_key'] = lambda match: (
            match.group(1) + self._mask_secret(match.group(2), keep_start=4, keep_end=2)
        )
        
        # IP地址脱敏 (保留网段，脱敏主机部分)
        self.patterns['ip_address'] = re.compile(
            r'\b(\d{1,3}\.\d{1,3}\.)(\d{1,3}\.\d{1,3})\b'
        )
        self.replacers['ip_address'] = lambda match: (
            match.group(1) + "***." + match.group(2).split('.')[-1]
        )
        
        # ZeroTier网络ID脱敏 (16位十六进制)
        self.patterns['zerotier_network'] = re.compile(
            r'\b([a-fA-F0-9]{16})\b'
        )
        self.replacers['zerotier_network'] = lambda match: (
            self._mask_secret(match.group(1), keep_start=4, keep_end=4)
        )
        
        # MAC地址脱敏
        self.patterns['mac_address'] = re.compile(
            r'\b([a-fA-F0-9]{2}[:-]){5}([a-fA-F0-9]{2})\b'
        )
        self.replacers['mac_address'] = lambda match: (
            "XX:XX:XX:XX:" + match.group(0)[-5:]
        )
        
        # 用户名脱敏
        self.patterns['username'] = re.compile(
            r'(?i)(user[_-]?name["\']?\s*[:=]\s*["\']?)([^"\'\s,}]{3,})',
            re.IGNORECASE
        )
        self.replacers['username'] = lambda match: (
            match.group(1) + self._mask_secret(match.group(2), keep_start=2, keep_end=1)
        )
        
        # 密码完全脱敏
        self.patterns['password'] = re.compile(
            r'(?i)(password["\']?\s*[:=]\s*["\']?)([^"\'\s,}]+)',
            re.IGNORECASE
        )
        self.replacers['password'] = lambda match: (
            match.group(1) + "***HIDDEN***"
        )
    
    def _mask_secret(self, secret: str, keep_start: int = 4, keep_end: int = 2) -> str:
        """脱敏字符串，保留开头和结尾部分字符"""
        if len(secret) <= keep_start + keep_end:
            return "*" * len(secret)
        
        start = secret[:keep_start]
        end = secret[-keep_end:] if keep_end > 0 else ""
        middle = "*" * (len(secret) - keep_start - keep_end)
        
        return start + middle + end
    
    def sanitize(self, message: str) -> str:
        """脱敏日志信息"""
        sanitized = message
        
        for pattern_name, pattern in self.patterns.items():
            replacer = self.replacers[pattern_name]
            
            def replace_func(match: Match) -> str:
                try:
                    return replacer(match)
                except Exception:
                    # 如果脱敏失败，返回完全脱敏的结果
                    return "*" * len(match.group(0))
            
            sanitized = pattern.sub(replace_func, sanitized)
        
        return sanitized
    
    def add_pattern(self, name: str, pattern: Pattern, replacer: Callable[[Match], str]):
        """添加自定义脱敏模式"""
        self.patterns[name] = pattern
        self.replacers[name] = replacer


class SanitizedFormatter(logging.Formatter):
    """脱敏日志格式化器"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sanitizer = LogSanitizer()
    
    def format(self, record: logging.LogRecord) -> str:
        # 先进行标准格式化
        formatted = super().format(record)
        # 然后进行脱敏处理
        return self.sanitizer.sanitize(formatted)


def setup_sanitized_logging(log_level: str = "INFO", log_file: Optional[str] = None):
    """设置脱敏日志配置"""
    
    # 创建脱敏格式化器
    formatter = SanitizedFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 添加文件处理器（如果指定）
    if log_file:
        try:
            import os
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            logging.warning(f"无法设置文件日志: {e}")


# 全局脱敏器实例
_global_sanitizer = LogSanitizer()


def sanitize_log_message(message: str) -> str:
    """快速脱敏函数"""
    return _global_sanitizer.sanitize(message)
