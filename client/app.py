import atexit
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib3.util.retry import Retry

import requests
import requests.adapters
from colorama import Fore, Style, init

# 尝试相对导入，如果失败则使用绝对导入
try:
    from .config import ClientConfig
    from .platform_utils import (
        setup_logging, get_service_status, start_service, stop_service,
        get_app_status, start_app, stop_app, ping, get_zerotier_ips,
        get_interface_info
    )
except ImportError:
    from client.config import ClientConfig
    from client.platform_utils import (
        setup_logging, get_service_status, start_service, stop_service,
        get_app_status, start_app, stop_app, ping, get_zerotier_ips,
        get_interface_info
    )

init(autoreset=True)


# 常量定义
MAX_RESTART_FAILURES = 5           # 最大连续重启失败次数
RESTART_BACKOFF_BASE_SEC = 30      # 基础退避时间(秒)
SESSION_MAX_AGE_SEC = 3600         # 会话最大生存时间（1小时）
SESSION_MAX_REQUESTS = 1000        # 会话最大请求数量
DEFAULT_TIMEOUT_SEC = 10           # 默认超时时间
MAX_BACKOFF_EXPONENT = 4           # 最大退避指数（降低以避免过长间隔）
MAX_BACKOFF_TIME_SEC = 240        # 最大退避时间(4分钟，更合理的上限)
NETWORK_RECOVERY_WAIT_SEC = 300    # 达到最大失败次数时的等待时间(5分钟)


class ClientApp:
    def __init__(self) -> None:
        self.config = ClientConfig.load()
        setup_logging(self.config)
        
        # 尝试自动发现和更新 ZeroTier 路径
        try:
            self.config.auto_discover_zerotier_paths()
        except Exception as e:
            logging.warning(f"自动发现 ZeroTier 路径时出错: {e}")
        
        self._stop_event = threading.Event()
        self._bg_thread: Optional[threading.Thread] = None
        
        # 自动治愈重启失败跟踪
        self._restart_failure_count = 0  # 连续重启失败次数
        self._max_restart_failures = MAX_RESTART_FAILURES  # 最大连续失败次数
        self._restart_backoff_base = RESTART_BACKOFF_BASE_SEC  # 基础退避时间(秒)
        self._last_restart_time = 0.0   # 上次重启时间
        
        # HTTP会话，使用连接池提高性能，添加生命周期管理
        self._session: Optional[requests.Session] = None
        self._session_created_at = 0.0  # 会话创建时间
        self._session_max_age = SESSION_MAX_AGE_SEC  # 会话最大生存时间
        self._session_request_count = 0  # 会话处理的请求数量
        self._session_max_requests = SESSION_MAX_REQUESTS  # 会话最大请求数量
        self._session_lock = threading.Lock()  # 会话访问锁，确保线程安全
        self._init_session()
        
        # 配置默认超时
        self._default_timeout = DEFAULT_TIMEOUT_SEC
        
        # 注册退出清理函数（比 __del__ 更可靠）
        atexit.register(self._cleanup_session)
        
        logging.info("ZeroTier Reconnecter 客户端已启动")

    def _init_session(self):
        """初始化HTTP会话 - 增强资源管理"""
        if self._session is not None:
            # 如果已有会话，先清理再重建
            self._cleanup_session()
            
        try:
            self._session = requests.Session()
            self._session_created_at = time.time()
            self._session_request_count = 0
            
            # 配置连接池参数和重试策略（仅对幂等方法重试）
            retry_strategy = Retry(
                total=3,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],  # 仅对幂等方法重试
                backoff_factor=1
            )
            
            # 配置适配器，限制连接池大小防止资源泄漏
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=5,     # 连接池数量（增加以支持并发请求）
                pool_maxsize=10,        # 每个连接池的最大连接数
                max_retries=retry_strategy,
                pool_block=True         # 连接池满时阻塞而不是创建新连接
            )
            self._session.mount('http://', adapter)
            self._session.mount('https://', adapter)
            
            logging.debug("HTTP会话已初始化，配置了连接池和重试策略")
            
        except Exception as e:
            logging.error(f"初始化HTTP会话失败: {e}")
            self._session = None
            raise

    def _cleanup_session(self):
        """安全地清理HTTP会话 - 修复连接池泄漏，增强线程安全"""
        with self._session_lock:  # 确保线程安全
            if hasattr(self, '_session') and self._session is not None:
                try:
                    # 关闭session中的所有适配器和连接池
                    for adapter in self._session.adapters.values():
                        try:
                            # 安全地尝试清理连接池管理器（如果存在）
                            if hasattr(adapter, 'poolmanager'):
                                poolmanager = getattr(adapter, 'poolmanager', None)
                                if poolmanager and hasattr(poolmanager, 'clear'):
                                    poolmanager.clear()
                            adapter.close()
                        except Exception as adapter_error:
                            logging.debug(f"关闭适配器时出错: {adapter_error}")
                    
                    # 关闭session本身
                    self._session.close()
                    logging.debug("HTTP会话和连接池已完全关闭")
                except Exception as e:
                    logging.error(f"关闭HTTP会话时出错: {e}")
                finally:
                    self._session = None
                    self._session_request_count = 0

    def _ensure_session(self):
        """确保HTTP会话可用 - 优化版本，减少锁竞争"""
        current_time = time.time()
        
        # 先进行无锁检查，减少锁竞争
        should_recreate = (
            self._session is None or
            current_time - self._session_created_at > self._session_max_age or
            self._session_request_count >= self._session_max_requests
        )
        
        if not should_recreate:
            return
            
        # 只有需要重建时才获取锁
        with self._session_lock:
            # 双重检查锁定模式，防止重复重建
            current_time = time.time()
            should_recreate = (
                self._session is None or
                current_time - self._session_created_at > self._session_max_age or
                self._session_request_count >= self._session_max_requests
            )
            
            if should_recreate:
                # 确定重建原因（用于调试）
                if self._session is None:
                    reason = "会话不存在"
                elif current_time - self._session_created_at > self._session_max_age:
                    reason = f"会话超时({self._session_max_age}s)"
                else:
                    reason = f"请求过多({self._session_request_count})"
                
                logging.debug(f"重建HTTP会话: {reason}")
                # 记录会话轮换统计信息（仅info级别，避免日志噪声）
                if self._session_request_count >= self._session_max_requests:
                    logging.info(f"HTTP会话已处理 {self._session_request_count} 个请求，重建以保持性能")
                
                try:
                    self._init_session()
                except Exception as e:
                    logging.error(f"重建HTTP会话失败: {e}")
                    # 即使重建失败，也要确保有基本的会话可用
                    if self._session is None:
                        try:
                            self._session = requests.Session()
                            self._session_created_at = time.time()
                            self._session_request_count = 0
                        except Exception as fallback_error:
                            logging.critical(f"创建备用HTTP会话失败: {fallback_error}")
    
    def _record_request(self):
        """记录请求使用（在实际发起请求后调用）"""
        with self._session_lock:
            if self._session is not None:
                self._session_request_count += 1

    # ---- UI 适配方法 ----
    def log_and_print(self, message: str, level: str = "INFO", color: str = "white"):
        """同时记录日志和在UI中显示"""
        if level == "INFO":
            logging.info(message)
        elif level == "WARNING":
            logging.warning(message)
        elif level == "ERROR":
            logging.error(message)
        elif level == "DEBUG":
            logging.debug(message)

        color_code = {
            'red': Fore.RED,
            'green': Fore.GREEN,
            'yellow': Fore.YELLOW,
            'blue': Fore.BLUE,
            'cyan': Fore.CYAN,
            'magenta': Fore.MAGENTA,
            'white': Fore.WHITE
        }.get(color, Fore.WHITE)
        print(color_code + message)
    def _get_headers(self):
        """获取请求头，包含认证信息"""
        headers = {'Content-Type': 'application/json'}
        if self.config.api_key:
            headers['Authorization'] = f'Bearer {self.config.api_key}'
        return headers

    # ---- API 交互 ----
    def remember_self(self):
        """向服务端上报本机 IP"""
        print("—— 向服务端上报本机 IP ——")
        print(f"目标服务端: {self.config.server_base}")
        print()
        
        try:
            self._ensure_session()
        except Exception as e:
            logging.error(f"会话初始化失败: {e}")
            return False
        
        ips = get_zerotier_ips(self.config)
        if not ips:
            message = "未找到本地 ZeroTier IP，请确认已加入网络。"
            self.log_and_print(message, "WARNING", "yellow")
            return False
        
        print(f"发现本机 ZeroTier IP: {ips}")
        
        payload = {"ips": ips}
        try:
            response = self._session.post(  # type: ignore  # _ensure_session 确保不为 None
                f"{self.config.server_base}/clients/remember", 
                json=payload, 
                timeout=self._default_timeout,
                headers=self._get_headers()
            )
            self._record_request()  # 记录成功发起的请求
            if response.ok:
                result = response.json()
                message = f"✓ 已成功上报本机 IP: {ips}，服务端总客户端数: {result.get('total_clients', '未知')}"
                self.log_and_print(message, "INFO", "green")
                return True
            else:
                # 详细分析错误原因
                if response.status_code == 404:
                    if 'nginx' in response.text.lower():
                        message = f"✗ 上报失败: 服务端返回404 (nginx)"
                        print(Fore.RED + message)
                        print(Fore.YELLOW + "可能原因:")
                        print("  1. nginx作为反向代理，但未正确配置到ZeroTier服务端")
                        print("  2. ZeroTier服务端未在nginx配置的后端端口运行")
                        print("  3. 请检查nginx配置或直接连接ZeroTier服务端端口(如:5418)")
                    else:
                        message = f"✗ 上报失败: 404 - 路径不存在，请检查服务端地址是否正确"
                        print(Fore.RED + message)
                elif response.status_code == 401:
                    message = f"✗ 上报失败: 401 - 需要API密钥认证，请使用选项3设置API密钥"
                    print(Fore.RED + message)
                elif response.status_code == 403:
                    message = f"✗ 上报失败: 403 - API密钥无效，请检查密钥是否正确"
                    print(Fore.RED + message)
                else:
                    message = f"✗ 上报失败: HTTP {response.status_code}"
                    print(Fore.RED + message)
                    print(f"响应内容: {response.text[:200]}")
                
                logging.error(f"上报失败: {response.status_code} {response.text}")
                return False
        except requests.exceptions.Timeout as e:
            message = f"✗ 上报超时: 服务端响应时间过长"
            self.log_and_print(message, "WARNING", "yellow")
            logging.warning(f"服务端上报超时: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            message = f"✗ 上报失败: 无法连接到服务端"
            self.log_and_print(message, "WARNING", "yellow")
            logging.warning(f"服务端连接错误: {e}")
            return False
        except Exception as e:
            message = f"✗ 上报异常: {e}"
            self.log_and_print(message, "ERROR", "red")
            return False

    def start_local_server(self):
        """启动本地服务端"""
        print("—— 启动本地服务端 ——")
        print("此功能将在后台启动 ZeroTier Reconnecter 服务端")
        print()
        
        # 检查是否已有服务端在运行
        if self.check_server_health(silent=True):
            print(Fore.YELLOW + "检测到服务端已在运行中")
            server_url = self.config.server_base
            print(f"服务端地址: {server_url}")
            
            choice = input("是否重启服务端？ (y/N): ").strip().lower()
            if choice != 'y':
                print("操作已取消")
                return
            
            print("正在重启服务端...")
        else:
            print("正在启动服务端...")
        
        try:
            from pathlib import Path
            
            # 获取当前项目根目录
            project_root = Path(__file__).parent.parent
            main_py_path = project_root / "main.py"
            
            if not main_py_path.exists():
                print(Fore.RED + "错误: 找不到 main.py 文件")
                return
            
            # 构建启动命令
            cmd = [sys.executable, str(main_py_path), "server"]
            
            print(f"执行命令: {' '.join(cmd)}")
            print("服务端将在后台运行...")
            
            # 在新窗口中启动服务端（Windows）
            if sys.platform == "win32":
                # 使用 creationflags 在新窗口中启动，避免管道阻塞
                subprocess.Popen(
                    cmd,
                    cwd=str(project_root),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Linux/Mac 使用正确的后台启动方式
                # 使用shell=True配合nohup和重定向，或使用start_new_session
                if hasattr(os, 'setsid'):
                    # 使用进程组分离的方式（推荐）
                    subprocess.Popen(
                        cmd,
                        cwd=str(project_root),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=os.setsid
                    )
                else:
                    # 回退到shell方式
                    cmd_str = ' '.join(cmd) + ' >/dev/null 2>&1 &'
                    subprocess.Popen(
                        cmd_str,
                        shell=True,
                        cwd=str(project_root)
                    )
            
            print(Fore.GREEN + "服务端启动命令已执行")
            print("请等待几秒钟，然后检查服务端健康状态...")
            
            # 等待服务端启动
            print("等待服务端启动", end="")
            for i in range(5):
                time.sleep(1)
                print(".", end="", flush=True)
            print()
            
            # 检查服务端是否成功启动
            if self.check_server_health(silent=True):
                print(Fore.GREEN + "✓ 服务端启动成功！")
                print(f"服务端地址: {self.config.server_base}")
                logging.info("用户启动本地服务端成功")
            else:
                print(Fore.YELLOW + "服务端可能正在启动中...")
                print("请稍后手动检查服务端健康状态")
                logging.warning("本地服务端启动后健康检查失败")
                
        except Exception as e:
            message = f"启动服务端时发生错误: {e}"
            print(Fore.RED + message)
            logging.error(f"启动本地服务端异常: {e}")

    def check_server_health(self, silent=False):
        """检查服务端健康状态"""
        if not silent:
            print("—— 检查服务端健康状态 ——")
        
        try:
            self._ensure_session()
        except Exception as e:
            if not silent:
                message = f"会话初始化失败: {e}"
                print(Fore.RED + message)
                logging.error(message)
            return False
        
        try:
            response = self._session.get(  # type: ignore  # _ensure_session 确保不为 None
                f"{self.config.server_base}/health", 
                timeout=self._default_timeout,
                headers=self._get_headers()
            )
            self._record_request()  # 记录成功发起的请求
            if response.ok:
                data = response.json()
                clients_info = data.get('clients', {})
                total = clients_info.get('total', 0) if isinstance(clients_info, dict) else clients_info
                
                if not silent:
                    message = f"服务端正常，客户端数量: {total}"
                    print(Fore.GREEN + message)
                
                # 降低日志噪声：详细数据改为debug级别，info只记录摘要
                if not silent:
                    logging.info(f"服务端健康检查成功，客户端数量: {total}")
                logging.debug(f"服务端详细状态: {data}")
                return True
            else:
                if not silent:
                    message = f"服务端健康检查失败: HTTP {response.status_code}"
                    print(Fore.RED + message)
                    logging.error(f"{message}, 响应: {response.text[:200]}")
                return False
        except requests.exceptions.ConnectionError as e:
            if not silent:
                message = f"无法连接到服务端: 连接被拒绝"
                print(Fore.RED + message)
                logging.error(f"服务端连接错误: {e}")
            else:
                logging.debug(f"服务端连接错误: {e}")
            return False
        except requests.exceptions.Timeout as e:
            if not silent:
                message = f"服务端连接超时"
                print(Fore.RED + message)
                logging.error(f"服务端超时: {e}")
            else:
                logging.debug(f"服务端超时: {e}")
            return False
        except requests.exceptions.RequestException as e:
            if not silent:
                message = f"请求服务端时发生错误: {type(e).__name__}"
                print(Fore.RED + message)
                logging.error(f"服务端请求错误: {e}")
            else:
                logging.debug(f"服务端请求错误: {e}")
            return False
        except (ValueError, KeyError) as e:
            message = f"服务端响应格式错误"
            if not silent:
                print(Fore.RED + message)
            logging.error(f"服务端响应解析错误: {e}")
            return False
        except Exception as e:
            message = f"检查服务端时发生未知错误: {type(e).__name__}"
            if not silent:
                print(Fore.RED + message)
            logging.error(f"服务端健康检查未知错误: {e}")
            return False

    def get_server_clients(self):
        """获取服务端客户端列表"""
        self._ensure_session()
        
        try:
            response = self._session.get(  # type: ignore  # _ensure_session 确保不为 None
                f"{self.config.server_base}/clients", 
                timeout=5,
                headers=self._get_headers()
            )
            self._record_request()  # 记录成功发起的请求
            if response.ok:
                clients = response.json()
                print(Fore.CYAN + f"服务端客户端列表 (共 {len(clients)} 个):")
                for ip, info in clients.items():
                    last_seen_timestamp = info.get('last_seen', 0)
                    if last_seen_timestamp > 0:
                        last_seen = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_seen_timestamp))
                    else:
                        last_seen = "未上报"
                    
                    last_ping_ok = info.get('last_ping_ok', False)
                    last_ping_at = info.get('last_ping_at', 0)
                    
                    # 改进状态判断：区分未检测、在线、离线三种状态
                    if last_ping_at == 0:
                        ping_status = "待检测"
                        color = Fore.YELLOW
                    elif last_ping_ok:
                        ping_status = "在线"
                        color = Fore.GREEN
                    else:
                        ping_status = "离线"
                        color = Fore.RED
                    
                    print(f"  {ip}: {color}{ping_status}{Style.RESET_ALL} (最后上报: {last_seen})")
                logging.info(f"获取到 {len(clients)} 个客户端信息")
                return clients
            else:
                message = f"获取客户端列表失败: {response.status_code}"
                print(Fore.RED + message)
                logging.error(message)
                return None
        except Exception as e:
            message = f"获取客户端列表异常: {e}"
            print(Fore.RED + message)
            logging.error(message)
            return None

    def get_server_stats(self):
        """获取服务端统计信息"""
        self._ensure_session()
        
        try:
            response = self._session.get(  # type: ignore  # _ensure_session 确保不为 None
                f"{self.config.server_base}/clients/stats", 
                timeout=5,
                headers=self._get_headers()
            )
            self._record_request()  # 记录成功发起的请求
            if response.ok:
                stats = response.json()
                print(Fore.CYAN + "服务端统计信息:")
                print(f"  总客户端数: {stats.get('total', 0)}")
                print(f"  活跃客户端: {stats.get('active', 0)}")
                print(f"  在线客户端: {Fore.GREEN}{stats.get('online', 0)}{Style.RESET_ALL}")
                print(f"  离线客户端: {Fore.RED}{stats.get('offline', 0)}{Style.RESET_ALL}")
                print(f"  待检测客户端: {Fore.YELLOW}{stats.get('never_pinged', 0)}{Style.RESET_ALL}")
                logging.info(f"获取服务端统计: {stats}")
                return stats
            else:
                message = f"获取统计信息失败: {response.status_code}"
                print(Fore.RED + message)
                logging.error(message)
                return None
        except Exception as e:
            message = f"获取统计信息异常: {e}"
            print(Fore.RED + message)
            logging.error(message)
            return None

    def get_server_config(self):
        """获取服务端配置"""
        self._ensure_session()
        
        try:
            response = self._session.get(  # type: ignore  # _ensure_session 确保不为 None
                f"{self.config.server_base}/config", 
                timeout=5,
                headers=self._get_headers()
            )
            self._record_request()  # 记录成功发起的请求
            if response.ok:
                config = response.json()
                print(Fore.CYAN + "服务端配置:")
                print(f"  Ping 间隔: {config.get('ping_interval_sec', 0)} 秒")
                print(f"  Ping 超时: {config.get('ping_timeout_sec', 0)} 秒")
                print(f"  最大并发Ping: {config.get('max_concurrent_pings', 0)}")
                print(f"  客户端离线阈值: {config.get('client_offline_threshold_sec', 0)} 秒")
                print(f"  日志级别: {config.get('log_level', 'unknown')}")
                logging.info(f"获取服务端配置: {config}")
                return config
            else:
                message = f"获取服务端配置失败: {response.status_code}"
                print(Fore.RED + message)
                logging.error(message)
                return None
        except Exception as e:
            message = f"获取服务端配置异常: {e}"
            print(Fore.RED + message)
            logging.error(message)
            return None

    # ---- 配置管理 ----
    def set_target_ip(self):
        """设置服务端设备 IP"""
        print("—— 设置服务端设备 ZeroTier IP ——")
        print("设置运行ZeroTier Reconnecter服务端的设备IP地址")
        print("客户端将连接到该设备的5418端口进行通信")
        print()
        
        current = self.config.target_ip
        prompt = f"请输入服务端设备的 ZeroTier IP{f' (当前: {current})' if current else ''}: "
        ip = input(prompt).strip()
        
        if ip:
            # 保存目标IP
            self.config.target_ip = ip
            
            # 同时设置服务端地址为该IP的5418端口
            server_url = f"http://{ip}:5418"
            self.config.server_base = server_url
            
            self.config.save()
            message = f"已保存服务端设备 IP: {ip}"
            print(Fore.GREEN + message)
            print(Fore.GREEN + f"服务端地址已自动设置为: {server_url}")
            logging.info(f"设置服务端设备 IP: {ip}, 服务端地址: {server_url}")
            
            # 测试设备连通性
            print("\n正在测试设备连通性...")
            if ping(ip, self.config.ping_timeout_sec):
                message = "✓ 设备网络连通"
                print(Fore.GREEN + message)
                logging.info(f"服务端设备 {ip} 网络可达")
                
                # 测试服务端API连接
                print("正在测试服务端API连接...")
                if self.check_server_health(silent=True):
                    message = "✓ 服务端API连接正常"
                    print(Fore.GREEN + message)
                    
                    # 尝试上报本机IP
                    print("\n尝试上报本机 IP...")
                    self.remember_self()
                else:
                    print(Fore.RED + "✗ 服务端API连接失败")
                    print(Fore.YELLOW + "可能原因:")
                    print("  1. 服务端程序未在目标设备上运行")
                    print("  2. 服务端程序运行在非5418端口")
                    print("  3. 防火墙阻止了5418端口访问")
                    print("  4. 需要API密钥认证（使用选项3设置）")
            else:
                message = "✗ 设备网络不通"
                print(Fore.RED + message)
                print(Fore.YELLOW + "请检查:")
                print("  1. 设备IP地址是否正确")
                print("  2. 两台设备是否在同一ZeroTier网络中")
                print("  3. ZeroTier服务是否正常运行")
                logging.warning(f"服务端设备 {ip} 网络不可达")
        else:
            message = "未输入 IP"
            print(Fore.YELLOW + message)
            logging.warning("用户未输入服务端设备IP")

    def set_server_base(self):
        """高级：手动设置服务端地址"""
        print("—— 高级配置：手动设置服务端地址 ——")
        print("通常建议使用选项1自动配置")
        print("仅在使用非标准端口或特殊配置时使用此选项")
        print()
        
        current = self.config.server_base
        prompt = f"请输入完整服务端地址 (当前: {current}): "
        url = input(prompt).strip()
        
        if url:
            # 确保 URL 格式正确
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            
            self.config.server_base = url.rstrip('/')
            errors = self.config.validate()
            
            if errors:
                print(Fore.RED + "配置验证失败:")
                for error in errors:
                    print(f"  - {error}")
                logging.error(f"服务端地址配置验证失败: {errors}")
                return
            
            self.config.save()
            message = f"已保存服务端地址: {self.config.server_base}"
            print(Fore.GREEN + message)
            logging.info(f"手动设置服务端地址: {self.config.server_base}")
            
            # 测试连接，提供详细的错误诊断
            print("正在测试服务端连接...")
            if self.check_server_health(silent=True):
                message = "✓ 服务端连接测试成功"
                print(Fore.GREEN + message)
                logging.info(message)
            else:
                print(Fore.RED + "✗ 服务端连接测试失败")
                print(Fore.YELLOW + "常见问题排查:")
                print("  1. 检查服务端是否在指定地址和端口运行")
                print("  2. 检查防火墙是否阻止了连接")
                print("  3. 如果使用nginx代理，检查nginx配置")
                print("  4. 确认端口号正确（默认5418）")
                
                # 提供端口扫描建议
                import urllib.parse
                parsed = urllib.parse.urlparse(self.config.server_base)
                if parsed.hostname:
                    print(f"  5. 尝试telnet {parsed.hostname} {parsed.port or 5418} 测试端口连通性")
                
                logging.warning("服务端连接测试失败，已显示排查建议")
        else:
            message = "未输入地址"
            print(Fore.YELLOW + message)
            logging.warning("用户未输入服务端地址")

    def configure_zerotier_paths(self):
        """配置 ZeroTier 路径"""
        print("当前 ZeroTier 配置:")
        print(f"  服务名称: {self.config.zerotier_service_names}")
        print(f"  程序路径: {self.config.zerotier_bin_paths}")
        print(f"  GUI 路径: {self.config.zerotier_gui_paths}")
        print(f"  适配器关键词: {self.config.zerotier_adapter_keywords}")
        print()
        
        choice = input("是否要修改? (y/N): ").strip().lower()
        if choice != 'y':
            return
        
        # 这里可以添加更详细的配置修改逻辑
        message = f"配置修改功能待完善，请直接编辑配置文件: {self.config.get_config_path()}"
        print(Fore.YELLOW + message)
        logging.info("用户尝试修改ZeroTier路径配置")

    def view_config(self):
        """查看当前配置"""
        print("—— 当前配置 ——")
        print(f"服务端设备IP: {self.config.target_ip or '未设置'}")
        print(f"服务端地址: {self.config.server_base}")
        print(f"API密钥: {'***已设置***' if self.config.api_key else '未设置'}")
        print(f"Ping 间隔: {self.config.ping_interval_sec} 秒")
        print(f"Ping 超时: {self.config.ping_timeout_sec} 秒")
        print(f"重启冷却: {self.config.restart_cooldown_sec} 秒")
        print(f"自动治愈: {'已启用' if self.config.auto_heal_enabled else '已禁用'}")
        print(f"日志级别: {self.config.log_level}")
        print(f"配置文件: {self.config.get_config_path()}")
        logging.info("用户查看配置信息")

    def validate_config(self):
        """验证配置"""
        errors = self.config.validate()
        if errors:
            print(Fore.RED + "配置验证失败:")
            for error in errors:
                print(f"  - {error}")
            logging.error(f"配置验证失败: {errors}")
        else:
            message = "配置验证通过"
            print(Fore.GREEN + message)
            logging.info(message)

    def set_api_key(self):
        """设置服务端API密钥"""
        current = self.config.api_key
        prompt = f"请输入服务端API密钥{f' (当前: ***已设置***)' if current else ' (留空表示不使用认证)'}: "
        key = input(prompt).strip()
        
        self.config.api_key = key
        self.config.save()
        
        if key:
            message = "已保存API密钥"
            print(Fore.GREEN + message)
            logging.info("设置API密钥")
        else:
            message = "已清除API密钥"
            print(Fore.YELLOW + message)
            logging.info("清除API密钥")

    def reset_config(self):
        """重置配置设置"""
        print("—— 重置配置设置 ——")
        print("此功能将重置配置文件，您可以选择是否保留用户设置")
        print()
        
        choice = input("是否保留用户设置（目标IP、服务端地址等）？ (Y/n): ").strip().lower()
        preserve_settings = choice != 'n'
        
        confirm_msg = "重置配置" + ("（保留用户设置）" if preserve_settings else "（完全重置）")
        confirm = input(f"确认{confirm_msg}？ (y/N): ").strip().lower()
        
        if confirm != 'y':
            print(Fore.YELLOW + "已取消重置操作")
            return
        
        try:
            # 使用common模块中的重置功能
            from pathlib import Path
            common_path = Path(__file__).parent.parent / "common"
            sys.path.insert(0, str(common_path))
            
            from common.reset_config import reset_client_config
            
            print(f"\n正在{confirm_msg}...")
            success = reset_client_config(preserve_settings=preserve_settings)
            
            if success:
                print(Fore.GREEN + "配置重置成功！")
                print("建议重新启动客户端以应用新配置")
                logging.info(f"用户重置客户端配置，保留设置: {preserve_settings}")
                
                # 提示用户是否重新启动
                restart_choice = input("\n是否现在退出程序以重新启动？ (y/N): ").strip().lower()
                if restart_choice == 'y':
                    print("正在退出程序...")
                    logging.info("用户选择退出以重新启动")
                    sys.exit(0)
            else:
                print(Fore.RED + "配置重置失败，请查看错误信息")
                logging.error("客户端配置重置失败")
                
        except Exception as e:
            message = f"重置配置时发生错误: {e}"
            print(Fore.RED + message)
            logging.error(f"重置配置异常: {e}")

    # ---- ZeroTier 管理 ----
    def start_zerotier_service(self):
        """启动 ZeroTier 服务"""
        success = start_service(self.config)
        message = "服务启动成功" if success else "服务启动失败"
        color = Fore.GREEN if success else Fore.RED
        print(color + message)
        logging.info(f"ZeroTier服务启动{'成功' if success else '失败'}")
        return success

    def stop_zerotier_service(self):
        """停止 ZeroTier 服务"""
        success = stop_service(self.config)
        message = "服务停止成功" if success else "服务停止失败"
        color = Fore.GREEN if success else Fore.RED
        print(color + message)
        logging.info(f"ZeroTier服务停止{'成功' if success else '失败'}")
        return success

    def start_zerotier_app(self):
        """启动 ZeroTier 应用"""
        success = start_app(self.config)
        message = "应用启动成功" if success else "应用启动失败"
        color = Fore.GREEN if success else Fore.RED
        print(color + message)
        logging.info(f"ZeroTier应用启动{'成功' if success else '失败'}")
        return success

    def stop_zerotier_app(self):
        """停止 ZeroTier 应用"""
        success = stop_app()
        message = "应用停止成功" if success else "应用停止失败"
        color = Fore.GREEN if success else Fore.RED
        print(color + message)
        logging.info(f"ZeroTier应用停止{'成功' if success else '失败'}")
        return success

    def restart_strategy(self):
        """执行重启策略 - 增强失败跟踪和退避"""
        message = "执行重启策略：停止应用 -> 停止服务 -> 启动服务 -> 启动应用"
        print(Fore.CYAN + message)
        logging.info("开始执行重启策略")
        
        self._last_restart_time = time.time()
        restart_success = False
        
        try:
            # 停止应用和服务
            self.stop_zerotier_app()
            time.sleep(1)
            self.stop_zerotier_service()
            
            # 等待一段时间
            time.sleep(2)
            
            # 启动服务和应用
            service_ok = self.start_zerotier_service()
            time.sleep(3)
            app_ok = self.start_zerotier_app()
            
            # 检查重启是否成功
            restart_success = service_ok and app_ok
            
            if restart_success:
                self._restart_failure_count = 0  # 重置失败计数
                logging.info("重启策略执行成功")
            else:
                self._restart_failure_count += 1
                logging.warning(f"重启策略可能失败，连续失败次数: {self._restart_failure_count}")
                
        except Exception as e:
            self._restart_failure_count += 1
            logging.error(f"重启策略执行异常: {e}，连续失败次数: {self._restart_failure_count}")
            
        return restart_success

    # ---- 自动化功能 ----
    def auto_heal_loop(self):
        """自动治愈循环 - 修复版本，解决卡死和失败计数问题"""
        cooldown_until = 0.0
        last_status = None
        consecutive_ping_failures = 0  # 新增：连续ping失败计数
        last_ping_time = 0.0           # 新增：上次ping时间
        
        # 增强的状态跟踪
        loop_iteration = 0
        last_log_time = 0.0
        
        while not self._stop_event.is_set():
            try:
                current_time = time.time()
                loop_iteration += 1
                
                # 每隔5分钟输出一次心跳日志，证明循环还在运行
                if current_time - last_log_time >= 300:  # 5分钟
                    logging.info(f"[自动治愈] 心跳检查 (循环 #{loop_iteration}, 失败次数: {self._restart_failure_count})")
                    last_log_time = current_time
                
                # 检查是否设置了目标 IP
                if not self.config.target_ip:
                    if last_status != "no_target":
                        logging.warning("未设置目标 IP，自动治愈暂停")
                        last_status = "no_target"
                    # 使用 Event.wait 替代 time.sleep，响应停止信号
                    if self._stop_event.wait(timeout=5):
                        break
                    continue
                
                # 检查是否达到最大重启失败次数
                if self._restart_failure_count >= self._max_restart_failures:
                    if last_status != "max_failures":
                        logging.error(f"连续重启失败 {self._restart_failure_count} 次，暂停自动治愈")
                        last_status = "max_failures"
                    # 在达到最大失败次数时，使用更长的等待时间，并在网络恢复时重置
                    if self._stop_event.wait(timeout=NETWORK_RECOVERY_WAIT_SEC):  # 5分钟
                        break
                    # 等待后重新检测网络状态，如果恢复则重置失败计数
                    try:
                        if ping(self.config.target_ip, self.config.ping_timeout_sec):
                            logging.info("网络已恢复，重置重启失败计数")
                            self._restart_failure_count = 0
                            consecutive_ping_failures = 0  # 同时重置ping失败计数
                            last_status = None  # 重置状态以触发新的状态消息
                    except Exception as ping_error:
                        logging.warning(f"网络恢复检测时出错: {ping_error}")
                    continue
                
                # Ping 目标主机（增加异常处理）
                try:
                    reachable = ping(self.config.target_ip, self.config.ping_timeout_sec)
                    last_ping_time = current_time
                except Exception as ping_error:
                    logging.warning(f"Ping执行出错: {ping_error}")
                    reachable = False
                    
                status_msg = f"ping {self.config.target_ip}: {'成功' if reachable else '失败'}"
                
                # 更新ping失败计数
                if reachable:
                    if consecutive_ping_failures > 0:
                        logging.info(f"Ping恢复成功，重置连续失败计数 ({consecutive_ping_failures} -> 0)")
                    consecutive_ping_failures = 0
                    # 网络恢复时重置重启失败计数
                    if self._restart_failure_count > 0:
                        logging.info(f"网络已恢复，重置重启失败计数 ({self._restart_failure_count} -> 0)")
                        self._restart_failure_count = 0
                else:
                    consecutive_ping_failures += 1
                
                # 减少日志噪声：只在状态变化或每10次ping失败时记录
                should_log_status = (
                    last_status != status_msg or
                    (not reachable and consecutive_ping_failures % 10 == 0)
                )
                
                if should_log_status:
                    if not reachable and consecutive_ping_failures > 1:
                        logging.info(f"[自动治愈] {status_msg} (连续失败 {consecutive_ping_failures} 次)")
                    else:
                        logging.info(f"[自动治愈] {status_msg}")
                    last_status = status_msg
                
                # 如果不可达且已过冷却期，执行重启策略
                # 增加条件：必须连续ping失败超过3次才触发重启，避免偶发网络波动
                if (not reachable and 
                    consecutive_ping_failures >= 3 and 
                    current_time >= cooldown_until):
                    
                    # 计算动态冷却期（安全的指数退避实现）
                    base_cooldown = max(10, self.config.restart_cooldown_sec)
                    
                    # 限制指数以防止整数溢出，降低最大指数避免过长间隔
                    safe_exponent = min(MAX_BACKOFF_EXPONENT, self._restart_failure_count)
                    exponential_multiplier = min(16, 2 ** safe_exponent)  # 最大16倍（2^4）
                    exponential_backoff = min(MAX_BACKOFF_TIME_SEC, base_cooldown * exponential_multiplier)
                    
                    logging.warning(f"目标主机 {self.config.target_ip} 连续 {consecutive_ping_failures} 次不可达，执行重启策略 "
                                  f"(重启失败次数: {self._restart_failure_count}, 指数: {safe_exponent}, "
                                  f"退避: {exponential_backoff}s)")
                    
                    restart_success = False
                    try:
                        restart_success = self.restart_strategy()
                    except Exception as restart_error:
                        logging.error(f"重启策略执行异常: {restart_error}")
                        self._restart_failure_count += 1
                    
                    # 设置冷却期（使用当前时间 + 退避时间，考虑重启耗时）
                    cooldown_until = time.time() + exponential_backoff
                    
                    # 重启后尝试上报本机 IP（增加超时保护）
                    if self._stop_event.wait(timeout=5):
                        break
                        
                    if restart_success:
                        try:
                            # 给重启一些时间完成
                            if self._stop_event.wait(timeout=10):
                                break
                            # 重启成功后尝试上报
                            if self.remember_self():
                                logging.info("重启后成功上报本机 IP")
                                consecutive_ping_failures = 0  # 重启成功后重置ping失败计数
                        except Exception as report_error:
                            logging.warning(f"重启后上报IP失败: {report_error}")
                
                # 等待下次检查，使用 Event.wait 响应停止信号
                wait_time = max(5, self.config.ping_interval_sec)
                if self._stop_event.wait(timeout=wait_time):
                    break
                
            except Exception as e:
                logging.error(f"自动治愈循环出错: {e}")
                # 异常时短暂等待，同样响应停止信号
                if self._stop_event.wait(timeout=10):
                    break
        
        logging.info("自动治愈循环已退出")

    def start_auto_heal(self):
        """启动自动治愈"""
        if not self.config.auto_heal_enabled:
            message = "自动治愈已在配置中禁用"
            print(Fore.YELLOW + message)
            logging.warning(message)
            return
        
        if self._bg_thread and self._bg_thread.is_alive():
            message = "自动治愈已在运行"
            print(Fore.YELLOW + message)
            logging.warning(message)
            return
        
        self._stop_event.clear()
        self._bg_thread = threading.Thread(target=self.auto_heal_loop, daemon=True)
        self._bg_thread.start()
        
        message = "自动治愈已启动"
        print(Fore.GREEN + message)
        logging.info(message)

    def reset_failure_count(self):
        """重置自动治愈失败计数"""
        print("—— 重置自动治愈失败计数 ——")
        print(f"当前失败计数: {self._restart_failure_count}")
        print(f"最大允许失败: {self._max_restart_failures}")
        
        if self._restart_failure_count == 0:
            message = "失败计数已经为0，无需重置"
            print(Fore.YELLOW + message)
            logging.info(message)
            return
        
        confirm = input("确认重置失败计数？ (y/N): ").strip().lower()
        if confirm != 'y':
            print(Fore.YELLOW + "已取消重置操作")
            return
        
        old_count = self._restart_failure_count
        self._restart_failure_count = 0
        
        message = f"已重置失败计数: {old_count} -> 0"
        print(Fore.GREEN + message)
        logging.info(f"用户手动重置自动治愈失败计数: {old_count} -> 0")
        
        # 如果自动治愈正在运行，提示用户
        if self._bg_thread and self._bg_thread.is_alive():
            print(Fore.GREEN + "自动治愈将继续正常工作")
        else:
            print(Fore.YELLOW + "请启动自动治愈以使重置生效 (选项14)")

    def stop_auto_heal(self):
        """停止自动治愈"""
        self._stop_event.set()
        if self._bg_thread:
            # 延长等待时间，确保线程能响应 Event 信号
            self._bg_thread.join(timeout=10)
            if self._bg_thread.is_alive():
                logging.warning("自动治愈线程未能及时停止")
        
        message = "自动治愈已停止"
        print(Fore.GREEN + message)
        logging.info(message)

    def cleanup(self):
        """清理资源"""
        self.stop_auto_heal()
        self._cleanup_session()

    def debug_auto_heal(self):
        """调试自动治愈状态 - 详细诊断信息"""
        print("—— 自动治愈调试信息 ——")
        
        # 基本状态
        is_running = self._bg_thread and self._bg_thread.is_alive()
        print(f"自动治愈状态: {'运行中' if is_running else '已停止'}")
        print(f"配置启用状态: {'启用' if self.config.auto_heal_enabled else '禁用'}")
        
        if self._bg_thread:
            print(f"后台线程ID: {self._bg_thread.ident}")
            print(f"线程存活状态: {self._bg_thread.is_alive()}")
            print(f"线程是否为守护线程: {self._bg_thread.daemon}")
        else:
            print("后台线程: 未创建")
        
        # 停止事件状态
        print(f"停止信号状态: {'已设置' if self._stop_event.is_set() else '未设置'}")
        
        # 失败计数器状态
        print(f"重启失败计数: {self._restart_failure_count}/{self._max_restart_failures}")
        if self._restart_failure_count >= self._max_restart_failures:
            print(Fore.RED + "  ⚠️ 已达到最大失败次数，自动治愈已暂停")
        
        # 配置检查
        print(f"目标IP设置: {self.config.target_ip or '未设置'}")
        if not self.config.target_ip:
            print(Fore.YELLOW + "  ⚠️ 未设置目标IP，自动治愈无法工作")
        
        print(f"Ping间隔: {self.config.ping_interval_sec} 秒")
        print(f"Ping超时: {self.config.ping_timeout_sec} 秒")
        print(f"重启冷却: {self.config.restart_cooldown_sec} 秒")
        
        # 网络连通性测试
        if self.config.target_ip:
            print(f"\n正在测试目标主机连通性...")
            try:
                start_time = time.time()
                reachable = ping(self.config.target_ip, self.config.ping_timeout_sec)
                ping_time = (time.time() - start_time) * 1000
                
                if reachable:
                    print(f"{Fore.GREEN}✓ 目标主机可达 (用时: {ping_time:.1f}ms)")
                else:
                    print(f"{Fore.RED}✗ 目标主机不可达 (用时: {ping_time:.1f}ms)")
                    print("  这可能是自动治愈停止工作的原因")
            except Exception as e:
                print(f"{Fore.RED}✗ Ping测试异常: {e}")
        
        # 服务端连接测试
        print(f"\n正在测试服务端连接...")
        try:
            start_time = time.time()
            health_ok = self.check_server_health(silent=True)
            api_time = (time.time() - start_time) * 1000
            
            if health_ok:
                print(f"{Fore.GREEN}✓ 服务端连接正常 (用时: {api_time:.1f}ms)")
            else:
                print(f"{Fore.RED}✗ 服务端连接失败 (用时: {api_time:.1f}ms)")
        except Exception as e:
            print(f"{Fore.RED}✗ 服务端测试异常: {e}")
        
        # HTTP会话状态
        with self._session_lock:
            if self._session:
                session_age = time.time() - self._session_created_at
                print(f"\nHTTP会话状态: 正常")
                print(f"  会话存活时间: {session_age:.0f} 秒")
                print(f"  已处理请求: {self._session_request_count}")
                print(f"  最大请求数: {self._session_max_requests}")
                print(f"  最大存活时间: {self._session_max_age} 秒")
            else:
                print(f"\n{Fore.YELLOW}HTTP会话状态: 未初始化")
        
        # 建议和排查步骤
        print(f"\n{Fore.CYAN}排查建议:")
        if not self.config.auto_heal_enabled:
            print(f"  1. 自动治愈在配置中被禁用，请检查配置")
        if not self.config.target_ip:
            print(f"  2. 请先设置目标IP (选项1)")
        if not is_running and self.config.auto_heal_enabled and self.config.target_ip:
            print(f"  3. 尝试重新启动自动治愈 (选项14)")
        if self._restart_failure_count >= self._max_restart_failures:
            print(f"  4. 重启失败次数过多，等待网络恢复或手动重置失败计数")
            print(f"     可以尝试停止后重新启动自动治愈来重置计数")
        
        print(f"  5. 检查日志文件: {self.config.log_file}")
        print(f"  6. 确保ZeroTier服务正常运行")
        
        logging.info("用户查看自动治愈调试信息")

    # ---- 状态查看 ----
    def show_status(self):
        """显示系统状态"""
        print("—— 系统状态 ——")
        
        # ZeroTier 状态
        service_status = get_service_status(self.config)
        app_status = get_app_status()
        print(f"ZeroTier 服务: {service_status}")
        print(f"ZeroTier 应用: {app_status}")
        
        # 网络状态
        if self.config.target_ip:
            try:
                reachable = ping(self.config.target_ip, self.config.ping_timeout_sec)
                status_color = Fore.GREEN if reachable else Fore.RED
                status_text = "可达" if reachable else "不可达"
                print(f"目标主机 ({self.config.target_ip}): {status_color}{status_text}")
            except Exception as e:
                print(f"目标主机 ({self.config.target_ip}): {Fore.YELLOW}检测异常 ({e})")
        else:
            print("目标主机: 未设置")
        
        # 本机 IP
        local_ips = get_zerotier_ips(self.config)
        if local_ips:
            print(f"本机 ZeroTier IP: {', '.join(local_ips)}")
        else:
            print("本机 ZeroTier IP: 未找到")
        
        # 自动化状态（增强诊断信息）
        auto_status = "运行中" if (self._bg_thread and self._bg_thread.is_alive()) else "已停止"
        print(f"自动治愈: {auto_status}")
        
        if auto_status == "运行中":
            print(f"  - 重启失败次数: {self._restart_failure_count}/{self._max_restart_failures}")
            print(f"  - 配置启用状态: {'启用' if self.config.auto_heal_enabled else '禁用'}")
            print(f"  - Ping 间隔: {self.config.ping_interval_sec} 秒")
            print(f"  - 重启冷却: {self.config.restart_cooldown_sec} 秒")
            
            # 显示线程状态
            if self._bg_thread:
                print(f"  - 线程状态: {'活跃' if self._bg_thread.is_alive() else '已终止'}")
                print(f"  - 线程ID: {self._bg_thread.ident}")
        
        # HTTP会话状态
        with self._session_lock:
            if self._session:
                session_age = time.time() - self._session_created_at
                print(f"HTTP会话: 正常 (存活: {session_age:.0f}s, 请求数: {self._session_request_count})")
            else:
                print("HTTP会话: 未初始化")
        
        logging.info("用户查看系统状态")

    def show_network_info(self):
        """显示网络接口信息"""
        print("—— 网络接口信息 ——")
        info = get_interface_info()
        print(info)
        logging.info("用户查看网络接口信息")

    def show_server_status(self):
        """显示服务端状态"""
        print("—— 服务端状态 ——")
        
        # 健康检查
        health_ok = self.check_server_health()
        if not health_ok:
            return
        
        print()
        
        # 获取统计信息
        self.get_server_stats()
        
        print()
        
        # 获取配置信息
        self.get_server_config()
        
        logging.info("用户查看服务端状态")

    # ---- 主菜单 ----
    def menu(self):
        """主菜单"""
        while True:
            print("\n" + "="*50)
            print(Fore.CYAN + Style.BRIGHT + "ZeroTier Reconnecter 客户端")
            print("="*50)
            
            print("配置管理:")
            print("  1) 设置服务端设备 ZeroTier IP")
            print("  2) 高级：手动设置服务端地址")
            print("  3) 设置服务端API密钥")
            print("  4) 查看当前配置")
            print("  5) 验证配置")
            print("  6) 配置 ZeroTier 路径")
            print("  7) 重置配置设置")
            
            print("\nZeroTier 管理:")
            print("  8) 启动 ZeroTier 服务")
            print("  9) 停止 ZeroTier 服务")
            print("  10) 启动 ZeroTier 应用")
            print("  11) 停止 ZeroTier 应用")
            print("  12) 执行重启策略")
            
            print("\n网络功能:")
            print("  13) 向服务端上报本机 IP")
            print("  14) 启动自动治愈")
            print("  15) 停止自动治愈")
            print("  16) 重置自动治愈失败计数")
            
            print("\n服务端交互:")
            print("  17) 启动本地服务端")
            print("  18) 检查服务端健康状态")
            print("  19) 查看服务端客户端列表")
            print("  20) 查看服务端统计信息")
            print("  21) 查看服务端配置")
            print("  22) 查看服务端状态汇总")
            
            print("\n状态查看:")
            print("  23) 查看本地系统状态")
            print("  24) 查看网络接口信息")
            print("  25) 调试自动治愈状态")
            
            print("\n  0) 退出")
            
            choice = input("\n请选择: ").strip()
            
            try:
                if choice == "1":
                    self.set_target_ip()
                elif choice == "2":
                    self.set_server_base()
                elif choice == "3":
                    self.set_api_key()
                elif choice == "4":
                    self.view_config()
                elif choice == "5":
                    self.validate_config()
                elif choice == "6":
                    self.configure_zerotier_paths()
                elif choice == "7":
                    self.reset_config()
                elif choice == "8":
                    self.start_zerotier_service()
                elif choice == "9":
                    self.stop_zerotier_service()
                elif choice == "10":
                    self.start_zerotier_app()
                elif choice == "11":
                    self.stop_zerotier_app()
                elif choice == "12":
                    self.restart_strategy()
                elif choice == "13":
                    self.remember_self()
                elif choice == "14":
                    self.start_auto_heal()
                elif choice == "15":
                    self.stop_auto_heal()
                elif choice == "16":
                    self.reset_failure_count()
                elif choice == "17":
                    self.start_local_server()
                elif choice == "18":
                    self.check_server_health()
                elif choice == "19":
                    self.get_server_clients()
                elif choice == "20":
                    self.get_server_stats()
                elif choice == "21":
                    self.get_server_config()
                elif choice == "22":
                    self.show_server_status()
                elif choice == "23":
                    self.show_status()
                elif choice == "24":
                    self.show_network_info()
                elif choice == "25":
                    self.debug_auto_heal()
                elif choice == "0":
                    message = "正在退出..."
                    print(message)
                    logging.info("客户端正常退出")
                    break
                else:
                    message = "无效选项"
                    print(Fore.YELLOW + message)
                    logging.warning(f"用户输入无效选项: {choice}")
            
            except KeyboardInterrupt:
                message = "\n检测到 Ctrl+C，正在退出..."
                print(Fore.YELLOW + message)
                logging.info("用户通过Ctrl+C退出")
                break
            except Exception as e:
                message = f"操作出错: {e}"
                print(Fore.RED + message)
                logging.error(f"菜单操作出错: {e}")
        # 移除重复清理：已在finally块中统一处理


def main():
    """主入口 - 使用 try/finally 确保资源清理"""
    app = None
    try:
        app = ClientApp()
        app.menu()
    except Exception as e:
        logging.error(f"程序启动失败: {e}")
        message = f"程序启动失败: {e}"
        print(Fore.RED + message)
    finally:
        # 确保资源清理
        if app:
            app.cleanup()


if __name__ == "__main__":
    main()
