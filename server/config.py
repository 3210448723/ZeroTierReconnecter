import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List


@dataclass
class ServerConfig:
    """服务端配置"""
    # 网络配置
    host: str = "0.0.0.0"
    port: int = 5418
    
    # Ping 配置
    ping_interval_sec: int = 60        # 每个 IP 的 ping 间隔（秒）
    ping_timeout_sec: int = 2          # ping 超时时间（秒）
    ping_stagger_sec: float = 0.5      # 不同 IP 之间的错开时间（秒）
    max_concurrent_pings: int = 5      # 最大并发 ping 数量
    
    # 数据保存配置
    data_file: str = "~/.zerotier_reconnecter_server_data.json"  # 改为与配置文件不同的默认路径
    save_interval_sec: int = 30        # 定期保存间隔（秒）
    
    # 日志配置
    log_level: str = "INFO"            # DEBUG, INFO, WARNING, ERROR
    log_file: str = "~/.zerotier_reconnecter_server.log"  # 默认日志文件路径
    
    # 客户端管理配置
    client_offline_threshold_sec: int = 300  # 客户端离线判断阈值（秒）
    
    # 安全配置
    api_key: str = ""                  # API访问密钥，空表示不启用认证
    enable_api_auth: bool = False      # 是否启用API认证

    @staticmethod
    def get_config_path() -> Path:
        """获取配置文件路径"""
        # 改为独立的默认配置路径，避免与 data_file 冲突
        return Path.home() / ".zerotier_reconnecter_server_config.json"

    @classmethod
    def load(cls) -> "ServerConfig":
        """从配置文件加载"""
        config_path = cls.get_config_path()
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return cls(**data)
            except Exception as e:
                logging.warning(f"加载服务端配置失败: {e}，使用默认配置")
        instance = cls()
        # 保存默认配置到文件
        instance.save()
        return instance

    def save(self) -> bool:
        """保存配置到文件"""
        try:
            config_path = self.get_config_path()
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logging.error(f"保存服务端配置失败: {e}")
            return False

    def validate(self) -> List[str]:
        """验证配置，返回错误信息列表（增强版）"""
        errors = []
        warnings = []
        
        # 验证网络配置
        if not (1 <= self.port <= 65535):
            errors.append(f"端口号必须在 1-65535 之间，当前: {self.port}")
        elif self.port < 1024 and self.port != 80 and self.port != 443:
            warnings.append(f"使用系统端口 {self.port} 可能需要管理员权限")
        
        # 验证主机地址
        if not self.host.strip():
            errors.append("主机地址不能为空")
        elif self.host not in ["0.0.0.0", "127.0.0.1", "localhost"]:
            try:
                import ipaddress
                ipaddress.ip_address(self.host)
            except ValueError:
                errors.append(f"无效的主机地址格式: {self.host}")
        
        # 验证时间间隔配置
        if self.ping_interval_sec < 5:
            errors.append(f"ping 间隔不能小于 5 秒，当前: {self.ping_interval_sec}")
        elif self.ping_interval_sec < 10:
            warnings.append(f"ping 间隔过短 ({self.ping_interval_sec}s)，可能影响性能")
        
        if self.ping_timeout_sec < 1 or self.ping_timeout_sec > 30:
            errors.append(f"ping 超时时间应在 1-30 秒之间，当前: {self.ping_timeout_sec}")
        elif self.ping_timeout_sec > self.ping_interval_sec * 0.8:
            warnings.append(f"ping 超时时间 ({self.ping_timeout_sec}s) 建议不要超过 ping 间隔的80% ({self.ping_interval_sec * 0.8:.1f}s)")
        
        if self.ping_stagger_sec < 0.1 or self.ping_stagger_sec > 10:
            errors.append(f"ping 错开时间应在 0.1-10 秒之间，当前: {self.ping_stagger_sec}")
        elif self.ping_stagger_sec > self.ping_interval_sec / 2:
            warnings.append(f"ping 错开时间过大，可能导致任务重叠")
        
        # 验证并发配置
        import psutil
        cpu_count = psutil.cpu_count() or 4
        
        if self.max_concurrent_pings < 1 or self.max_concurrent_pings > 100:
            errors.append(f"最大并发 ping 数量应在 1-100 之间，当前: {self.max_concurrent_pings}")
        elif self.max_concurrent_pings > cpu_count * 4:
            warnings.append(f"并发数量 ({self.max_concurrent_pings}) 超过CPU核心数的4倍 ({cpu_count * 4})，可能影响性能")
        
        # 验证存储配置
        if self.save_interval_sec < 5:
            errors.append(f"保存间隔不能小于 5 秒，当前: {self.save_interval_sec}")
        elif self.save_interval_sec < 30:
            warnings.append(f"保存间隔过短 ({self.save_interval_sec}s)，可能导致频繁IO操作")
        
        if self.client_offline_threshold_sec < 60:
            errors.append(f"客户端离线判断阈值不能小于 60 秒，当前: {self.client_offline_threshold_sec}")
        elif self.client_offline_threshold_sec < self.ping_interval_sec * 3:
            warnings.append(f"离线阈值 ({self.client_offline_threshold_sec}s) 过小，建议至少是ping间隔的3倍")
        
        # 验证日志配置
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level not in valid_levels:
            errors.append(f"日志级别必须是: {', '.join(valid_levels)}，当前: {self.log_level}")
        
        # 验证API认证配置
        if self.enable_api_auth:
            if not self.api_key:
                errors.append("启用API认证时必须设置api_key")
            elif len(self.api_key) < 16:
                errors.append(f"API密钥长度至少16个字符，当前: {len(self.api_key)}字符")
            elif len(self.api_key) < 32:
                warnings.append(f"API密钥长度较短 ({len(self.api_key)}字符)，建议至少32字符")
            
            # 检查密钥复杂度
            if self.api_key and len(set(self.api_key)) < 8:
                warnings.append("API密钥字符种类较少，建议包含数字、字母和特殊字符")
        
        # 验证文件路径
        try:
            cfg_path = self.get_config_path()
            data_path = Path(self.data_file).expanduser()
            
            # 检查路径冲突
            if data_path.resolve() == cfg_path.resolve():
                errors.append("data_file 不可与配置文件路径相同，请修改 data_file 或配置文件路径")
            
            # 检查目录是否存在和可写
            data_dir = data_path.parent
            if not data_dir.exists():
                warnings.append(f"数据文件目录不存在，将自动创建: {data_dir}")
                try:
                    data_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    errors.append(f"无法创建数据文件目录: {e}")
            elif not os.access(data_dir, os.W_OK):
                errors.append(f"数据文件目录不可写: {data_dir}")
                
        except Exception as e:
            errors.append(f"路径验证失败: {e}")
        
        # 打印警告信息
        if warnings:
            import logging
            logging.warning("配置验证警告:")
            for warning in warnings:
                logging.warning(f"  - {warning}")
        
        return errors

    def get_data_file_path(self) -> Path:
        """获取数据文件的绝对路径"""
        data_path = Path(self.data_file).expanduser()
        return data_path
