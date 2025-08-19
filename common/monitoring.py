#!/usr/bin/env python3
"""
性能监控和健康检查工具
提供系统性能监控、内存使用情况和组件健康状态检查
"""

import time
import threading
import psutil
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    timestamp: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    thread_count: int = 0
    active_connections: int = 0
    ping_success_rate: float = 0.0
    response_time_avg: float = 0.0
    errors_per_minute: int = 0


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, collection_interval: float = 60.0):
        self.collection_interval = collection_interval
        self._metrics_history: list[PerformanceMetrics] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._ping_stats = {"success": 0, "total": 0, "response_times": []}
        self._error_count = 0
        self._last_error_reset = time.time()
        
    def start(self):
        """启动性能监控"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
            
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="performance_monitor"
        )
        self._monitor_thread.start()
        logging.info("性能监控器已启动")
    
    def stop(self):
        """停止性能监控"""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logging.info("性能监控器已停止")
    
    def record_ping_result(self, success: bool, response_time: float):
        """记录ping结果"""
        with self._lock:
            self._ping_stats["total"] += 1
            if success:
                self._ping_stats["success"] += 1
                self._ping_stats["response_times"].append(response_time)
                
            # 保持响应时间历史记录在合理范围内
            if len(self._ping_stats["response_times"]) > 1000:
                self._ping_stats["response_times"] = self._ping_stats["response_times"][-500:]
    
    def record_error(self):
        """记录错误"""
        with self._lock:
            current_time = time.time()
            if current_time - self._last_error_reset > 60:  # 每分钟重置
                self._error_count = 0
                self._last_error_reset = current_time
            self._error_count += 1
    
    def get_current_metrics(self) -> PerformanceMetrics:
        """获取当前性能指标"""
        with self._lock:
            # 计算成功率
            success_rate = 0.0
            if self._ping_stats["total"] > 0:
                success_rate = self._ping_stats["success"] / self._ping_stats["total"]
            
            # 计算平均响应时间
            avg_response_time = 0.0
            if self._ping_stats["response_times"]:
                avg_response_time = sum(self._ping_stats["response_times"]) / len(self._ping_stats["response_times"])
            
            # 获取系统资源信息
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return PerformanceMetrics(
                cpu_percent=process.cpu_percent(),
                memory_percent=process.memory_percent(),
                memory_used_mb=memory_info.rss / 1024 / 1024,
                thread_count=process.num_threads(),
                ping_success_rate=success_rate * 100,
                response_time_avg=avg_response_time,
                errors_per_minute=self._error_count
            )
    
    def get_metrics_history(self, last_n: int = 10) -> list[PerformanceMetrics]:
        """获取历史性能指标"""
        with self._lock:
            return self._metrics_history[-last_n:] if self._metrics_history else []
    
    def _monitor_loop(self):
        """监控循环"""
        while not self._stop_event.wait(self.collection_interval):
            try:
                metrics = self.get_current_metrics()
                with self._lock:
                    self._metrics_history.append(metrics)
                    # 保持历史记录在合理范围内
                    if len(self._metrics_history) > 100:
                        self._metrics_history = self._metrics_history[-50:]
                
                # 检查异常指标
                self._check_health_alerts(metrics)
                
            except Exception as e:
                logging.error(f"性能监控循环异常: {e}")
                self.record_error()
    
    def _check_health_alerts(self, metrics: PerformanceMetrics):
        """检查健康状态并发出警告"""
        warnings = []
        
        if metrics.memory_percent > 80:
            warnings.append(f"内存使用率过高: {metrics.memory_percent:.1f}%")
        
        if metrics.cpu_percent > 80:
            warnings.append(f"CPU使用率过高: {metrics.cpu_percent:.1f}%")
        
        if metrics.ping_success_rate < 90 and metrics.ping_success_rate > 0:
            warnings.append(f"Ping成功率过低: {metrics.ping_success_rate:.1f}%")
        
        if metrics.errors_per_minute > 10:
            warnings.append(f"错误率过高: {metrics.errors_per_minute} 错误/分钟")
        
        for warning in warnings:
            logging.warning(f"性能警告: {warning}")


class HealthChecker:
    """健康检查器"""
    
    def __init__(self):
        self.checks = {}
        self._lock = threading.Lock()
    
    def register_check(self, name: str, check_func, interval: float = 30.0):
        """注册健康检查"""
        with self._lock:
            self.checks[name] = {
                "func": check_func,
                "interval": interval,
                "last_check": 0,
                "last_result": None,
                "last_error": None
            }
    
    def run_checks(self) -> Dict[str, Any]:
        """运行所有健康检查"""
        results = {}
        current_time = time.time()
        
        with self._lock:
            for name, check_info in self.checks.items():
                if current_time - check_info["last_check"] >= check_info["interval"]:
                    try:
                        result = check_info["func"]()
                        check_info["last_result"] = result
                        check_info["last_error"] = None
                        check_info["last_check"] = current_time
                        results[name] = {"status": "healthy", "result": result}
                    except Exception as e:
                        check_info["last_error"] = str(e)
                        check_info["last_check"] = current_time
                        results[name] = {"status": "unhealthy", "error": str(e)}
                        logging.error(f"健康检查 {name} 失败: {e}")
                else:
                    # 使用缓存的结果
                    if check_info["last_error"]:
                        results[name] = {"status": "unhealthy", "error": check_info["last_error"]}
                    else:
                        results[name] = {"status": "healthy", "result": check_info["last_result"]}
        
        return results


# 全局实例
performance_monitor = PerformanceMonitor()
health_checker = HealthChecker()


def setup_monitoring():
    """设置监控"""
    performance_monitor.start()
    
    # 注册基本健康检查
    health_checker.register_check("disk_space", _check_disk_space)
    health_checker.register_check("memory_available", _check_memory_available)
    
    logging.info("监控系统已初始化")


def cleanup_monitoring():
    """清理监控"""
    performance_monitor.stop()
    logging.info("监控系统已清理")


def _check_disk_space() -> Dict[str, Any]:
    """检查磁盘空间"""
    disk_usage = psutil.disk_usage('/')
    free_percent = (disk_usage.free / disk_usage.total) * 100
    return {
        "free_percent": free_percent,
        "free_gb": disk_usage.free / (1024**3),
        "total_gb": disk_usage.total / (1024**3)
    }


def _check_memory_available() -> Dict[str, Any]:
    """检查可用内存"""
    memory = psutil.virtual_memory()
    return {
        "available_percent": memory.available / memory.total * 100,
        "available_gb": memory.available / (1024**3),
        "total_gb": memory.total / (1024**3)
    }
