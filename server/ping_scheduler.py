import heapq
import random
import threading
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class PingTask:
    """Ping任务"""
    ip: str
    next_ping_time: float
    task_version: int  # 任务版本号，用于去重
    
    def __lt__(self, other):
        return self.next_ping_time < other.next_ping_time


class OptimizedPingScheduler:
    """优化的Ping调度器，使用优先队列替代O(n)遍历"""
    
    def __init__(self, ping_interval: int = 60):
        self._ping_queue: List[PingTask] = []  # 最小堆
        self._clients: Dict[str, Dict] = {}
        self._client_versions: Dict[str, int] = {}  # 每个客户端的当前任务版本号
        self._ping_result_count: int = 0  # 定期清理计数器
        self._lock = threading.RLock()
        self.ping_interval = ping_interval
    
    def add_client(self, ip: str, initial_data: Optional[Dict] = None):
        """添加或更新客户端到调度队列"""
        with self._lock:
            current_time = time.time()
            is_new_client = ip not in self._clients
            
            if is_new_client:
                # 新客户端：初始化所有数据
                self._clients[ip] = initial_data or {
                    "last_seen": current_time,
                    "last_ping_ok": False,
                    "last_ping_at": 0.0
                }
                self._client_versions[ip] = 1
                
                # 新客户端使用随机抖动快速首ping（1-10秒），避免雷群又能快速确认状态
                jitter = random.uniform(1.0, 10.0)
                next_ping = current_time + jitter
                heapq.heappush(self._ping_queue, PingTask(ip, next_ping, self._client_versions[ip]))
                
                import logging
                logging.debug(f"新客户端 {ip} 将在 {jitter:.1f}s 后首次ping")
                
            else:
                # 已存在客户端：更新数据并重新调度
                if initial_data:
                    # 保留关键字段，更新提供的数据
                    existing_data = self._clients[ip]
                    existing_data.update(initial_data)
                    existing_data["last_seen"] = current_time
                else:
                    # 仅更新 last_seen 时间戳
                    self._clients[ip]["last_seen"] = current_time
                
                # 增加版本号并重新调度（使用正常间隔）
                self._client_versions[ip] = self._client_versions.get(ip, 0) + 1
                next_ping = current_time + self.ping_interval
                heapq.heappush(self._ping_queue, PingTask(ip, next_ping, self._client_versions[ip]))
    
    def update_ping_result(self, ip: str, success: bool):
        """更新ping结果并重新调度"""
        with self._lock:
            if ip in self._clients:
                current_time = time.time()
                self._clients[ip]["last_ping_ok"] = success
                self._clients[ip]["last_ping_at"] = current_time
                
                # 增加版本号并重新调度下次ping
                self._client_versions[ip] = self._client_versions.get(ip, 0) + 1
                next_ping = current_time + self.ping_interval
                heapq.heappush(self._ping_queue, PingTask(ip, next_ping, self._client_versions[ip]))
                
                # 优化的清理策略：更频繁但轻量的清理
                client_count = len(self._clients)
                queue_size = len(self._ping_queue)
                
                # 降低清理阈值，防止队列过度增长
                if queue_size > max(5, client_count * 1.2):
                    self._cleanup_queue()
                # 绝对大小限制降低
                elif queue_size > 500:
                    self._cleanup_queue()
                # 更频繁的定期清理：每50个ping结果清理一次
                self._ping_result_count += 1
                if self._ping_result_count >= 50:
                    self._ping_result_count = 0
                    self._cleanup_queue()
    
    def get_ready_ips(self) -> List[str]:
        """获取准备好进行ping的IP列表（O(log n)复杂度）- 增强版本控制与去重"""
        ready_ips_set = set()  # 使用集合去重
        current_time = time.time()
        
        with self._lock:
            # 从堆顶取出所有到期的任务
            while self._ping_queue and self._ping_queue[0].next_ping_time <= current_time:
                task = heapq.heappop(self._ping_queue)
                
                # 验证任务版本号和客户端存在性
                if (task.ip in self._clients and 
                    task.ip in self._client_versions and
                    task.task_version == self._client_versions[task.ip]):
                    ready_ips_set.add(task.ip)
                # 旧版本任务直接丢弃，不需要处理
        
        return list(ready_ips_set)
    
    def remove_client(self, ip: str):
        """移除客户端（队列中的过期任务会在取出时过滤）"""
        with self._lock:
            self._clients.pop(ip, None)
            self._client_versions.pop(ip, None)  # 同时清理版本号
    
    def get_all_clients(self) -> Dict[str, Dict]:
        """获取所有客户端信息（新增公开接口）"""
        with self._lock:
            return self._clients.copy()
    
    def get_stats(self) -> Dict:
        """获取调度器统计信息"""
        with self._lock:
            return {
                "total_clients": len(self._clients),
                "queued_tasks": len(self._ping_queue),
                "active_versions": len(self._client_versions),
                "next_ping_in": self._ping_queue[0].next_ping_time - time.time() if self._ping_queue else 0
            }
    
    def next_ready_in(self) -> float:
        """返回距离下次应执行 ping 的秒数；<=0 表示已有就绪任务，空队列返回正值默认间隔。"""
        with self._lock:
            if not self._ping_queue:
                return float(self.ping_interval)
            delta = self._ping_queue[0].next_ping_time - time.time()
            return max(0.0, delta)  # 确保不返回负值

    def _cleanup_queue(self):
        """清理过期任务，防止队列无限增长（优化版本）"""
        current_time = time.time()
        active_clients = set(self._clients.keys())
        old_size = len(self._ping_queue)
        
        # 如果队列为空或很小，直接返回
        if old_size <= 5:
            return
        
        # 只有当清理收益可能较大时才执行完整清理
        estimated_cleanup_ratio = 0.3  # 预估清理比例
        if old_size < 20 and estimated_cleanup_ratio < 0.5:
            return
        
        # 重建队列，只保留有效且当前版本的任务
        new_queue = []
        stale_time_threshold = current_time - self.ping_interval * 1.5  # 减少阈值时间
        
        for task in self._ping_queue:
            # 更严格的清理条件
            if (task.ip in active_clients and 
                task.ip in self._client_versions and
                task.task_version == self._client_versions[task.ip] and
                task.next_ping_time > stale_time_threshold):
                new_queue.append(task)
        
        # 只有清理效果显著时才重建堆
        cleaned_count = old_size - len(new_queue)
        cleanup_ratio = cleaned_count / old_size if old_size > 0 else 0
        
        if cleanup_ratio > 0.1:  # 只有清理超过10%才值得重建
            heapq.heapify(new_queue)
            self._ping_queue = new_queue
            
            # 简化日志记录，减少字符串操作
            import logging
            if cleanup_ratio > 0.5:  # 只在大量清理时记录详细信息
                logging.debug(f"调度器清理: -{cleaned_count}/{old_size} ({cleanup_ratio:.1%})")
            
            # 内存泄漏警告阈值调整
            if len(new_queue) > len(active_clients) * 5:
                logging.warning(f"队列异常大: {len(new_queue)} 任务 vs {len(active_clients)} 客户端")
