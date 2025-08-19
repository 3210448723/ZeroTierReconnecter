import json
import logging
import hashlib
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class ClientConfig:
    """客户端配置"""
    # 服务端配置
    server_base: str = "http://127.0.0.1:5418"
    api_key: str = ""  # 服务端API密钥
    
    # 目标主机配置
    target_ip: str = ""  # 远程 ZeroTier 组网地址
    
    # ZeroTier 配置
    zerotier_service_names: Optional[List[str]] = None  # ZeroTier 服务名称列表
    zerotier_bin_paths: Optional[List[str]] = None      # ZeroTier 程序路径列表
    zerotier_gui_paths: Optional[List[str]] = None      # ZeroTier GUI 程序路径列表
    zerotier_adapter_keywords: Optional[List[str]] = None  # ZeroTier 网络适配器关键词
    
    # 自动化配置
    auto_heal_enabled: bool = True
    ping_interval_sec: int = 20        # ping 间隔（秒）
    restart_cooldown_sec: int = 30     # 重启冷却时间（秒）
    ping_timeout_sec: int = 3          # ping 超时时间（秒）
    
    # 日志配置
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    log_file: str = ""       # 空字符串表示仅控制台输出
    
    # 私有属性：用于检测配置变更
    _config_hash: str = ""
    
    # 类级别的路径验证缓存（减少重复文件系统调用）
    _path_cache: Optional[dict] = None
    _cache_timestamp: float = 0.0
    _cache_ttl: float = 30.0  # 缓存30秒
    
    def __post_init__(self):
        """初始化默认值"""
        if self.zerotier_service_names is None:
            self.zerotier_service_names = [
                "ZeroTier One",
                "ZeroTierOneService",
                "zerotier-one"
            ]
        
        if self.zerotier_bin_paths is None:
            self.zerotier_bin_paths = [
                # Windows (更新到实际路径)
                r"C:\ProgramData\ZeroTier\One\zerotier-one_x64.exe",
                r"C:\Program Files\ZeroTier\One\zerotier-one_x64.exe",
                r"C:\Program Files (x86)\ZeroTier\One\zerotier-one_x86.exe",
                r"C:\ProgramData\ZeroTier\One\zerotier-one.exe",
                # Linux/macOS
                "/usr/sbin/zerotier-one",
                "/usr/local/sbin/zerotier-one",
                "/opt/zerotier-one/zerotier-one",
            ]
        
        if self.zerotier_gui_paths is None:
            self.zerotier_gui_paths = [
                # Windows GUI (更新到实际路径)
                r"C:\Program Files (x86)\ZeroTier\One\zerotier_desktop_ui.exe",
                r"C:\Program Files\ZeroTier\One\zerotier_desktop_ui.exe",
                r"C:\Program Files\ZeroTier\One\ZeroTier One.exe",
                r"C:\Program Files (x86)\ZeroTier\One\ZeroTier One.exe",
            ]
        
        if self.zerotier_adapter_keywords is None:
            self.zerotier_adapter_keywords = [
                "ZeroTier One",
                "ZeroTier",
                "zt"
            ]

    def auto_discover_zerotier_paths(self) -> bool:
        """自动发现并更新 ZeroTier 路径"""
        try:
            # 延迟导入避免循环导入
            from .platform_utils import discover_zerotier_paths
            
            discovered = discover_zerotier_paths()
            updated = False
            
            # 更新服务路径（如果发现了新路径）
            if discovered['service_bin']:
                new_paths = discovered['service_bin'] + (self.zerotier_bin_paths or [])
                # 去重但保持发现的路径优先
                unique_paths = []
                seen = set()
                for path in new_paths:
                    if path not in seen:
                        unique_paths.append(path)
                        seen.add(path)
                
                if unique_paths != self.zerotier_bin_paths:
                    self.zerotier_bin_paths = unique_paths
                    updated = True
            
            # 更新GUI路径
            if discovered['gui_bin']:
                new_gui_paths = discovered['gui_bin'] + (self.zerotier_gui_paths or [])
                unique_gui_paths = []
                seen_gui = set()
                for path in new_gui_paths:
                    if path not in seen_gui:
                        unique_gui_paths.append(path)
                        seen_gui.add(path)
                
                if unique_gui_paths != self.zerotier_gui_paths:
                    self.zerotier_gui_paths = unique_gui_paths
                    updated = True
            
            # 更新服务名称
            if discovered['service_names']:
                new_service_names = discovered['service_names'] + (self.zerotier_service_names or [])
                unique_service_names = []
                seen_services = set()
                for name in new_service_names:
                    if name not in seen_services:
                        unique_service_names.append(name)
                        seen_services.add(name)
                
                if unique_service_names != self.zerotier_service_names:
                    self.zerotier_service_names = unique_service_names
                    updated = True
            
            if updated:
                logging.info("已自动更新 ZeroTier 路径配置")
                return self.save()
            else:
                logging.debug("自动发现未找到新的 ZeroTier 路径")
                return True
                
        except Exception as e:
            logging.warning(f"自动发现 ZeroTier 路径失败: {e}")
            return False

    @staticmethod
    def get_config_path() -> Path:
        """获取配置文件路径"""
        return Path.home() / ".zerotier_solver_client.json"

    @classmethod
    def load(cls) -> "ClientConfig":
        """从配置文件加载"""
        config_path = cls.get_config_path()
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    data = json.loads(content)
                    instance = cls(**data)
                    # 保存配置文件的哈希值，用于检测变更
                    instance._config_hash = hashlib.md5(content.encode()).hexdigest()
                    return instance
            except Exception as e:
                logging.warning(f"加载客户端配置失败: {e}，使用默认配置")
        
        instance = cls()
        instance._config_hash = ""
        return instance

    def save(self) -> bool:
        """保存配置到文件（仅在配置变更时）"""
        try:
            config_path = self.get_config_path()
            
            # 创建配置数据的副本，排除私有属性
            config_dict = asdict(self)
            config_dict.pop('_config_hash', None)
            
            # 生成新的配置内容和哈希
            new_content = json.dumps(config_dict, indent=2, ensure_ascii=False)
            new_hash = hashlib.md5(new_content.encode()).hexdigest()
            
            # 仅在配置变更时写入文件
            if new_hash != self._config_hash:
                with open(config_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                self._config_hash = new_hash
                logging.debug("配置已保存到文件")
            else:
                logging.debug("配置无变更，跳过保存")
            
            return True
        except Exception as e:
            logging.error(f"保存客户端配置失败: {e}")
            return False

    def validate(self) -> List[str]:
        """验证配置，返回错误信息列表（增强版）"""
        errors = []
        warnings = []
        
        # 验证服务端地址
        if not self.server_base:
            errors.append("服务端地址不能为空")
        elif not self.server_base.startswith(('http://', 'https://')):
            errors.append(f"服务端地址必须以 http:// 或 https:// 开头，当前: {self.server_base}")
        else:
            # 验证URL格式
            try:
                from urllib.parse import urlparse
                parsed = urlparse(self.server_base)
                if not parsed.netloc:
                    errors.append(f"无效的服务端地址格式: {self.server_base}")
                elif parsed.scheme == 'http' and parsed.port == 443:
                    warnings.append("HTTP协议使用443端口可能有问题")
                elif parsed.scheme == 'https' and parsed.port == 80:
                    warnings.append("HTTPS协议使用80端口可能有问题")
            except Exception as e:
                errors.append(f"服务端地址解析失败: {e}")
        
        # 验证API认证配置
        if self.api_key:
            if len(self.api_key) < 16:
                errors.append(f"API密钥长度至少16个字符，当前: {len(self.api_key)}字符")
            elif len(self.api_key) < 32:
                warnings.append(f"API密钥长度较短 ({len(self.api_key)}字符)，建议至少32字符")
        
        # 验证时间配置
        if self.ping_interval_sec < 5:
            errors.append(f"ping 间隔不能小于 5 秒，当前: {self.ping_interval_sec}")
        elif self.ping_interval_sec < 10:
            warnings.append(f"ping 间隔较短 ({self.ping_interval_sec}s)，可能增加服务端负载")
        
        if self.ping_timeout_sec < 1 or self.ping_timeout_sec > 30:
            errors.append(f"ping 超时时间应在 1-30 秒之间，当前: {self.ping_timeout_sec}")
        elif self.ping_timeout_sec >= self.ping_interval_sec:
            warnings.append(f"ping 超时时间 ({self.ping_timeout_sec}s) 不应大于等于 ping 间隔 ({self.ping_interval_sec}s)")
        
        if self.restart_cooldown_sec < 10:
            errors.append(f"重启冷却时间不能小于 10 秒，当前: {self.restart_cooldown_sec}")
        elif self.restart_cooldown_sec < 30:
            warnings.append(f"重启冷却时间较短 ({self.restart_cooldown_sec}s)，可能导致频繁重启")
        
        # 验证日志配置
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level not in valid_levels:
            errors.append(f"日志级别必须是: {', '.join(valid_levels)}，当前: {self.log_level}")
        
        # 验证ZeroTier配置
        if not self.zerotier_service_names:
            errors.append("ZeroTier服务名称列表不能为空")
        
        if not self.zerotier_bin_paths:
            errors.append("ZeroTier可执行文件路径列表不能为空")
        
        if not self.zerotier_adapter_keywords:
            errors.append("ZeroTier网络适配器关键词列表不能为空")
        
        # 验证路径有效性（使用缓存减少IO）
        import os
        import time
        
        current_time = time.time()
        # 检查缓存是否有效
        if (self._path_cache is None or 
            current_time - self._cache_timestamp > self._cache_ttl):
            # 重新验证并更新缓存
            self._path_cache = {}
            for path in (self.zerotier_bin_paths or []):
                try:
                    self._path_cache[path] = os.path.exists(path)
                except (OSError, ValueError):
                    self._path_cache[path] = False
            self._cache_timestamp = current_time
        
        # 使用缓存结果
        valid_bin_paths = [path for path, exists in self._path_cache.items() if exists]
        
        if not valid_bin_paths:
            warnings.append("未找到有效的ZeroTier可执行文件路径，可能需要手动配置")
        
        # 验证配置文件路径
        try:
            config_path = self.get_config_path()
            config_dir = config_path.parent
            if not config_dir.exists():
                warnings.append(f"配置文件目录不存在，将自动创建: {config_dir}")
            elif not os.access(config_dir, os.W_OK):
                errors.append(f"配置文件目录不可写: {config_dir}")
        except Exception as e:
            errors.append(f"配置文件路径验证失败: {e}")
        
        # 打印警告信息
        if warnings:
            import logging
            logging.warning("客户端配置验证警告:")
            for warning in warnings:
                logging.warning(f"  - {warning}")
        
        return errors
