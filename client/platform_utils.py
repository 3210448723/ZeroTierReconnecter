import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, List

import psutil
import socket

from .config import ClientConfig

# 尝试导入统一日志工具和网络工具（修复相对导入问题）
try:
    from ..common.logging_utils import setup_unified_logging, get_log_config_from_client_config
    from ..common.network_utils import is_private_ip as unified_is_private_ip
    _USE_UNIFIED_LOGGING = True
    _USE_UNIFIED_NETWORK = True
except ImportError:
    try:
        from common.logging_utils import setup_unified_logging, get_log_config_from_client_config
        from common.network_utils import is_private_ip as unified_is_private_ip
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
    
    # 回退到本地实现 - 但也使用统一的核心逻辑
    try:
        # 尝试使用统一日志工具的核心功能
        if _USE_UNIFIED_LOGGING:
            success = setup_unified_logging(
                log_level=config.log_level,
                log_file=config.log_file,
                use_sanitizer=False,  # 客户端不需要脱敏
                enable_rotation=True
            )
            if success:
                logging.info("使用统一日志工具（回退模式）")
                return
    except ImportError:
        logging.debug("统一日志工具不可用，使用传统实现")
    except Exception as e:
        logging.warning(f"统一日志工具回退失败: {e}，使用传统实现")
    
    # 最终回退：传统本地实现
    _setup_logging_fallback(config)


def _setup_logging_fallback(config: ClientConfig):
    """传统日志配置实现（最终回退）"""
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
            # 确保日志文件目录存在，使用 Path 处理波浪线路径
            log_path = Path(config.log_file).expanduser().resolve()
            log_dir = log_path.parent
            if log_dir:  # 避免空字符串导致的问题
                log_dir.mkdir(parents=True, exist_ok=True)
            
            # 使用轮转文件处理器，防止日志文件过大
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                str(log_path),  # 使用处理后的路径
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logging.info(f"日志文件已配置: {log_path} (轮转: 10MB × 5个文件)")
        except Exception as e:
            logging.warning(f"无法创建轮转日志文件 {config.log_file}: {e}")
            # 回退到普通文件处理器
            try:
                # 再次确保目录存在，使用 Path 处理波浪线路径
                log_path = Path(config.log_file).expanduser().resolve()
                log_dir = log_path.parent
                if log_dir:
                    log_dir.mkdir(parents=True, exist_ok=True)
                
                file_handler = logging.FileHandler(str(log_path), encoding='utf-8')
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
                logging.warning(f"使用普通日志文件: {log_path}")
            except Exception as e2:
                logging.error(f"无法创建日志文件 {config.log_file}: {e2}")


def is_windows() -> bool:
    """判断是否为 Windows 系统"""
    return sys.platform.startswith("win")


def find_executable(candidates: List[str]) -> Optional[str]:
    """在候选路径中查找可执行文件"""
    for path in candidates:
        if os.path.exists(path):
            # Unix系统需要额外检查可执行权限
            if not is_windows() and not os.access(path, os.X_OK):
                logging.debug(f"文件存在但无执行权限: {path}")
                continue
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
    """获取 Windows 服务状态 - 增强错误处理和本地化兼容性"""
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
            
            # 兼容多语言的状态检查
            stdout_upper = result.stdout.upper()
            stdout_lower = result.stdout.lower()
            
            if "STATE" in stdout_upper or "状态" in result.stdout:
                # 运行状态检查（英文+中文+常见本地化）
                running_keywords = ["RUNNING", "运行", "正在运行", "DÉMARRÉ", "EJECUTÁNDOSE", "実行中"]
                if any(keyword in stdout_upper for keyword in running_keywords):
                    logging.debug(f"Windows 服务 {name} 正在运行")
                    return "running"
                
                # 停止状态检查
                stopped_keywords = ["STOPPED", "STOP_PENDING", "停止", "已停止", "停止挂起", "ARRÊTÉ", "DETENIDO", "停止中"]
                if any(keyword in stdout_upper for keyword in stopped_keywords):
                    logging.debug(f"Windows 服务 {name} 已停止")
                    return "stopped"
                
                # 启动中状态检查
                starting_keywords = ["START_PENDING", "启动挂起", "正在启动", "EN COURS", "INICIANDO", "開始中"]
                if any(keyword in stdout_upper for keyword in starting_keywords):
                    logging.debug(f"Windows 服务 {name} 正在启动")
                    return "starting"
                
                # 未知状态
                logging.debug(f"Windows 服务 {name} 状态未知: {result.stdout}")
                return "unknown"
            
            # 服务不存在检查（多语言）
            not_exist_keywords = [
                "does not exist", "服务不存在", "指定的服务不存在", 
                "n'existe pas", "no existe", "存在しません",
                "cannot be found", "找不到", "未找到"
            ]
            if any(keyword in stdout_lower for keyword in not_exist_keywords):
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
    """启动 Windows 服务 - 增强错误诊断和权限处理"""
    service_errors = []
    
    # 尝试通过服务管理器启动
    for name in config.zerotier_service_names or []:
        try:
            result = run_command(["sc", "start", name], timeout=15)
            if result.returncode == 0:
                if "START_PENDING" in result.stdout or "RUNNING" in result.stdout:
                    logging.info(f"Windows 服务 {name} 启动成功")
                    return True
            else:
                # 检查具体的错误原因
                error_output = result.stderr.lower()
                stdout_output = result.stdout.lower()
                
                if "already running" in stdout_output or "已启动" in result.stdout:
                    logging.info(f"Windows 服务 {name} 已经在运行")
                    return True
                elif "access" in error_output or "denied" in error_output or "权限" in result.stderr:
                    service_errors.append(f"{name}: 权限不足，需要管理员权限")
                elif "not found" in error_output or "找不到" in result.stderr:
                    service_errors.append(f"{name}: 服务不存在")
                elif "disabled" in stdout_output or "禁用" in result.stdout:
                    service_errors.append(f"{name}: 服务被禁用")
                else:
                    service_errors.append(f"{name}: {result.stderr.strip() or result.stdout.strip()}")
                    
        except Exception as e:
            service_errors.append(f"{name}: 异常 - {e}")
            logging.debug(f"通过服务管理器启动 {name} 失败: {e}")
            continue
    
    # 记录服务启动失败的详细信息
    if service_errors:
        logging.warning(f"服务启动失败原因: {'; '.join(service_errors)}")
    
    # 尝试直接启动守护进程
    exe_path = find_executable(config.zerotier_bin_paths or [])
    if exe_path:
        try:
            subprocess.Popen(
                [exe_path], 
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            time.sleep(3)  # 给进程更多启动时间
            logging.info(f"直接启动 ZeroTier 守护进程: {exe_path}")
            return True
        except Exception as e:
            logging.error(f"直接启动守护进程失败: {e}")
    else:
        logging.error("未找到 ZeroTier 可执行文件")
    
    logging.error("所有启动 Windows 服务的方法都失败了")
    if service_errors:
        logging.error("建议解决方案: 1) 以管理员身份运行程序 2) 检查ZeroTier是否正确安装 3) 检查服务是否被禁用")
    return False


def _start_linux_service() -> bool:
    """启动 Linux 服务"""
    try:
        # 检查是否为 root 用户（仅在 Unix 系统上）
        is_root = False
        try:
            if hasattr(os, 'geteuid'):
                is_root = getattr(os, 'geteuid')() == 0
        except (AttributeError, OSError):
            # Windows 系统没有 geteuid 或其他权限问题
            pass
        
        if is_root:
            # root 用户直接执行
            result = run_command(["systemctl", "start", "zerotier-one"], timeout=15)
            logging.info("Linux 服务 zerotier-one 启动成功")
            return result.returncode == 0
        else:
            # 非 root 用户，检查 sudo 权限
            try:
                # 测试 sudo 无密码权限
                test_result = run_command(["sudo", "-n", "true"], timeout=5)
                if test_result.returncode != 0:
                    logging.error("启动 Linux 服务需要 sudo 权限，请配置免密码 sudo 或以 root 身份运行")
                    return False
                
                # 有权限，执行启动
                result = run_command(["sudo", "systemctl", "start", "zerotier-one"], timeout=15)
                logging.info("Linux 服务 zerotier-one 启动成功")
                return result.returncode == 0
            except Exception as e:
                logging.error(f"检查 sudo 权限失败: {e}")
                logging.error("启动 Linux 服务需要 sudo 权限，请确保当前用户在 sudo 组中或以 root 身份运行")
                return False
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
    """停止 Windows 服务 - 增强权限处理和错误诊断"""
    stopped = False
    service_errors = []
    
    # 尝试通过服务管理器停止
    for name in config.zerotier_service_names or []:
        try:
            result = run_command(["sc", "stop", name], timeout=15)
            if result.returncode == 0:
                if "STOP_PENDING" in result.stdout or "STOPPED" in result.stdout:
                    logging.info(f"Windows 服务 {name} 停止成功")
                    stopped = True
                    break
            else:
                # 检查是否因为权限问题失败
                error_output = result.stderr.lower()
                if "access" in error_output or "denied" in error_output or "权限" in result.stderr:
                    service_errors.append(f"{name}: 权限不足，可能需要管理员权限")
                elif "not found" in error_output or "找不到" in result.stderr:
                    service_errors.append(f"{name}: 服务不存在")
                elif "已停止" in result.stdout or "stopped" in result.stdout.lower():
                    logging.info(f"Windows 服务 {name} 已经停止")
                    stopped = True
                    break
                else:
                    service_errors.append(f"{name}: {result.stderr.strip()}")
        except Exception as e:
            service_errors.append(f"{name}: {e}")
            logging.debug(f"通过服务管理器停止 {name} 失败: {e}")
            continue
    
    # 如果服务停止失败，记录详细错误信息
    if not stopped and service_errors:
        logging.warning(f"服务停止失败的详细原因: {'; '.join(service_errors)}")
    
    # 强制终止相关进程
    killed = _kill_zerotier_processes()
    
    result = stopped or killed
    if result:
        if stopped:
            logging.info("Windows ZeroTier 服务停止成功")
        else:
            logging.info("Windows ZeroTier 服务通过进程终止停止")
    else:
        logging.error("停止 Windows ZeroTier 服务失败")
        if service_errors:
            logging.error("可能的解决方案: 1) 以管理员身份运行程序 2) 检查服务名称是否正确")
    
    return result


def _stop_linux_service() -> bool:
    """停止 Linux 服务"""
    try:
        # 检查是否为 root 用户（仅在 Unix 系统上）
        is_root = False
        try:
            if hasattr(os, 'geteuid'):
                is_root = getattr(os, 'geteuid')() == 0
        except (AttributeError, OSError):
            # Windows 系统没有 geteuid 或其他权限问题
            pass
        
        if is_root:
            # root 用户直接执行
            result = run_command(["systemctl", "stop", "zerotier-one"], timeout=15)
            if result.returncode == 0:
                logging.info("Linux 服务 zerotier-one 停止成功")
            return result.returncode == 0
        else:
            # 非 root 用户，检查 sudo 权限
            try:
                # 测试 sudo 无密码权限
                test_result = run_command(["sudo", "-n", "true"], timeout=5)
                if test_result.returncode != 0:
                    logging.error("停止 Linux 服务需要 sudo 权限，请配置免密码 sudo 或以 root 身份运行")
                    return False
                
                # 有权限，执行停止
                result = run_command(["sudo", "systemctl", "stop", "zerotier-one"], timeout=15)
                if result.returncode == 0:
                    logging.info("Linux 服务 zerotier-one 停止成功")
                return result.returncode == 0
            except Exception as e:
                logging.error(f"检查 sudo 权限失败: {e}")
                logging.error("停止 Linux 服务需要 sudo 权限，请确保当前用户在 sudo 组中或以 root 身份运行")
                return False
    except Exception as e:
        logging.error(f"停止 Linux 服务失败: {e}")
        return False


def _kill_zerotier_processes() -> bool:
    """强制终止 ZeroTier 服务进程（优先保留GUI应用）- 增强进程识别和错误处理"""
    killed = False
    processes_found = []
    
    try:
        for process in psutil.process_iter(attrs=["name", "pid", "exe"]):
            try:
                name = process.info.get("name", "").lower()
                exe_path = process.info.get("exe", "") or ""
                
                # 更精确的服务进程识别
                is_service_process = False
                
                # 匹配服务进程的关键词
                service_keywords = [
                    "zerotier-one_x64.exe",      # Windows 64位服务进程
                    "zerotier-one_x86.exe",      # Windows 32位服务进程  
                    "zerotier-one.exe",          # 通用服务进程名
                    "zerotierone",               # 服务进程简化名
                ]
                
                for keyword in service_keywords:
                    if keyword in name:
                        is_service_process = True
                        break
                
                # 通过路径进一步确认是服务进程
                if is_service_process and exe_path:
                    service_path_indicators = [
                        "programdata",           # Windows服务常见位置
                        "system32",             # 系统服务位置
                        "/usr/sbin/",           # Linux服务位置
                        "/usr/local/sbin/",     # Linux服务位置
                    ]
                    
                    # 如果路径包含服务目录，确认为服务进程
                    path_matches_service = any(indicator in exe_path.lower() for indicator in service_path_indicators)
                    
                    # 如果路径包含GUI目录，则不是服务进程
                    gui_path_indicators = [
                        "program files",         # GUI应用常见位置
                        "program files (x86)",   # 32位GUI应用位置
                    ]
                    path_matches_gui = any(indicator in exe_path.lower() for indicator in gui_path_indicators)
                    
                    if path_matches_gui:
                        logging.debug(f"跳过GUI应用进程: {name} ({exe_path})")
                        is_service_process = False
                    elif not path_matches_service:
                        # 如果路径既不匹配服务也不匹配GUI，保守处理
                        logging.debug(f"路径不明确的进程，跳过: {name} ({exe_path})")
                        is_service_process = False
                
                if is_service_process:
                    pid = process.info['pid']
                    process_name = process.info['name']
                    processes_found.append(f"{process_name} (PID: {pid})")
                    
                    logging.debug(f"找到ZeroTier服务进程: {process_name} (PID: {pid}) - {exe_path}")
                    
                    # 先尝试正常终止
                    process.terminate()
                    killed = True
                    
                    # 等待进程退出，最多等待5秒
                    try:
                        process.wait(timeout=5)
                        logging.debug(f"服务进程 {process_name} (PID: {pid}) 已正常退出")
                    except psutil.TimeoutExpired:
                        # 如果5秒后还没退出，强制杀死
                        try:
                            process.kill()
                            logging.warning(f"强制杀死服务进程 {process_name} (PID: {pid})")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            # 进程可能已经退出或没有权限
                            pass
                    except psutil.NoSuchProcess:
                        # 进程已经退出
                        logging.debug(f"服务进程 {process_name} (PID: {pid}) 已退出")
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception as e:
                logging.debug(f"检查进程时出错: {e}")
                continue
                
    except Exception as e:
        logging.error(f"终止 ZeroTier 服务进程时出错: {e}")
    
    if processes_found:
        logging.info(f"找到并尝试终止 {len(processes_found)} 个ZeroTier服务进程: {', '.join(processes_found)}")
    else:
        logging.debug("未找到运行中的ZeroTier服务进程")
    
    return killed


# === ZeroTier 应用管理 ===

def get_app_status() -> str:
    """获取 ZeroTier GUI应用状态"""
    try:
        for process in psutil.process_iter(attrs=["name", "exe"]):
            name = process.info.get("name", "").lower()
            exe_path = process.info.get("exe", "") or ""
            
            # 匹配GUI应用进程名
            gui_names = [
                "zerotier one.exe",           # ZeroTier One GUI主程序
                "zerotier_desktop_ui.exe",    # ZeroTier Desktop UI
            ]
            
            is_gui_app = any(gui_name in name for gui_name in gui_names)
            
            # 通过路径进一步确认是GUI应用而不是服务
            if is_gui_app and exe_path:
                # 如果路径包含服务目录，则跳过（避免将服务进程误认为GUI应用）
                service_paths = ["programdata", "system32", "windows"]
                if any(service_path in exe_path.lower() for service_path in service_paths):
                    logging.debug(f"跳过服务进程: {process.info['name']} ({exe_path})")
                    continue
                    
                logging.debug(f"找到 ZeroTier GUI应用进程: {process.info['name']} ({exe_path})")
                return "running"
            elif is_gui_app:
                # 如果无法获取路径信息，保守处理
                logging.debug(f"找到 ZeroTier GUI应用进程: {process.info['name']}")
                return "running"
                
        logging.debug("未找到 ZeroTier GUI应用进程")
        return "stopped"
    except Exception as e:
        logging.error(f"检查GUI应用状态时出错: {e}")
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
    """停止 ZeroTier GUI应用（不包括服务进程）"""
    stopped = False
    try:
        for process in psutil.process_iter(attrs=["name", "pid", "exe"]):
            try:
                name = process.info.get("name", "").lower()
                exe_path = process.info.get("exe", "") or ""
                
                # 仅匹配GUI应用进程，排除服务进程
                is_gui_app = False
                
                # 匹配GUI应用的进程名
                gui_names = [
                    "zerotier one.exe",           # ZeroTier One GUI主程序
                    "zerotier_desktop_ui.exe",    # ZeroTier Desktop UI
                ]
                
                for gui_name in gui_names:
                    if gui_name in name:
                        is_gui_app = True
                        break
                
                # 通过路径进一步确认是GUI应用而不是服务
                if is_gui_app and exe_path:
                    # 如果路径包含服务目录，则跳过（避免误杀服务进程）
                    service_paths = ["programdata", "system32", "windows"]
                    if any(service_path in exe_path.lower() for service_path in service_paths):
                        logging.debug(f"跳过服务进程: {process.info['name']} ({exe_path})")
                        continue
                
                if is_gui_app:
                    pid = process.info['pid']
                    process_name = process.info['name']
                    logging.debug(f"找到GUI应用进程: {process_name} (PID: {pid})")
                    
                    # 先尝试正常终止
                    process.terminate()
                    stopped = True
                    
                    # 等待进程退出，最多等待3秒
                    try:
                        process.wait(timeout=3)
                        logging.debug(f"GUI应用进程 {process_name} (PID: {pid}) 已正常退出")
                    except psutil.TimeoutExpired:
                        # 如果3秒后还没退出，强制杀死
                        try:
                            process.kill()
                            logging.warning(f"强制杀死GUI应用进程 {process_name} (PID: {pid})")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            # 进程可能已经退出或没有权限
                            pass
                    except psutil.NoSuchProcess:
                        # 进程已经退出
                        logging.debug(f"GUI应用进程 {process_name} (PID: {pid}) 已退出")
                        
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

def _basic_ping(host: str, timeout_sec: int = 3) -> bool:
    """基本的ping实现，作为备用方案"""
    import subprocess
    import platform
    
    try:
        # 根据操作系统选择ping命令
        if platform.system().lower() == "windows":
            # Windows使用 -n 指定次数，-w 指定超时(毫秒)
            cmd = ["ping", "-n", "1", "-w", str(timeout_sec * 1000), host]
        else:
            # Linux/Mac使用 -c 指定次数，-W 指定超时(秒)
            cmd = ["ping", "-c", "1", "-W", str(timeout_sec), host]
        
        # 执行ping命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_sec + 2,  # 给进程额外的时间
            text=True
        )
        
        return result.returncode == 0
        
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return False
    except Exception:
        return False


def ping(host: str, timeout_sec: int = 3) -> bool:
    """Ping 指定主机（支持 IPv6）- 使用统一网络工具"""
    try:
        from ..common.network_utils import ping as unified_ping
        return unified_ping(host, timeout_sec)
    except ImportError:
        try:
            from common.network_utils import ping as unified_ping
            return unified_ping(host, timeout_sec)
        except ImportError:
            # 回退到基本实现
            return _basic_ping(host, timeout_sec)


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
