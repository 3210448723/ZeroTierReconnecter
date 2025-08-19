import logging
import os
import re
import subprocess
import sys
import time
from typing import Optional, List

import psutil
import socket

from .config import ClientConfig

# 尝试导入统一日志工具和网络工具
try:
    from ..common.logging_utils import setup_unified_logging, get_log_config_from_client_config
    from ..common.network_utils import is_private_ip as unified_is_private_ip
    _USE_UNIFIED_LOGGING = True
    _USE_UNIFIED_NETWORK = True
except ImportError:
    _USE_UNIFIED_LOGGING = False
    _USE_UNIFIED_NETWORK = False


def setup_logging(config: ClientConfig):
    """配置日志系统（优先使用统一工具）"""
    if _USE_UNIFIED_LOGGING:
        # 使用统一日志配置
        try:
            log_config = get_log_config_from_client_config(config)
            success = setup_unified_logging(**log_config)
            if success:
                return
        except Exception as e:
            logging.warning(f"统一日志配置失败，回退到本地实现: {e}")
    
    # 回退到原有实现
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    
    # 配置日志格式
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 移除现有的处理器
    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    logger.setLevel(level)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（如果配置了）
    if config.log_file:
        try:
            # 确保日志文件目录存在
            log_dir = os.path.dirname(config.log_file)
            if log_dir:  # 避免空字符串导致的问题
                os.makedirs(log_dir, exist_ok=True)
            
            # 使用轮转文件处理器，防止日志文件过大
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                config.log_file, 
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logging.info(f"日志文件已配置: {config.log_file} (轮转: 10MB × 5个文件)")
        except Exception as e:
            logging.warning(f"无法创建轮转日志文件 {config.log_file}: {e}")
            # 回退到普通文件处理器
            try:
                # 再次确保目录存在
                log_dir = os.path.dirname(config.log_file)
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)
                
                file_handler = logging.FileHandler(config.log_file, encoding='utf-8')
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
                logging.warning(f"使用普通日志文件: {config.log_file}")
            except Exception as e2:
                logging.error(f"无法创建日志文件 {config.log_file}: {e2}")


def is_windows() -> bool:
    """判断是否为 Windows 系统"""
    return sys.platform.startswith("win")


def find_executable(candidates: List[str]) -> Optional[str]:
    """在候选路径中查找可执行文件"""
    for path in candidates:
        if os.path.exists(path):
            logging.debug(f"找到可执行文件: {path}")
            return path
    logging.debug(f"未找到可执行文件，候选路径: {candidates}")
    return None


def discover_zerotier_paths() -> dict:
    """自动发现 ZeroTier 路径（增强版）"""
    import subprocess
    import shutil
    
    paths = {
        'service_bin': [],
        'gui_bin': [],
        'service_names': []
    }
    
    if is_windows():
        # Windows: 检查常见安装位置和注册表
        common_locations = [
            r"C:\ProgramData\ZeroTier\One",
            r"C:\Program Files\ZeroTier\One", 
            r"C:\Program Files (x86)\ZeroTier\One"
        ]
        
        for location in common_locations:
            if os.path.exists(location):
                # 查找服务可执行文件
                for exe_name in ["zerotier-one_x64.exe", "zerotier-one.exe"]:
                    exe_path = os.path.join(location, exe_name)
                    if os.path.exists(exe_path):
                        paths['service_bin'].append(exe_path)
                
                # 查找GUI可执行文件
                for gui_name in ["zerotier_desktop_ui.exe", "ZeroTier One.exe"]:
                    gui_path = os.path.join(location, gui_name)
                    if os.path.exists(gui_path):
                        paths['gui_bin'].append(gui_path)
        
        # 尝试通过注册表查找
        try:
            import winreg
            key_paths = [
                r"SOFTWARE\ZeroTier",
                r"SOFTWARE\WOW6432Node\ZeroTier"
            ]
            for key_path in key_paths:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                        install_path = winreg.QueryValueEx(key, "InstallPath")[0]
                        if os.path.exists(install_path):
                            for exe in ["zerotier-one_x64.exe", "zerotier-one.exe"]:
                                full_path = os.path.join(install_path, exe)
                                if os.path.exists(full_path) and full_path not in paths['service_bin']:
                                    paths['service_bin'].append(full_path)
                except (FileNotFoundError, OSError):
                    continue
        except ImportError:
            pass
        
        # Windows 服务名称
        paths['service_names'] = ["ZeroTier One", "ZeroTierOneService", "zerotier-one"]
        
    else:
        # Linux/macOS: 使用 which 和常见路径
        try:
            which_result = subprocess.run(['which', 'zerotier-one'], 
                                        capture_output=True, text=True, timeout=5)
            if which_result.returncode == 0:
                found_path = which_result.stdout.strip()
                if found_path and os.path.exists(found_path):
                    paths['service_bin'].append(found_path)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # 检查常见Linux路径
        linux_paths = [
            "/usr/sbin/zerotier-one",
            "/usr/local/sbin/zerotier-one", 
            "/opt/zerotier-one/zerotier-one",
            "/usr/bin/zerotier-one"
        ]
        
        for path in linux_paths:
            if os.path.exists(path) and path not in paths['service_bin']:
                paths['service_bin'].append(path)
        
        # Linux 服务名称
        paths['service_names'] = ["zerotier-one"]
    
    # 去重并记录发现结果
    for key in ['service_bin', 'gui_bin']:
        paths[key] = list(dict.fromkeys(paths[key]))  # 保持顺序的去重
    
    logging.info(f"自动发现 ZeroTier 路径: {paths}")
    return paths


def run_command(cmd: List[str] | str, check: bool = False, shell: bool = False, timeout: int = 30) -> subprocess.CompletedProcess:
    """执行系统命令"""
    try:
        result = subprocess.run(
            cmd, 
            check=check, 
            shell=shell, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            timeout=timeout
        )
        logging.debug(f"命令执行成功: {cmd}")
        return result
    except subprocess.TimeoutExpired:
        logging.error(f"命令执行超时: {cmd}")
        raise
    except Exception as e:
        logging.error(f"命令执行失败: {cmd}, 错误: {e}")
        raise


# === ZeroTier 服务管理 ===

def get_service_status(config: ClientConfig) -> str:
    """获取 ZeroTier 服务状态"""
    if is_windows():
        return _get_windows_service_status(config.zerotier_service_names or [])
    else:
        return _get_linux_service_status()


def _get_windows_service_status(service_names: List[str]) -> str:
    """获取 Windows 服务状态 - 增强错误处理"""
    if not service_names:
        logging.warning("服务名称列表为空")
        return "not_found"
    
    last_error = None
    for name in service_names:
        if not name or not isinstance(name, str):
            logging.warning(f"跳过无效服务名称: {repr(name)}")
            continue
            
        try:
            result = run_command(["sc", "query", name.strip()], timeout=10)
            
            # 更严格的状态检查
            stdout_upper = result.stdout.upper()
            if "STATE" in stdout_upper:
                if "RUNNING" in stdout_upper:
                    logging.debug(f"Windows 服务 {name} 正在运行")
                    return "running"
                elif "STOPPED" in stdout_upper or "STOP_PENDING" in stdout_upper:
                    logging.debug(f"Windows 服务 {name} 已停止")
                    return "stopped"
                elif "START_PENDING" in stdout_upper:
                    logging.debug(f"Windows 服务 {name} 正在启动")
                    return "starting"
                else:
                    logging.debug(f"Windows 服务 {name} 状态未知: {result.stdout}")
                    return "unknown"
            elif "服务不存在" in result.stdout or "does not exist" in result.stdout.lower():
                logging.debug(f"Windows 服务 {name} 不存在")
                continue
            else:
                logging.debug(f"Windows 服务 {name} 查询结果解析失败: {result.stdout}")
                
        except subprocess.TimeoutExpired:
            logging.warning(f"查询 Windows 服务 {name} 超时")
            last_error = "查询超时"
        except FileNotFoundError:
            logging.error("sc 命令不存在，可能不是 Windows 系统")
            last_error = "sc命令不存在"
            break
        except Exception as e:
            logging.debug(f"查询 Windows 服务 {name} 失败: {type(e).__name__}: {e}")
            last_error = str(e)
    
    if last_error:
        logging.warning(f"所有 ZeroTier Windows 服务查询失败，最后错误: {last_error}")
    else:
        logging.warning("未找到任何 ZeroTier Windows 服务")
    return "not_found"


def _get_linux_service_status() -> str:
    """获取 Linux 服务状态 - 增强错误处理"""
    service_commands = [
        (["systemctl", "is-active", "zerotier-one"], "systemd"),
        (["service", "zerotier-one", "status"], "sysv"),
        (["rc-service", "zerotier-one", "status"], "openrc")
    ]
    
    for cmd, system_type in service_commands:
        try:
            result = run_command(cmd, timeout=10)
            status = result.stdout.strip().lower()
            
            if system_type == "systemd":
                if status == "active":
                    logging.debug("Linux 服务 zerotier-one 正在运行 (systemd)")
                    return "running"
                elif status in ("inactive", "failed", "dead"):
                    logging.debug(f"Linux 服务 zerotier-one 状态: {status} (systemd)")
                    return "stopped"
                elif status == "activating":
                    logging.debug("Linux 服务 zerotier-one 正在启动 (systemd)")
                    return "starting"
                else:
                    logging.debug(f"Linux 服务 zerotier-one 状态未知: {status} (systemd)")
                    return "unknown"
                    
            elif system_type in ("sysv", "openrc"):
                # 检查返回码和输出内容
                if result.returncode == 0 and ("running" in status or "started" in status):
                    logging.debug(f"Linux 服务 zerotier-one 正在运行 ({system_type})")
                    return "running"
                elif "stopped" in status or "dead" in status or result.returncode != 0:
                    logging.debug(f"Linux 服务 zerotier-one 已停止 ({system_type})")
                    return "stopped"
                else:
                    logging.debug(f"Linux 服务 zerotier-one 状态未知: {status} ({system_type})")
                    return "unknown"
                    
        except subprocess.TimeoutExpired:
            logging.debug(f"查询 Linux 服务超时: {' '.join(cmd)}")
            continue
        except FileNotFoundError:
            logging.debug(f"命令不存在: {cmd[0]}")
            continue
        except Exception as e:
            logging.debug(f"查询 Linux 服务失败 ({' '.join(cmd)}): {type(e).__name__}: {e}")
            continue
    
    logging.warning("无法查询 Linux 服务状态：所有命令都失败")
    return "unknown"


def start_service(config: ClientConfig) -> bool:
    """启动 ZeroTier 服务"""
    if is_windows():
        return _start_windows_service(config)
    else:
        return _start_linux_service()


def _start_windows_service(config: ClientConfig) -> bool:
    """启动 Windows 服务"""
    # 尝试通过服务管理器启动
    for name in config.zerotier_service_names or []:
        try:
            result = run_command(["sc", "start", name], timeout=10)
            if "START_PENDING" in result.stdout or "RUNNING" in result.stdout:
                logging.info(f"Windows 服务 {name} 启动成功")
                return True
        except Exception as e:
            logging.debug(f"通过服务管理器启动 {name} 失败: {e}")
            continue
    
    # 尝试直接启动守护进程
    exe_path = find_executable(config.zerotier_bin_paths or [])
    if exe_path:
        try:
            subprocess.Popen(
                [exe_path], 
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            time.sleep(2)
            logging.info(f"直接启动 ZeroTier 守护进程: {exe_path}")
            return True
        except Exception as e:
            logging.error(f"直接启动守护进程失败: {e}")
    
    logging.error("所有启动 Windows 服务的方法都失败了")
    return False


def _start_linux_service() -> bool:
    """启动 Linux 服务"""
    try:
        result = run_command(["sudo", "systemctl", "start", "zerotier-one"], timeout=15)
        logging.info("Linux 服务 zerotier-one 启动成功")
        return result.returncode == 0
    except Exception as e:
        logging.error(f"启动 Linux 服务失败: {e}")
        return False


def stop_service(config: ClientConfig) -> bool:
    """停止 ZeroTier 服务"""
    if is_windows():
        return _stop_windows_service(config)
    else:
        return _stop_linux_service()


def _stop_windows_service(config: ClientConfig) -> bool:
    """停止 Windows 服务"""
    stopped = False
    
    # 尝试通过服务管理器停止
    for name in config.zerotier_service_names or []:
        try:
            result = run_command(["sc", "stop", name], timeout=10)
            if "STOP_PENDING" in result.stdout or "STOPPED" in result.stdout:
                logging.info(f"Windows 服务 {name} 停止成功")
                stopped = True
        except Exception as e:
            logging.debug(f"通过服务管理器停止 {name} 失败: {e}")
            continue
    
    # 强制终止相关进程
    killed = _kill_zerotier_processes()
    
    result = stopped or killed
    if result:
        logging.info("Windows ZeroTier 服务停止成功")
    else:
        logging.error("停止 Windows ZeroTier 服务失败")
    
    return result


def _stop_linux_service() -> bool:
    """停止 Linux 服务"""
    try:
        result = run_command(["sudo", "systemctl", "stop", "zerotier-one"], timeout=15)
        if result.returncode == 0:
            logging.info("Linux 服务 zerotier-one 停止成功")
        return result.returncode == 0
    except Exception as e:
        logging.error(f"停止 Linux 服务失败: {e}")
        return False


def _kill_zerotier_processes() -> bool:
    """强制终止 ZeroTier 相关进程"""
    killed = False
    try:
        for process in psutil.process_iter(attrs=["name", "pid"]):
            try:
                name = process.info.get("name", "").lower()
                if any(keyword in name for keyword in ["zerotier-one", "zerotier one"]):
                    process.terminate()
                    logging.debug(f"终止进程 {process.info['name']} (PID: {process.info['pid']})")
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logging.error(f"终止 ZeroTier 进程时出错: {e}")
    
    return killed


# === ZeroTier 应用管理 ===

def get_app_status() -> str:
    """获取 ZeroTier 应用状态"""
    try:
        for process in psutil.process_iter(attrs=["name"]):
            name = process.info.get("name", "").lower()
            if name in ("zerotier one.exe", "zerotier-one.exe", "zerotier-one_x64.exe"):
                logging.debug(f"找到 ZeroTier 应用进程: {process.info['name']}")
                return "running"
        logging.debug("未找到 ZeroTier 应用进程")
        return "stopped"
    except Exception as e:
        logging.error(f"检查应用状态时出错: {e}")
        return "unknown"


def start_app(config: ClientConfig) -> bool:
    """启动 ZeroTier 应用"""
    # 优先尝试 GUI 程序
    exe_path = find_executable(config.zerotier_gui_paths or [])
    if not exe_path:
        # 回退到守护进程
        exe_path = find_executable(config.zerotier_bin_paths or [])
    
    if not exe_path:
        logging.error("未找到 ZeroTier 可执行文件")
        return False
    
    try:
        if is_windows():
            subprocess.Popen(
                [exe_path], 
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            subprocess.Popen([exe_path])
        
        time.sleep(1.5)
        logging.info(f"ZeroTier 应用启动成功: {exe_path}")
        return True
    except Exception as e:
        logging.error(f"启动 ZeroTier 应用失败: {e}")
        return False


def stop_app() -> bool:
    """停止 ZeroTier 应用"""
    stopped = False
    try:
        for process in psutil.process_iter(attrs=["name", "pid"]):
            try:
                name = process.info.get("name", "").lower()
                if name in ("zerotier one.exe", "zerotier-one.exe", "zerotier-one_x64.exe"):
                    process.terminate()
                    logging.debug(f"终止应用进程 {process.info['name']} (PID: {process.info['pid']})")
                    stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        logging.error(f"停止 ZeroTier 应用时出错: {e}")
    
    if stopped:
        logging.info("ZeroTier 应用停止成功")
    else:
        logging.warning("未找到正在运行的 ZeroTier 应用")
    
    return stopped


# === 网络工具 ===

def ping(host: str, timeout_sec: int = 3) -> bool:
    """Ping 指定主机（支持 IPv6）- 使用统一网络工具"""
    from ..common.network_utils import ping as unified_ping
    return unified_ping(host, timeout_sec)


def get_zerotier_ips(config: ClientConfig) -> List[str]:
    """获取本地 ZeroTier 网络接口的 IP 地址（支持IPv4和IPv6）"""
    ips: List[str] = []
    
    try:
        interfaces = psutil.net_if_addrs()
        
        for interface_name, addresses in interfaces.items():
            is_zerotier = any(
                keyword.lower() in interface_name.lower()
                for keyword in (config.zerotier_adapter_keywords or [])
            )
            
            if is_zerotier:
                for addr in addresses:
                    # 支持 IPv4
                    if getattr(addr, 'family', None) == socket.AF_INET:
                        ip = addr.address
                        if not ip.startswith('127.'):
                            ips.append(ip)
                            logging.debug(f"找到 ZeroTier IPv4: {ip} (接口: {interface_name})")
                    
                    # 支持 IPv6
                    elif getattr(addr, 'family', None) == socket.AF_INET6:
                        ip = addr.address
                        # 过滤掉链路本地地址和回环地址
                        if not (ip.startswith('fe80:') or ip.startswith('::1') or ip == '::'):
                            # 移除 IPv6 地址中的范围标识符（如 %eth0）
                            if '%' in ip:
                                ip = ip.split('%')[0]
                            ips.append(ip)
                            logging.debug(f"找到 ZeroTier IPv6: {ip} (接口: {interface_name})")
        
        if not ips:
            logging.warning("未找到 ZeroTier 网络接口")
            # 以前这里会回退枚举私网 IP 并上报，容易误报；改为不回退，交由用户处理
            # 如需恢复回退行为，可在配置中添加开关并在此判断
    except Exception as e:
        logging.error(f"获取 ZeroTier IP 时出错: {e}")
    
    return ips


def _get_private_ips() -> List[str]:
    """获取所有私网 IP 地址（回退方案）"""
    ips = []
    try:
        for interface_name, addresses in psutil.net_if_addrs().items():
            for addr in addresses:
                if getattr(addr, 'family', None) == socket.AF_INET:
                    ip = addr.address
                    # 检查是否为私网地址
                    if _is_private_ip(ip):
                        ips.append(ip)
                        logging.debug(f"找到私网 IP: {ip} (接口: {interface_name})")
    except Exception as e:
        logging.error(f"获取私网 IP 时出错: {e}")
    
    return ips


def _is_private_ip(ip: str) -> bool:
    """判断是否为私网 IP 地址（优先使用统一实现）"""
    if _USE_UNIFIED_NETWORK:
        try:
            return unified_is_private_ip(ip)
        except Exception:
            pass  # 回退到本地实现
    
    # 本地实现作为回退
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


def get_interface_info() -> str:
    """获取网络接口信息（用于调试）"""
    try:
        if is_windows():
            result = run_command(["ipconfig"], timeout=10)
            return result.stdout
        elif sys.platform == 'darwin':
            result = run_command(["ifconfig"], timeout=10)
            return result.stdout
        else:
            result = run_command(["ip", "addr"], timeout=10)
            return result.stdout
    except Exception as e:
        logging.error(f"获取网络接口信息失败: {e}")
        return f"获取失败: {e}"
