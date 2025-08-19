import threading
import time
from typing import Dict, Any, Optional, Set
import logging


class ClientInfo:
    """客户端信息数据类（内存优化）"""
    __slots__ = ('last_seen', 'last_ping_ok', 'last_ping_at')
    
    def __init__(self, last_seen: float = 0.0, last_ping_ok: bool = False, last_ping_at: float = 0.0):
        self.last_seen = last_seen
        self.last_ping_ok = last_ping_ok
        self.last_ping_at = last_ping_at
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_seen": self.last_seen,
            "last_ping_ok": self.last_ping_ok,
            "last_ping_at": self.last_ping_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClientInfo":
        """从字典创建客户端信息"""
        return cls(
            last_seen=float(data.get("last_seen", 0.0)),
            last_ping_ok=bool(data.get("last_ping_ok", False)),
            last_ping_at=float(data.get("last_ping_at", 0.0))
        )


class ThreadSafeClientManager:
    """线程安全的客户端管理器"""
    
    def __init__(self):
        self._clients: Dict[str, ClientInfo] = {}
        self._lock = threading.RLock()  # 使用可重入锁
        self._logger = logging.getLogger(__name__)
        self._data_dirty = False  # 数据脏标志
        self._last_data_hash = ""  # 上次保存的数据哈希
    
    def add_or_update_client(self, ip: str, **kwargs) -> bool:
        """添加或更新客户端信息"""
        try:
            with self._lock:
                current_time = time.time()
                
                if ip not in self._clients:
                    # 新客户端
                    self._clients[ip] = ClientInfo(
                        last_seen=current_time,
                        last_ping_ok=False,
                        last_ping_at=0.0
                    )
                    self._logger.debug(f"添加新客户端: {ip}")
                    self._data_dirty = True  # 标记数据已变更
                
                # 更新指定属性
                client = self._clients[ip]
                data_changed = False
                for key, value in kwargs.items():
                    if hasattr(client, key):
                        old_value = getattr(client, key)
                        if old_value != value:
                            setattr(client, key, value)
                            data_changed = True
                
                if data_changed:
                    self._data_dirty = True  # 标记数据已变更
                
                return True
        except Exception as e:
            self._logger.error(f"更新客户端 {ip} 失败: {e}")
            return False
    
    def update_ping_result(self, ip: str, success: bool) -> bool:
        """更新客户端ping结果"""
        current_time = time.time()
        return self.add_or_update_client(
            ip, 
            last_ping_ok=success, 
            last_ping_at=current_time
        )
    
    def get_clients_to_ping(self, ping_interval: int) -> Set[str]:
        """获取需要ping的客户端列表"""
        current_time = time.time()
        with self._lock:
            return {
                ip for ip, info in self._clients.items()
                if current_time - info.last_ping_at >= ping_interval
            }
    
    def get_all_clients(self) -> Dict[str, Dict[str, Any]]:
        """获取所有客户端信息的副本"""
        with self._lock:
            return {ip: info.to_dict() for ip, info in self._clients.items()}
    
    def get_active_clients(self, offline_threshold: int) -> Dict[str, Dict[str, Any]]:
        """获取活跃客户端列表"""
        current_time = time.time()
        with self._lock:
            return {
                ip: info.to_dict() 
                for ip, info in self._clients.items()
                if current_time - info.last_seen <= offline_threshold
            }
    
    def get_stats(self, offline_threshold: int) -> Dict[str, int]:
        """获取客户端统计信息"""
        current_time = time.time()
        stats = {
            "total": 0,
            "active": 0,
            "online": 0,
            "offline": 0,
            "never_pinged": 0
        }
        
        with self._lock:
            stats["total"] = len(self._clients)
            
            for info in self._clients.values():
                # 活跃客户端（最近上报过）
                if current_time - info.last_seen <= offline_threshold:
                    stats["active"] += 1
                
                # Ping状态统计（互斥分类）
                if info.last_ping_at == 0:
                    stats["never_pinged"] += 1
                elif info.last_ping_ok:
                    stats["online"] += 1
                else:
                    stats["offline"] += 1
        
        return stats
    
    def remove_client(self, ip: str) -> bool:
        """移除客户端"""
        try:
            with self._lock:
                removed = self._clients.pop(ip, None)
                if removed:
                    self._logger.debug(f"移除客户端: {ip}")
                    self._data_dirty = True  # 标记数据已变更
                    return True
                return False
        except Exception as e:
            self._logger.error(f"移除客户端 {ip} 失败: {e}")
            return False
    
    def cleanup_offline_clients(self, offline_threshold: int, max_offline_time: Optional[int] = None) -> int:
        """
        清理长时间离线的客户端。
        - 如果提供 max_offline_time，则使用该阈值；
        - 否则使用 offline_threshold。
        """
        current_time = time.time()
        removed_count = 0
        
        threshold = max_offline_time if (isinstance(max_offline_time, (int, float)) and max_offline_time > 0) else offline_threshold
        
        try:
            with self._lock:
                offline_clients = [
                    ip for ip, info in self._clients.items()
                    if current_time - info.last_seen > threshold
                ]
                
                for ip in offline_clients:
                    if self._clients.pop(ip, None):
                        removed_count += 1
                        self._logger.info(f"清理长时间离线客户端: {ip}")
                
                if removed_count > 0:
                    self._data_dirty = True  # 标记数据已变更
        
        except Exception as e:
            self._logger.error(f"清理离线客户端失败: {e}")
        
        return removed_count
    
    def load_from_dict(self, data: Dict[str, Any]) -> int:
        """从字典加载客户端数据"""
        loaded_count = 0
        
        try:
            with self._lock:
                self._clients.clear()
                
                for ip, client_data in data.items():
                    try:
                        if isinstance(client_data, dict):
                            self._clients[ip] = ClientInfo.from_dict(client_data)
                            loaded_count += 1
                        else:
                            # 兼容旧格式 (ip: timestamp)
                            self._clients[ip] = ClientInfo(
                                last_seen=float(client_data),
                                last_ping_ok=False,
                                last_ping_at=0.0
                            )
                            loaded_count += 1
                    except Exception as e:
                        self._logger.warning(f"加载客户端 {ip} 数据失败: {e}")
                        continue
                
                # 重置脏标志和哈希
                self._data_dirty = False
                import json
                self._last_data_hash = self._calculate_data_hash()
        
        except Exception as e:
            self._logger.error(f"加载客户端数据失败: {e}")
        
        self._logger.info(f"成功加载 {loaded_count} 个客户端数据")
        return loaded_count
    
    def to_dict(self) -> Dict[str, Dict[str, Any]]:
        """转换为字典格式（用于保存）"""
        return self.get_all_clients()
    
    def size(self) -> int:
        """获取客户端数量"""
        with self._lock:
            return len(self._clients)
    
    def is_data_dirty(self) -> bool:
        """检查数据是否有变更"""
        with self._lock:
            return self._data_dirty
    
    def mark_data_clean(self):
        """标记数据为干净状态"""
        with self._lock:
            self._data_dirty = False
            self._last_data_hash = self._calculate_data_hash()
    
    def mark_data_dirty(self):
        """显式标记数据为脏状态（用于错误恢复）"""
        with self._lock:
            self._data_dirty = True
    
    def get_data_snapshot_and_mark_clean(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """原子性获取数据快照并标记为干净 - 解决竞态条件"""
        with self._lock:
            if not self._data_dirty:
                return None  # 没有变更，返回None表示无需保存
            
            # 获取当前数据快照
            data_snapshot = {ip: info.to_dict() for ip, info in self._clients.items()}
            
            # 原子性地标记为干净
            self._data_dirty = False
            self._last_data_hash = self._calculate_data_hash()
            
            return data_snapshot
    
    def _calculate_data_hash(self) -> str:
        """计算当前数据的哈希值"""
        import hashlib
        import json
        try:
            data_dict = {ip: info.to_dict() for ip, info in self._clients.items()}
            data_str = json.dumps(data_dict, sort_keys=True, ensure_ascii=False)
            return hashlib.md5(data_str.encode()).hexdigest()
        except Exception:
            return ""
