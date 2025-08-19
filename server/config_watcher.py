"""
配置热重载模块
监听配置文件变化并自动重新加载
"""

import os
import time
import threading
import logging
from typing import Callable, Optional
from pathlib import Path


class ConfigWatcher:
    """配置文件监视器"""
    __slots__ = ('_config_path', '_callback', '_last_mtime', '_running', '_thread', '_check_interval')
    
    def __init__(self, config_path: str, callback: Callable[[], None], check_interval: float = 1.0):
        self._config_path = Path(config_path)
        self._callback = callback
        self._last_mtime = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._check_interval = check_interval
        
        # 初始化文件修改时间
        if self._config_path.exists():
            self._last_mtime = self._config_path.stat().st_mtime
    
    def start(self):
        """启动配置监听"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logging.info(f"配置监听器已启动: {self._config_path}")
    
    def stop(self):
        """停止配置监听"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logging.info("配置监听器已停止")
    
    def _watch_loop(self):
        """监听循环"""
        while self._running:
            try:
                if self._config_path.exists():
                    current_mtime = self._config_path.stat().st_mtime
                    if current_mtime != self._last_mtime:
                        self._last_mtime = current_mtime
                        logging.info(f"检测到配置文件变化: {self._config_path}")
                        
                        # 短暂延迟确保文件写入完成
                        time.sleep(0.1)
                        
                        try:
                            self._callback()
                            logging.info("配置重载成功")
                        except Exception as e:
                            logging.error(f"配置重载失败: {e}")
                
                time.sleep(self._check_interval)
                
            except Exception as e:
                logging.error(f"配置监听错误: {e}")
                time.sleep(self._check_interval)


class HotReloadConfig:
    """热重载配置管理器"""
    __slots__ = ('_config_instance', '_watcher', '_reload_callbacks')
    
    def __init__(self, config_instance):
        self._config_instance = config_instance
        self._watcher: Optional[ConfigWatcher] = None
        self._reload_callbacks = []
    
    def add_reload_callback(self, callback: Callable[[], None]):
        """添加重载回调函数"""
        self._reload_callbacks.append(callback)
    
    def start_watching(self, config_path: str):
        """开始监听配置文件"""
        self._watcher = ConfigWatcher(config_path, self._on_config_change)
        self._watcher.start()
    
    def stop_watching(self):
        """停止监听配置文件"""
        if self._watcher:
            self._watcher.stop()
    
    def _on_config_change(self):
        """配置变化处理：将新配置字段写回到现有实例，并触发回调"""
        try:
            # 保存旧值用于对比
            old_values = {
                'ping_interval_sec': self._config_instance.ping_interval_sec,
                'ping_timeout_sec': self._config_instance.ping_timeout_sec,
                'max_concurrent_pings': self._config_instance.max_concurrent_pings,
                'client_offline_threshold_sec': self._config_instance.client_offline_threshold_sec,
                'log_level': self._config_instance.log_level,
                'log_file': getattr(self._config_instance, 'log_file', ''),
                'save_interval_sec': getattr(self._config_instance, 'save_interval_sec', 30),
            }
            
            # 加载新配置（类方法返回新实例)
            cfg_cls = type(self._config_instance)
            new_cfg = cfg_cls.load()
            
            # 验证新配置
            validation_errors = new_cfg.validate()
            if validation_errors:
                logging.error(f"新配置验证失败，保持原配置: {validation_errors}")
                return
            
            # 将变化写回当前实例（保持引用不变）
            for key in old_values.keys():
                setattr(self._config_instance, key, getattr(new_cfg, key))
            self._config_instance.host = new_cfg.host
            self._config_instance.port = new_cfg.port
            self._config_instance.data_file = new_cfg.data_file
            
            # 计算变化项
            changes = []
            new_values = {
                'ping_interval_sec': self._config_instance.ping_interval_sec,
                'ping_timeout_sec': self._config_instance.ping_timeout_sec,
                'max_concurrent_pings': self._config_instance.max_concurrent_pings,
                'client_offline_threshold_sec': self._config_instance.client_offline_threshold_sec,
                'log_level': self._config_instance.log_level,
                'log_file': getattr(self._config_instance, 'log_file', ''),
                'save_interval_sec': getattr(self._config_instance, 'save_interval_sec', 30),
            }
            for k, ov in old_values.items():
                nv = new_values[k]
                if ov != nv:
                    changes.append(f"{k}: {ov} -> {nv}")
            
            if changes:
                logging.info(f"配置变化: {', '.join(changes)}")
                # 执行重载回调
                for callback in self._reload_callbacks:
                    try:
                        callback()
                    except Exception as e:
                        logging.error(f"重载回调执行失败: {e}")
            else:
                logging.debug("配置文件已更新，但没有实际变化")
                
        except Exception as e:
            logging.error(f"配置重载失败: {e}")
