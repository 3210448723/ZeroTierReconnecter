#!/usr/bin/env python3
"""
测试统一网络工具模块
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from common.network_utils import ping, validate_ip_address, is_private_ip, format_host_for_display

def test_network_utils():
    """测试网络工具函数"""
    print("=" * 50)
    print("网络工具模块测试")
    print("=" * 50)
    
    # 测试 ping 功能
    print("\n1. Ping 测试:")
    test_hosts = ["8.8.8.8", "127.0.0.1", "192.168.1.1", "invalid-host-12345"]
    for host in test_hosts:
        result = ping(host, timeout_sec=2)
        print(f"  Ping {host}: {'成功' if result else '失败'}")
    
    # 测试 IP 地址验证
    print("\n2. IP 地址验证测试:")
    test_ips = [
        "192.168.1.1",      # 有效私网IP
        "8.8.8.8",          # 有效公网IP
        "127.0.0.1",        # 回环地址（应拒绝）
        "10.0.0.1",         # 有效私网IP
        "256.1.1.1",        # 无效IP
        "::1",              # IPv6回环（应拒绝）
        "2001:db8::1"       # 有效IPv6
    ]
    
    for ip in test_ips:
        is_valid, error_msg = validate_ip_address(ip)
        print(f"  {ip:15} -> {'有效' if is_valid else f'无效: {error_msg}'}")
    
    # 测试私网IP判断
    print("\n3. 私网IP判断测试:")
    test_private_ips = ["192.168.1.1", "10.0.0.1", "172.16.0.1", "8.8.8.8", "127.0.0.1"]
    for ip in test_private_ips:
        is_private = is_private_ip(ip)
        print(f"  {ip:15} -> {'私网' if is_private else '公网/特殊'}")
    
    # 测试主机显示格式化
    print("\n4. 主机显示格式化测试:")
    test_hosts_format = [
        "192.168.1.1",
        "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
        "very-long-hostname.example.com"
    ]
    for host in test_hosts_format:
        formatted = format_host_for_display(host, max_length=15)
        print(f"  {host:40} -> {formatted}")
    
    print("\n测试完成!")

if __name__ == "__main__":
    test_network_utils()
