"""
共享网络工具模块
统一客户端和服务端的网络操作实现
"""

import logging
import os
import subprocess
import sys
from typing import Optional


def ping(host: str, timeout_sec: int = 3) -> bool:
    """
    Ping 指定主机 - 统一实现，支持 IPv4/IPv6
    
    Args:
        host: 目标主机地址（IP或域名）
        timeout_sec: 超时时间（秒）
        
    Returns:
        bool: ping 是否成功
    """
    # IP地址验证和IPv6检测
    try:
        import ipaddress
        ip_obj = ipaddress.ip_address(host)
        is_ipv6 = ip_obj.version == 6
    except ValueError:
        # 不是IP地址，可能是域名，使用更严格的IPv6检测
        if ":" in host and not host.startswith(("http://", "https://", "ftp://", "file://")):
            # 更严格的IPv6格式检测
            try:
                # 尝试用socket库验证IPv6格式
                import socket
                socket.inet_pton(socket.AF_INET6, host)
                is_ipv6 = True
            except (socket.error, AttributeError):
                # 如果socket.inet_pton不可用，使用改进的启发式检测
                colon_count = host.count(":")
                # IPv6地址必须有至少2个冒号，且不能包含非法字符
                if colon_count >= 2 and all(c in "0123456789abcdefABCDEF:." for c in host):
                    # 检查是否符合IPv6的基本格式规则
                    parts = host.split(":")
                    is_ipv6 = 3 <= len(parts) <= 8  # IPv6最少3段，最多8段
                else:
                    is_ipv6 = False
        else:
            is_ipv6 = False
    except Exception:
        is_ipv6 = False
    
    # 根据操作系统和地址族构建命令
    if sys.platform.startswith("win"):
        # Windows: -n 次数, -w 超时(毫秒)，IPv6 使用 -6
        if is_ipv6:
            cmd = ["ping", "-6", "-n", "1", "-w", str(timeout_sec * 1000), host]
        else:
            cmd = ["ping", "-n", "1", "-w", str(timeout_sec * 1000), host]
    elif sys.platform == "darwin":
        # macOS(BSD ping): -W 超时(毫秒)，需要将秒转换为毫秒
        ms = max(1, int(timeout_sec * 1000))
        if is_ipv6:
            cmd = ["ping", "-6", "-c", "1", "-W", str(ms), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(ms), host]
    else:
        # Linux: -c 次数, -W 超时(秒)，IPv6 使用 -6
        if is_ipv6:
            cmd = ["ping", "-6", "-c", "1", "-W", str(timeout_sec), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(timeout_sec), host]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 2  # 给subprocess额外的缓冲时间
        )
        # 统一采用返回码判断，避免解析本地化输出
        success = (result.returncode == 0)
        logging.debug(f"Ping {host}: {'成功' if success else '失败'}; rc={result.returncode}")
        return success
    except subprocess.TimeoutExpired:
        logging.debug(f"Ping {host} 超时")
        return False
    except FileNotFoundError:
        logging.error(f"ping 命令不存在，无法ping {host}")
        return False
    except Exception as e:
        logging.debug(f"Ping {host} 时出错: {e}")
        return False


def validate_ip_address(ip: str) -> tuple[bool, str]:
    """
    严格验证IP地址，允许常见的内网/覆盖网段
    
    Args:
        ip: IP地址字符串
        
    Returns:
        tuple: (是否有效, 错误信息)
    """
    try:
        import ipaddress
        ip_obj = ipaddress.ip_address(ip)

        # 检查是否为有效的IPv4或IPv6地址
        if not isinstance(ip_obj, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            return False, "不是有效的IP地址格式"

        # 排除特殊地址
        if ip_obj.is_loopback:
            return False, "不允许回环地址"
        if ip_obj.is_link_local:
            return False, "不允许链路本地地址"
        if ip_obj.is_multicast:
            return False, "不允许组播地址"
        if ip_obj.is_reserved:
            return False, "不允许保留地址"
        if ip_obj.is_unspecified:
            return False, "不允许未指定地址"

        # 允许私网 IPv4（RFC1918）与 CGNAT（100.64.0.0/10），以及 IPv6 ULA（fc00::/7）
        return True, ""

    except ValueError as e:
        return False, f"IP地址格式错误: {e}"
    except Exception as e:
        return False, f"IP地址验证异常: {e}"


def is_private_ip(ip: str) -> bool:
    """
    判断是否为私网 IP 地址（使用 ipaddress 模块）
    
    Args:
        ip: IP地址字符串
        
    Returns:
        bool: 是否为私网地址
    """
    try:
        import ipaddress
        ip_obj = ipaddress.ip_address(ip)
        
        # 排除回环地址
        if ip_obj.is_loopback:
            return False
        
        # 检查是否为私网地址
        return ip_obj.is_private
    except ValueError:
        # 如果IP格式无效，回退到正则表达式方法
        import re
        if ip.startswith('127.'):  # 回环地址
            return False
        
        # 私网地址范围
        private_ranges = [
            r'^10\.',                    # 10.0.0.0/8
            r'^192\.168\.',              # 192.168.0.0/16
            r'^172\.(1[6-9]|2[0-9]|3[01])\.',  # 172.16.0.0/12
            r'^100\.(6[4-9]|[7-9][0-9]|1[0-1][0-9]|12[0-7])\.',  # 100.64.0.0/10 CGNAT
        ]
        
        return any(re.match(pattern, ip) for pattern in private_ranges)


def format_host_for_display(host: str, max_length: int = 15) -> str:
    """
    格式化主机地址用于显示（避免过长的IPv6地址）
    
    Args:
        host: 主机地址
        max_length: 最大显示长度
        
    Returns:
        str: 格式化后的地址
    """
    if len(host) <= max_length:
        return host
    
    # 如果是IPv6地址，尝试简化显示
    try:
        import ipaddress
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.version == 6:
            compressed = ip_obj.compressed
            if len(compressed) <= max_length:
                return compressed
            # 截断显示
            return compressed[:max_length-3] + "..."
    except ValueError:
        pass
    
    # 普通截断
    return host[:max_length-3] + "..."
