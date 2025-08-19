"""
性能监控指标模块
提供 Prometheus 格式的指标输出
"""

import time
import psutil
import threading
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor


class MetricsCollector:
    """指标收集器"""
    __slots__ = (
        '_start_time',
        '_request_count',
        '_request_duration_sum',
        '_lock',
        '_sys_cache',
        '_sys_cache_ts',
        '_sys_ttl',
        '_ping_submitted',
        '_ping_completed',
        '_ping_failed',
        '_ping_duration_sum',
    )
    
    def __init__(self):
        self._start_time = time.time()
        self._request_count = 0
        self._request_duration_sum = 0.0
        self._lock = threading.Lock()
        self._sys_cache: Dict[str, float] = {}
        self._sys_cache_ts: float = 0.0
        self._sys_ttl: float = 2.0  # 系统指标缓存 TTL（秒）
        
        # Ping任务监控指标
        self._ping_submitted = 0
        self._ping_completed = 0
        self._ping_failed = 0
        self._ping_duration_sum = 0.0
    
    def get_uptime_seconds(self) -> float:
        """获取应用运行时间（秒）- 公开接口"""
        return time.time() - self._start_time
    
    def record_request(self, duration: float):
        """记录请求指标（线程安全）"""
        with self._lock:
            self._request_count += 1
            self._request_duration_sum += duration
    
    def record_ping_submitted(self, count: int = 1):
        """记录提交的ping任务数量"""
        with self._lock:
            self._ping_submitted += count
    
    def record_ping_completed(self, duration: float, success: bool):
        """记录完成的ping任务"""
        with self._lock:
            self._ping_completed += 1
            self._ping_duration_sum += duration
            if not success:
                self._ping_failed += 1
    
    def get_ping_metrics(self) -> Dict[str, Any]:
        """获取ping任务指标"""
        with self._lock:
            success_rate = 0.0
            if self._ping_completed > 0:
                success_rate = (self._ping_completed - self._ping_failed) / self._ping_completed
            
            avg_duration = 0.0
            if self._ping_completed > 0:
                avg_duration = self._ping_duration_sum / self._ping_completed
            
            return {
                "ping_submitted_total": self._ping_submitted,
                "ping_completed_total": self._ping_completed,
                "ping_failed_total": self._ping_failed,
                "ping_success_rate": success_rate,
                "ping_avg_duration_seconds": avg_duration,
                "ping_pending": max(0, self._ping_submitted - self._ping_completed)
            }
    
    def get_system_metrics(self) -> Dict[str, float]:
        """获取系统指标（带缓存，避免阻塞）"""
        now = time.time()
        if self._sys_cache and (now - self._sys_cache_ts) < self._sys_ttl:
            return self._sys_cache
        
        try:
            # 非阻塞 CPU 采样；首次可能返回 0，需要调用两次才能稳定，但有缓存即可接受
            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            import os as _os
            disk = psutil.disk_usage(_os.path.abspath(_os.sep))
            
            data = {
                "system_cpu_percent": float(cpu),
                "system_memory_percent": float(memory.percent),
                "system_memory_used_bytes": float(memory.used),
                "system_memory_total_bytes": float(memory.total),
                "system_disk_percent": float(disk.percent),
                "system_disk_used_bytes": float(disk.used),
                "system_disk_total_bytes": float(disk.total),
            }
            self._sys_cache = data
            self._sys_cache_ts = now
            return data
        except Exception:
            return {}
    
    def get_executor_metrics(self, executor: Optional[ThreadPoolExecutor] = None) -> Dict[str, Any]:
        """安全地获取线程池指标"""
        executor_metrics = {}
        if executor:
            try:
                # 尝试获取公开属性或通过反射安全访问
                max_workers = getattr(executor, '_max_workers', None)
                threads = getattr(executor, '_threads', None)
                shutdown = getattr(executor, '_shutdown', None)
                
                if max_workers is not None:
                    executor_metrics["executor_max_workers"] = max_workers
                else:
                    executor_metrics["executor_max_workers"] = "unknown"
                
                if threads is not None:
                    executor_metrics["executor_active_threads"] = len(threads)
                else:
                    executor_metrics["executor_active_threads"] = "unknown"
                
                if shutdown is not None:
                    executor_metrics["executor_is_shutdown"] = shutdown
                else:
                    executor_metrics["executor_is_shutdown"] = "unknown"
                    
            except Exception as e:
                # 属性访问失败时返回错误信息而不是崩溃
                executor_metrics = {
                    "executor_status": "error",
                    "executor_error": str(e)
                }
        else:
            executor_metrics = {"executor_status": "not_available"}
        
        return executor_metrics
    
    def get_app_metrics(self, client_manager, executor: Optional[ThreadPoolExecutor] = None, offline_threshold_sec: int = 300) -> Dict[str, Any]:
        """获取应用指标"""
        uptime = self.get_uptime_seconds()  # 使用公开接口
        
        # 客户端统计（使用可配置阈值）
        stats = client_manager.get_stats(offline_threshold_sec)
        
        # 线程池状态（使用安全方法）
        executor_metrics = self.get_executor_metrics(executor)
        
        with self._lock:
            req_total = self._request_count
            req_sum = self._request_duration_sum
        
        return {
            "app_uptime_seconds": uptime,
            "app_request_total": req_total,
            "app_request_duration_seconds_sum": req_sum,
            "app_request_duration_seconds_avg": (req_sum / req_total if req_total > 0 else 0),
            "clients_total": stats["total"],
            "clients_active": stats["active"],
            "clients_online": stats["online"],
            "clients_offline": stats["offline"],
            "clients_never_pinged": stats["never_pinged"],
            **executor_metrics
        }
    
    def export_prometheus_format(self, client_manager, executor: Optional[ThreadPoolExecutor] = None, offline_threshold_sec: int = 300) -> str:
        """导出 Prometheus 格式的指标"""
        system_metrics = self.get_system_metrics()
        app_metrics = self.get_app_metrics(client_manager, executor, offline_threshold_sec)
        
        lines = [
            "# HELP zerotier_solver_info ZeroTier Solver 应用信息",
            "# TYPE zerotier_solver_info gauge",
            f"zerotier_solver_info{{version=\"1.0.0\"}} 1",
            "",
        ]
        
        # 系统指标
        for name, value in system_metrics.items():
            metric_name = f"zerotier_solver_{name}"
            lines.extend([
                f"# HELP {metric_name} 系统指标",
                f"# TYPE {metric_name} gauge",
                f"{metric_name} {value}",
                "",
            ])
        
        # 应用指标
        for name, value in app_metrics.items():
            metric_name = f"zerotier_solver_{name}"
            metric_type = "counter" if ("total" in name or "sum" in name) else "gauge"
            lines.extend([
                f"# HELP {metric_name} 应用指标", 
                f"# TYPE {metric_name} {metric_type}",
                f"{metric_name} {value}",
                "",
            ])
        
        return "\n".join(lines)


# 全局指标收集器实例
metrics = MetricsCollector()
