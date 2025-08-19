"""
统一的日志配置工具模块
支持客户端和服务端的日志配置需求
"""

import logging
import os
from typing import Optional
from pathlib import Path


def setup_unified_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    use_sanitizer: bool = False,
    enable_rotation: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> bool:
    """
    统一的日志配置函数
    
    Args:
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 日志文件路径，None表示仅控制台输出
        use_sanitizer: 是否使用脱敏格式化器（服务端用）
        enable_rotation: 是否启用日志轮转
        max_bytes: 轮转文件最大字节数
        backup_count: 保留的备份文件数量
        
    Returns:
        bool: 配置是否成功
    """
    try:
        level = getattr(logging, log_level.upper(), logging.INFO)
        
        # 选择格式化器
        if use_sanitizer:
            try:
                from ..server.log_sanitizer import SanitizedFormatter
                formatter = SanitizedFormatter(
                    fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
            except ImportError:
                # 回退到普通格式化器
                formatter = logging.Formatter(
                    fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
        else:
            formatter = logging.Formatter(
                fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        # 清理现有处理器
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        root_logger.setLevel(level)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # 文件处理器（如果配置了）
        if log_file:
            try:
                # 确保日志文件目录存在
                log_path = Path(log_file)
                log_dir = log_path.parent
                if log_dir != Path('.'):  # 避免空字符串导致的问题
                    log_dir.mkdir(parents=True, exist_ok=True)
                
                if enable_rotation:
                    # 使用轮转文件处理器
                    from logging.handlers import RotatingFileHandler
                    file_handler = RotatingFileHandler(
                        log_file, 
                        maxBytes=max_bytes,
                        backupCount=backup_count,
                        encoding='utf-8'
                    )
                    file_handler.setFormatter(formatter)
                    root_logger.addHandler(file_handler)
                    logging.info(f"日志文件已配置: {log_file} (轮转: {max_bytes//1024//1024}MB × {backup_count}个文件)")
                else:
                    # 普通文件处理器
                    file_handler = logging.FileHandler(log_file, encoding='utf-8')
                    file_handler.setFormatter(formatter)
                    root_logger.addHandler(file_handler)
                    logging.info(f"日志文件已配置: {log_file}")
                    
            except Exception as e:
                logging.warning(f"无法创建日志文件 {log_file}: {e}")
                return False
        
        logging.info(f"日志系统已配置: 级别={log_level}")
        return True
        
    except Exception as e:
        print(f"日志系统配置失败: {e}")  # 使用print因为logging可能不可用
        return False


def get_log_config_from_client_config(config) -> dict:
    """从客户端配置提取日志配置参数"""
    return {
        'log_level': getattr(config, 'log_level', 'INFO'),
        'log_file': getattr(config, 'log_file', ''),
        'use_sanitizer': False,  # 客户端不需要脱敏
        'enable_rotation': True
    }


def get_log_config_from_server_config(config) -> dict:
    """从服务端配置提取日志配置参数"""
    return {
        'log_level': getattr(config, 'log_level', 'INFO'),
        'log_file': getattr(config, 'log_file', ''),
        'use_sanitizer': True,   # 服务端需要脱敏
        'enable_rotation': True
    }
