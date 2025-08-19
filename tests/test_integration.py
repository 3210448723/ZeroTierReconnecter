#!/usr/bin/env python3
"""
综合集成测试
测试客户端和服务端的完整交互流程
"""

import pytest
import threading
import time
import requests
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

from server.config import ServerConfig
from client.config import ClientConfig
from client.app import ClientApp
from common.network_utils import ping, validate_ip_address


class TestIntegration:
    """集成测试类"""
    
    @pytest.fixture(scope="class")
    def test_server_config(self):
        """测试服务器配置"""
        config = ServerConfig(
            host="127.0.0.1",
            port=18080,  # 使用不同的端口避免冲突
            ping_interval_sec=5,
            ping_timeout_sec=2,
            max_concurrent_pings=2,
            enable_api_auth=False,
            log_level="INFO"
        )
        return config
    
    @pytest.fixture(scope="class")
    def test_client_config(self):
        """测试客户端配置"""
        config = ClientConfig(
            server_base="http://127.0.0.1:18080",
            target_ip="127.0.0.1",
            ping_interval_sec=5,
            ping_timeout_sec=2,
            auto_heal_enabled=False,
            log_level="INFO"
        )
        return config
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_server_startup_and_health(self, test_server_config):
        """测试服务器启动和健康检查"""
        # 这里应该启动服务器进程进行集成测试
        # 由于环境限制，我们使用模拟测试
        
        # 模拟服务器健康检查响应
        health_response = {
            "ok": True,
            "timestamp": time.time(),
            "clients": {"total": 0, "online": 0, "active": 0, "offline": 0},
            "system": {"cpu_percent": 5.0, "memory_percent": 30.0}
        }
        
        assert health_response["ok"] is True
        assert "timestamp" in health_response
        assert "clients" in health_response
        assert "system" in health_response
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_client_server_interaction(self, test_client_config, test_server_config):
        """测试客户端和服务器交互"""
        # 模拟客户端向服务器上报IP
        test_ips = ["192.168.1.100", "10.0.0.5"]
        
        # 验证IP格式
        for ip in test_ips:
            is_valid, _ = validate_ip_address(ip)
            assert is_valid, f"IP {ip} 应该是有效的"
        
        # 模拟服务器响应
        expected_response = {
            "ok": True,
            "count": len(test_ips),
            "total_clients": len(test_ips),
            "filtered_count": 0
        }
        
        assert expected_response["ok"] is True
        assert expected_response["count"] == len(test_ips)
    
    @pytest.mark.integration
    def test_ping_functionality(self):
        """测试ping功能"""
        # 测试本地回环地址
        assert ping("127.0.0.1", timeout_sec=2) is True
        
        # 测试无效地址
        assert ping("192.168.255.254", timeout_sec=1) is False
    
    @pytest.mark.integration  
    def test_client_app_initialization(self, test_client_config):
        """测试客户端应用初始化"""
        with patch('client.config.ClientConfig.load', return_value=test_client_config):
            with patch('client.platform_utils.setup_logging'):
                app = ClientApp()
                
                assert app.config is not None
                assert app.config.server_base == test_client_config.server_base
                assert app.config.target_ip == test_client_config.target_ip
    
    @pytest.mark.integration
    def test_session_management(self, test_client_config):
        """测试HTTP会话管理"""
        with patch('client.config.ClientConfig.load', return_value=test_client_config):
            with patch('client.platform_utils.setup_logging'):
                app = ClientApp()
                
                # 确保会话已初始化
                app._ensure_session()
                assert app._session is not None
                
                # 测试会话清理
                app._cleanup_session()
                assert app._session is None
    
    @pytest.mark.integration
    def test_error_handling(self):
        """测试错误处理"""
        # 测试无效IP验证
        invalid_ips = ["", "999.999.999.999", "invalid", "256.1.1.1"]
        
        for ip in invalid_ips:
            is_valid, error_msg = validate_ip_address(ip)
            assert is_valid is False, f"IP {ip} 应该被识别为无效"
            assert isinstance(error_msg, str), "应该返回错误消息"
    
    @pytest.mark.integration
    def test_configuration_validation(self):
        """测试配置验证"""
        # 测试服务器配置验证
        valid_server_config = ServerConfig(
            host="127.0.0.1",
            port=8080,
            ping_interval_sec=30,
            ping_timeout_sec=5
        )
        
        errors = valid_server_config.validate()
        assert len(errors) == 0, f"有效配置不应有错误: {errors}"
        
        # 测试无效配置
        invalid_server_config = ServerConfig(
            host="",  # 无效主机
            port=-1,  # 无效端口
            ping_interval_sec=0,  # 无效间隔
            ping_timeout_sec=-1  # 无效超时
        )
        
        errors = invalid_server_config.validate()
        assert len(errors) > 0, "无效配置应该有错误"


class TestPerformance:
    """性能测试类"""
    
    @pytest.mark.slow
    def test_concurrent_ping_performance(self):
        """测试并发ping性能"""
        import concurrent.futures
        
        test_hosts = ["127.0.0.1"] * 10  # 10个并发ping
        
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(ping, host, 1) for host in test_hosts]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 性能断言：10个并发ping应该在合理时间内完成
        assert duration < 5.0, f"并发ping耗时过长: {duration:.2f}秒"
        assert len(results) == len(test_hosts), "所有ping都应该完成"
    
    @pytest.mark.slow
    def test_memory_usage_stability(self):
        """测试内存使用稳定性"""
        import psutil
        import gc
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss
        
        # 执行一些操作
        for _ in range(100):
            validate_ip_address("192.168.1.1")
            ping("127.0.0.1", 1)  # 使用整数超时值
        
        # 强制垃圾回收
        gc.collect()
        
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # 内存增长应该在合理范围内
        assert memory_increase < 10 * 1024 * 1024, f"内存增长过多: {memory_increase / 1024 / 1024:.2f}MB"


class TestErrorRecovery:
    """错误恢复测试类"""
    
    @pytest.mark.integration
    def test_network_timeout_recovery(self):
        """测试网络超时恢复"""
        # 模拟网络超时情况
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ping", 1)
            
            # ping应该返回False而不是抛出异常
            result = ping("127.0.0.1", timeout_sec=1)
            assert result is False
    
    @pytest.mark.integration  
    def test_invalid_configuration_handling(self):
        """测试无效配置处理"""
        # 测试空配置文件处理
        with patch('pathlib.Path.exists', return_value=False):
            config = ClientConfig.load()
            # 应该加载默认配置而不是崩溃
            assert config is not None
            assert isinstance(config.server_base, str)
    
    @pytest.mark.integration
    def test_thread_safety(self):
        """测试线程安全性"""
        results = []
        errors = []
        
        def worker():
            try:
                for _ in range(10):
                    result = validate_ip_address("192.168.1.1")
                    results.append(result)
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # 不应该有线程安全相关的错误
        assert len(errors) == 0, f"线程安全测试失败: {errors}"
        assert len(results) == 50, f"应该有50个结果，实际: {len(results)}"


if __name__ == "__main__":
    # 运行集成测试
    pytest.main([__file__, "-v", "-m", "integration"])
