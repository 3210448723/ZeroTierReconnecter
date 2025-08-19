#!/usr/bin/env python3
"""
测试网络工具模块 - 使用pytest框架
"""
import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

from common.network_utils import ping, validate_ip_address, is_private_ip, format_host_for_display


class TestNetworkUtils:
    """网络工具测试类"""
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_ping_functionality(self):
        """测试ping功能（集成测试）"""
        # 测试本地回环（应该成功）
        assert ping("127.0.0.1", timeout_sec=2) is True
        
        # 测试无效主机（应该失败）
        assert ping("invalid-host-12345.nonexistent", timeout_sec=1) is False
    
    @pytest.mark.parametrize("ip,expected", [
        ("192.168.1.1", True),      # 有效私网IP
        ("8.8.8.8", True),          # 有效公网IP
        ("10.0.0.1", True),         # 有效私网IP
        ("256.1.1.1", False),       # 无效IP
        ("2001:db8::1", True),      # 有效IPv6
        ("invalid_ip", False),      # 明显无效IP
        ("", False),                # 空字符串
    ])
    def test_ip_validation(self, ip, expected):
        """测试IP地址验证"""
        is_valid, _ = validate_ip_address(ip)
        assert is_valid == expected
    
    @pytest.mark.parametrize("ip,expected", [
        ("192.168.1.1", True),      # RFC1918私网
        ("10.0.0.1", True),         # RFC1918私网
        ("172.16.0.1", True),       # RFC1918私网
        ("8.8.8.8", False),         # Google DNS（公网）
        ("1.1.1.1", False),         # Cloudflare DNS（公网）
        ("169.254.1.1", True),      # 链路本地地址（私网）
    ])
    def test_private_ip_detection(self, ip, expected):
        """测试私网IP判断"""
        assert is_private_ip(ip) == expected
    
    def test_format_host_for_display(self):
        """测试主机名显示格式化"""
        # 测试IPv4地址
        assert format_host_for_display("192.168.1.1") == "192.168.1.1"
        
        # 测试IPv6地址（应该添加方括号）
        formatted = format_host_for_display("2001:db8::1")
        assert "[" in formatted and "]" in formatted
        
        # 测试域名
        assert format_host_for_display("example.com") == "example.com"
    
    def test_validate_ip_error_messages(self):
        """测试IP验证错误消息"""
        # 测试回环地址被拒绝
        is_valid, error_msg = validate_ip_address("127.0.0.1")
        assert not is_valid
        assert "回环" in error_msg or "loopback" in error_msg.lower()
        
        # 测试IPv6回环被拒绝
        is_valid, error_msg = validate_ip_address("::1")
        assert not is_valid
        assert "回环" in error_msg or "loopback" in error_msg.lower()
        
        # 测试无效格式
        is_valid, error_msg = validate_ip_address("invalid")
        assert not is_valid
        assert error_msg  # 应该有错误消息
    
    @pytest.mark.unit
    def test_edge_cases(self):
        """测试边界情况"""
        # 测试空字符串
        is_valid, _ = validate_ip_address("")
        assert not is_valid
        
        # 测试极长字符串
        long_string = "a" * 1000
        is_valid, _ = validate_ip_address(long_string)
        assert not is_valid


if __name__ == "__main__":
    # 支持直接运行
    pytest.main([__file__, "-v"])
