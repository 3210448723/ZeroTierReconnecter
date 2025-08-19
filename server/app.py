"""
ZeroTier Solver 服务端应用
提供客户端IP监控、ping调度和状态管理功能

主要功能:
- 客户端IP上报和验证
- 智能ping调度和结果收集
- 配置热重载和日志管理
- 健康检查和监控指标
- 可选的API认证机制
"""

import json
import logging
import threading
import time
import traceback
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict

from .config import ServerConfig
from .ping_scheduler import OptimizedPingScheduler
from .client_manager import ThreadSafeClientManager
from .metrics import metrics
from .config_watcher import HotReloadConfig
from .log_sanitizer import SanitizedFormatter

# 尝试相对导入，如果失败则使用绝对导入
try:
    from ..common.network_utils import ping, validate_ip_address
    from ..common.logging_utils import setup_unified_logging, get_log_config_from_server_config
except ImportError:
    from common.network_utils import ping, validate_ip_address
    from common.logging_utils import setup_unified_logging, get_log_config_from_server_config

# === 常量定义 ===
APP_VERSION = "1.0.0"
MAX_IP_LENGTH = 45  # IPv6最大长度 + 余量
MAX_IPS_PER_REQUEST = 20  # 单次请求最大IP数量
SYNC_INTERVAL_SEC = 30  # 调度器同步间隔
CLEANUP_INTERVAL_SEC = 3600  # 客户端清理间隔(1小时)
ERROR_SLEEP_SEC = 5.0  # 异常后休眠时间
MIN_SLEEP_SEC = 0.2  # 最小休眠时间
MAX_SLEEP_SEC = 2.0  # 最大休眠时间

# === FastAPI应用初始化 ===
app = FastAPI(
    title="ZeroTier Solver Server", 
    version=APP_VERSION,
    description="ZeroTier网络监控和故障自愈服务",
    docs_url="/docs",
    redoc_url="/redoc"
)

# === 全局状态 ===
_shutdown_event = threading.Event()
_save_lock = threading.Lock()  # 数据保存互斥锁，防止周期保存与关闭保存竞争
_executor_lock = threading.Lock()  # 线程池操作互斥锁，确保原子性
security = HTTPBearer(auto_error=False)

# === 中间件配置 ===
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """请求性能监控中间件"""
    start_time = time.time()
    try:
        response = await call_next(request)
        return response
    finally:
        # 无论成功还是异常都记录请求指标
        duration = time.time() - start_time
        metrics.record_request(duration)

# === 全局组件初始化 ===
config = ServerConfig.load()
_client_manager = ThreadSafeClientManager()
_ping_scheduler = OptimizedPingScheduler(ping_interval=config.ping_interval_sec)
_ping_executor: Optional[ThreadPoolExecutor] = None
_config_watcher = HotReloadConfig(config)


def setup_logging():
    """配置日志系统（使用统一日志工具）"""
    try:
        log_config = get_log_config_from_server_config(config)
        success = setup_unified_logging(**log_config)
        if not success:
            raise RuntimeError("统一日志配置失败")
    except Exception as e:
        print(f"日志系统配置失败: {e}")  # 使用print因为logging可能不可用
        raise


# === 数据模型 ===
class RememberPayload(BaseModel):
    """客户端上报IP的请求数据模型"""
    ips: List[str]
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ips": ["192.168.1.100", "10.0.0.5"]
            }
        }
    )

# === 核心功能函数 ===


def load_client_data():
    """从文件加载客户端数据"""
    data_path = config.get_data_file_path()
    
    if not data_path.exists():
        logging.info("数据文件不存在，使用空数据")
        return
    
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        if not isinstance(data, dict):
            logging.warning("数据文件格式无效（非字典类型），使用空数据")
            return
            
        if data:
            _client_manager.load_from_dict(data)
            logging.info(f"成功加载 {len(data)} 个客户端数据")
        else:
            logging.info("数据文件为空，使用空数据")
        
    except json.JSONDecodeError as e:
        logging.error(f"数据文件JSON格式错误: {e}，使用空数据")
    except (PermissionError, OSError) as e:
        logging.error(f"数据文件访问错误: {e}，使用空数据")
    except Exception as e:
        logging.error(f"加载客户端数据失败: {type(e).__name__}: {e}，使用空数据")
        logging.debug(f"详细错误信息: {traceback.format_exc()}")


def save_client_data(force_save: bool = False):
    """原子性保存客户端数据到文件 - 修复竞态条件和关闭竞争"""
    # 防止多个保存操作同时进行（如周期保存与关闭保存冲突）
    with _save_lock:
        # 检查是否正在关闭，如果是则跳过周期保存（除非强制保存）
        if _shutdown_event.is_set() and not force_save:
            logging.debug("正在关闭，跳过周期保存")
            return
            
        data_path = config.get_data_file_path()
        
        try:
            # 确保目录存在
            data_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 原子性获取数据和脏标志状态，避免检查时间和保存时间之间的竞态条件
            data_snapshot = _client_manager.get_data_snapshot_and_mark_clean()
            
            if data_snapshot is None:
                logging.debug("数据无变更，跳过保存")
                return
            
            # 使用更安全的临时文件名，避免并发冲突
            import uuid
            temp_path = data_path.with_suffix(f'.tmp.{uuid.uuid4().hex[:8]}')
            
            try:
                # 原子写入：先写临时文件，再移动
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data_snapshot, f, indent=2, ensure_ascii=False)
                    # 确保数据已写入磁盘（在文件仍打开时）
                    f.flush()
                    import os
                    os.fsync(f.fileno()) if hasattr(os, 'fsync') else None
                
                # 原子性移动操作
                temp_path.replace(data_path)
                
                logging.debug(f"成功保存 {len(data_snapshot)} 个客户端数据")
                
            except Exception as write_error:
                # 写入失败时确保清理临时文件
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                raise write_error
            
        except (PermissionError, OSError) as e:
            logging.error(f"数据文件保存错误: {e}")
            # 保存失败时，重新标记数据为脏，确保下次能重试
            _client_manager.mark_data_dirty()
        except (TypeError, ValueError) as e:
            logging.error(f"数据序列化错误: {e}")
            # 序列化错误通常是数据问题，不需要重新标记为脏
        except Exception as e:
            logging.error(f"保存客户端数据失败: {type(e).__name__}: {e}")
            logging.debug(f"详细错误信息: {traceback.format_exc()}")
            # 未知错误，保守起见重新标记为脏
            _client_manager.mark_data_dirty()


def ping_worker(ip: str) -> tuple[str, bool]:
    """执行ping操作的工作函数 - 集成监控"""
    start_time = time.time()
    try:
        success = ping(ip, config.ping_timeout_sec)
        duration = time.time() - start_time
        
        # 记录ping完成指标
        metrics.record_ping_completed(duration, success)
        
        # 只在debug级别记录详细信息，减少日志噪声
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug(f"Ping {ip}: {'成功' if success else '失败'} ({duration:.2f}s)")
        return ip, success
    except Exception as e:
        duration = time.time() - start_time
        
        # 记录ping失败指标
        metrics.record_ping_completed(duration, False)
        
        # 异常情况总是记录，但使用warning级别
        logging.warning(f"Ping {ip} 异常: {e}")
        return ip, False


def _create_ping_callback(target_ip: str):
    """创建ping结果处理回调函数 - 优化重复调用"""
    def handle_result(future):
        try:
            _, success = future.result()
            # 统一更新：同时更新客户端管理器和调度器
            _client_manager.update_ping_result(target_ip, success)
            _ping_scheduler.update_ping_result(target_ip, success)
            logging.debug(f"更新 {target_ip} ping结果: {'成功' if success else '失败'}")
        except concurrent.futures.CancelledError:
            logging.warning(f"{target_ip} 的ping任务被取消")
            _client_manager.update_ping_result(target_ip, False)
            _ping_scheduler.update_ping_result(target_ip, False)
            logging.debug(f"更新 {target_ip} ping结果: 失败（任务取消）")
        except Exception as exc:
            logging.error(f"处理 {target_ip} ping结果异常: {type(exc).__name__}: {exc}")
            _client_manager.update_ping_result(target_ip, False)
            _ping_scheduler.update_ping_result(target_ip, False)
            logging.debug(f"更新 {target_ip} ping结果: 失败（异常）")
    return handle_result


def _update_ping_interval():
    """检查并更新ping间隔配置"""
    # 预先获取当前间隔，避免异常时变量未定义
    current_interval = getattr(_ping_scheduler, 'ping_interval', config.ping_interval_sec)
    try:
        if config.ping_interval_sec != current_interval:
            _ping_scheduler.ping_interval = config.ping_interval_sec
            logging.info(f"运行期更新ping间隔: {current_interval} -> {config.ping_interval_sec}秒")
            return config.ping_interval_sec
        return current_interval
    except Exception as e:
        logging.error(f"更新调度器ping间隔失败: {e}")
        return current_interval


def _submit_ping_tasks(ips_to_ping: List[str]) -> int:
    """提交ping任务到线程池 - 修复竞态条件，增强安全性"""
    global _ping_executor
    
    if not ips_to_ping:
        return 0
    
    # 原子性获取执行器引用，避免在检查和使用之间被修改
    with _executor_lock:  # 使用模块级锁确保原子性
        current_executor = _ping_executor
        if current_executor is None:
            logging.error("线程池未初始化，无法提交ping任务")
            return 0
        
        # 安全检查线程池状态
        try:
            if hasattr(current_executor, '_shutdown') and current_executor._shutdown:
                logging.warning("线程池已关闭，跳过任务提交")
                return 0
        except AttributeError:
            # 如果无法检查状态，进行功能测试
            try:
                test_future = current_executor.submit(lambda: True)
                test_future.result(timeout=0.1)  # 快速测试
            except Exception:
                logging.warning("线程池状态异常，跳过任务提交")
                return 0
    
    submitted_count = 0
    
    # 优化提交策略：使用批量错峰而非逐个错峰
    batch_size = min(config.max_concurrent_pings, 10)  # 每批最多10个任务
    total_ips = len(ips_to_ping)
    
    for batch_start in range(0, total_ips, batch_size):
        if _shutdown_event.is_set():
            logging.info("检测到停机信号，停止提交ping任务")
            break
        
        # 当前批次的IP列表
        batch_ips = ips_to_ping[batch_start:batch_start + batch_size]
        batch_submitted = 0  # 当前批次实际提交的任务数
        
        # 批量提交当前批次的任务（无延迟）
        for ip in batch_ips:
            if _shutdown_event.is_set():
                break
                
            # 增强的输入验证
            if not ip or not isinstance(ip, str) or len(ip.strip()) == 0:
                logging.warning(f"跳过无效IP地址: {repr(ip)}")
                continue
                
            try:
                # 使用原子性检查：重新获取当前执行器引用
                with _executor_lock:
                    executor_to_use = _ping_executor
                    if executor_to_use is None or executor_to_use != current_executor:
                        logging.info("检测到线程池已被替换，停止提交剩余任务")
                        break
                    
                    # 增强的线程池状态检查
                    if hasattr(executor_to_use, '_shutdown') and executor_to_use._shutdown:
                        logging.info("线程池已关闭，停止提交剩余任务")
                        break
                
                # 在锁外提交任务，避免死锁
                future = executor_to_use.submit(ping_worker, ip.strip())
                future.add_done_callback(_create_ping_callback(ip.strip()))
                submitted_count += 1
                batch_submitted += 1
                
            except (RuntimeError, ValueError) as e:
                # 特定异常类型的处理
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ["shutdown", "closed", "terminated"]):
                    logging.info(f"线程池状态异常({type(e).__name__}): {e}，停止提交剩余任务")
                    break  # 跳出内层循环，记录已提交的任务
                else:
                    logging.error(f"提交ping任务 {ip} 失败: {type(e).__name__}: {e}")
            except Exception as e:
                logging.error(f"提交ping任务 {ip} 时发生未知异常: {type(e).__name__}: {e}")
                # 对于未知异常，继续尝试其他任务，但记录错误
        
        # 记录本批次实际提交的任务数量
        if batch_submitted > 0:
            metrics.record_ping_submitted(batch_submitted)
        
        # 批次间错峰（仅在有下一批次时）
        if batch_start + batch_size < total_ips:
            stagger_time = config.ping_stagger_sec * batch_size  # 批次错峰时间与批次大小相关
            if _shutdown_event.wait(timeout=min(stagger_time, 2.0)):  # 最大错峰2秒
                logging.info("检测到停机信号，退出批次间等待")
                break
    
    return submitted_count


def schedule_ping_tasks():
    """主ping调度循环 - 使用优化调度器"""
    global _ping_executor
    
    # 初始化线程池
    if _ping_executor is None:
        _ping_executor = ThreadPoolExecutor(
            max_workers=config.max_concurrent_pings,
            thread_name_prefix="ping_worker"
        )
    
    # 同步初始ping间隔
    last_interval = _update_ping_interval()
    
    # 初始化时间戳
    last_save_time = time.time()
    last_cleanup_time = time.time() 
    last_sync_time = time.time()
    
    logging.info("Ping调度循环已启动")
    
    while not _shutdown_event.is_set():
        try:
            current_time = time.time()
            
            # 检查配置变更
            last_interval = _update_ping_interval()
            
            # 定期同步客户端数据到调度器
            if current_time - last_sync_time >= SYNC_INTERVAL_SEC:
                sync_clients_to_scheduler()
                last_sync_time = current_time
            
            # 获取准备好的ping任务
            ips_to_ping = _ping_scheduler.get_ready_ips()
            
            if ips_to_ping:
                logging.debug(f"调度器计划ping {len(ips_to_ping)}个客户端")
                submitted = _submit_ping_tasks(ips_to_ping)
                if submitted < len(ips_to_ping):
                    logging.warning(f"只成功提交了 {submitted}/{len(ips_to_ping)} 个ping任务")
            
            # 定期保存数据
            if current_time - last_save_time >= config.save_interval_sec:
                save_client_data()
                last_save_time = current_time
            
            # 定期清理离线客户端
            if current_time - last_cleanup_time >= CLEANUP_INTERVAL_SEC:
                before_count = _client_manager.size()
                removed_count = _client_manager.cleanup_offline_clients(config.client_offline_threshold_sec)
                
                if removed_count > 0:
                    logging.info(f"清理了 {removed_count}/{before_count} 个长时间离线的客户端")
                    try:
                        sync_clients_to_scheduler()
                        logging.debug("客户端清理后调度器同步完成")
                    except Exception as e:
                        logging.error(f"清理后调度器同步失败: {e}")
                
                last_cleanup_time = current_time
            
            # 自适应休眠
            try:
                next_ready_in = _ping_scheduler.next_ready_in()
            except Exception:
                next_ready_in = MAX_SLEEP_SEC
            
            if ips_to_ping:
                sleep_time = MIN_SLEEP_SEC  # 有任务时短等待
            else:
                sleep_time = min(max(next_ready_in, MIN_SLEEP_SEC), MAX_SLEEP_SEC)
            
            if _shutdown_event.wait(timeout=sleep_time):
                logging.info("检测到停机信号，退出调度循环")
                break
            
        except Exception as e:
            logging.error(f"Ping调度循环异常: {e}")
            logging.debug(f"异常详情: {traceback.format_exc()}")
            if _shutdown_event.wait(timeout=ERROR_SLEEP_SEC):
                logging.info("检测到停机信号，退出异常处理等待")
                break
    
    logging.info("Ping调度循环已退出")


def sync_clients_to_scheduler():
    """同步客户端管理器数据到调度器"""
    try:
        all_clients = _client_manager.get_all_clients()
        sched_clients = _ping_scheduler.get_all_clients()
        
        removed = 0
        added = 0
        
        # 移除不再存在的客户端
        for ip in list(sched_clients.keys()):
            if ip not in all_clients:
                try:
                    _ping_scheduler.remove_client(ip)
                    removed += 1
                except Exception as e:
                    logging.warning(f"从调度器移除客户端 {ip} 失败: {e}")
        
        # 新增/更新现有客户端
        for ip, client_data in all_clients.items():
            try:
                _ping_scheduler.add_client(ip, client_data)
                added += 1
            except Exception as e:
                logging.warning(f"向调度器添加客户端 {ip} 失败: {e}")
        
        logging.debug(f"调度器同步完成: 新增/更新 {added}个, 移除 {removed}个, 总计 {len(all_clients)}个")
        
    except Exception as e:
        logging.error(f"同步客户端到调度器失败: {e}")


def update_ping_result(ip: str, success: bool):
    """更新ping结果到客户端管理器"""
    _client_manager.update_ping_result(ip, success)
    logging.debug(f"更新 {ip} ping结果: {'成功' if success else '失败'}")


# === API认证 ===
def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证API密钥的依赖函数"""
    if not config.enable_api_auth:
        return True
    
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="需要API认证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if credentials.credentials != config.api_key:
        raise HTTPException(status_code=403, detail="API密钥无效")
    
    return True


def get_optional_auth():
    """可选API认证装饰器工厂 - 改进策略一致性"""
    def optional_verify(credentials: HTTPAuthorizationCredentials = Depends(security)):
        # 如果启用了API认证
        if config.enable_api_auth:
            # 必须提供凭据且正确
            if not credentials:
                raise HTTPException(
                    status_code=401,
                    detail="启用API认证时必须提供认证凭据",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if credentials.credentials != config.api_key:
                raise HTTPException(status_code=403, detail="API密钥无效")
        # 如果未启用API认证，则允许访问（无论是否提供凭据）
        return True
    return optional_verify


# === API路由 ===

@app.post("/clients/remember", 
          summary="客户端IP上报",
          description="客户端向服务端上报自己的IP地址列表",
          tags=["客户端管理"])
async def remember_clients(payload: RememberPayload, _: bool = Depends(verify_api_key)):
    """客户端上报IP地址 - 包含验证和认证保护"""
    if not payload.ips:
        raise HTTPException(status_code=400, detail="IP列表不能为空")

    # 防止恶意提交大量IP
    if len(payload.ips) > MAX_IPS_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"IP列表数量过多，最多允许{MAX_IPS_PER_REQUEST}个")

    # 验证每个IP地址
    valid_ips = []
    for ip in payload.ips:
        if len(ip) > MAX_IP_LENGTH:
            logging.warning(f"忽略过长的IP地址: {ip[:50]}...")
            continue

        is_valid, error_msg = validate_ip_address(ip)
        if is_valid:
            valid_ips.append(ip)
        else:
            logging.warning(f"忽略无效IP地址 {ip}: {error_msg}")

    if not valid_ips:
        raise HTTPException(status_code=400, detail="没有有效的IP地址")

    # 更新客户端信息
    current_time = time.time()
    for ip in valid_ips:
        _client_manager.add_or_update_client(ip, last_seen=current_time)
        # 立即同步到调度器
        try:
            _ping_scheduler.add_client(ip, {
                "last_seen": current_time, 
                "last_ping_ok": False, 
                "last_ping_at": 0.0
            })
        except Exception as e:
            logging.error(f"将 {ip} 加入调度器失败: {e}")

    total_clients = _client_manager.size()
    logging.info(f"客户端上报IP: {valid_ips} (过滤前: {payload.ips})")

    return {
        "ok": True,
        "count": len(valid_ips),
        "total_clients": total_clients,
        "filtered_count": len(payload.ips) - len(valid_ips)
    }


@app.get("/clients", 
         summary="获取所有客户端",
         description="获取所有已知客户端的详细信息",
         tags=["客户端管理"])
async def list_clients(_: bool = Depends(get_optional_auth())):
    """获取所有客户端信息"""
    return _client_manager.get_all_clients()


@app.get("/clients/active",
         summary="获取活跃客户端", 
         description="获取在线和活跃状态的客户端信息",
         tags=["客户端管理"])
async def list_active_clients(_: bool = Depends(get_optional_auth())):
    """获取活跃客户端信息"""
    return _client_manager.get_active_clients(config.client_offline_threshold_sec)


@app.get("/clients/stats",
         summary="获取客户端统计",
         description="获取客户端数量统计信息",
         tags=["监控"])
async def get_client_stats(_: bool = Depends(get_optional_auth())):
    """获取客户端统计信息"""
    return _client_manager.get_stats(config.client_offline_threshold_sec)


@app.get("/health",
         summary="健康检查",
         description="获取服务端健康状态和系统信息",
         tags=["监控"])
async def health_check():
    """健康检查接口 - 获取系统状态"""
    try:
        client_count = _client_manager.size()
        stats = _client_manager.get_stats(config.client_offline_threshold_sec)
        system_metrics = metrics.get_system_metrics()
        
        # 调度器状态
        scheduler_info = {}
        try:
            scheduler_info = _ping_scheduler.get_stats()
        except Exception as sched_error:
            scheduler_info = {"status": "error", "error": str(sched_error)}
        
        return {
            "ok": True,
            "timestamp": time.time(),
            "uptime_seconds": metrics.get_uptime_seconds(),
            "clients": {
                "total": client_count,
                "online": stats["online"],
                "active": stats["active"],
                "offline": stats["offline"]
            },
            "system": system_metrics,
            "executor": metrics.get_executor_metrics(_ping_executor),
            "scheduler": scheduler_info,
            "config": {
                "host": config.host,
                "port": config.port,
                "ping_interval_sec": config.ping_interval_sec,
                "api_auth_enabled": config.enable_api_auth
            }
        }
        
    except Exception as e:
        logging.error(f"健康检查失败: {e}")
        return {
            "ok": False,
            "error": str(e),
            "timestamp": time.time()
        }


@app.get("/config",
         summary="获取配置信息",
         description="获取当前服务端配置参数",
         tags=["配置"])
async def get_config(_: bool = Depends(get_optional_auth())):
    """获取服务端配置信息"""
    return {
        "ping_interval_sec": config.ping_interval_sec,
        "ping_timeout_sec": config.ping_timeout_sec,
        "max_concurrent_pings": config.max_concurrent_pings,
        "client_offline_threshold_sec": config.client_offline_threshold_sec,
        "log_level": config.log_level,
        "api_auth_enabled": config.enable_api_auth
    }


@app.get("/metrics", 
         response_class=PlainTextResponse,
         summary="Prometheus指标",
         description="获取Prometheus格式的监控指标数据",
         tags=["监控"])
async def get_metrics():
    """获取Prometheus格式的监控指标"""
    return metrics.export_prometheus_format(
        _client_manager, 
        _ping_executor, 
        config.client_offline_threshold_sec
    )


# === 服务器生命周期管理 ===

def _apply_config_changes_after_reload():
    """配置热重载后的处理函数 - 修复竞态条件和增强状态一致性"""
    global _ping_executor
    
    # 在函数开始时捕获配置快照，避免在处理过程中配置被再次修改
    config_snapshot = {
        'max_concurrent_pings': config.max_concurrent_pings,
        'ping_interval_sec': config.ping_interval_sec,
        'log_level': config.log_level,
        'log_file': config.log_file
    }
    
    # 记录应用前的状态，用于回滚
    rollback_info = {
        'logging_configured': False,
        'executor_rebuilt': False,
        'scheduler_updated': False,
        'old_ping_interval': getattr(_ping_scheduler, 'ping_interval', None),
        'old_max_workers': getattr(_ping_executor, '_max_workers', None) if _ping_executor else None
    }
    
    success_count = 0
    total_operations = 3
    
    # 1. 重新设置日志系统
    try:
        setup_logging()
        rollback_info['logging_configured'] = True
        success_count += 1
        logging.info("配置热重载: 日志系统更新成功")
    except Exception as e:
        logging.error(f"配置热重载: 日志系统更新失败: {e}")
    
    # 2. 检查是否需要重建线程池
    try:
        if (_ping_executor and 
            getattr(_ping_executor, '_max_workers', None) != config_snapshot['max_concurrent_pings']):
            logging.info(f"配置热重载: 检测到max_concurrent_pings变化 "
                        f"({rollback_info['old_max_workers']} -> {config_snapshot['max_concurrent_pings']})，重建线程池...")
            _rebuild_ping_executor_safely()
            rollback_info['executor_rebuilt'] = True
            success_count += 1
            logging.info("配置热重载: 线程池重建成功")
        else:
            success_count += 1  # 无需重建也算成功
    except Exception as e:
        logging.error(f"配置热重载: 线程池重建失败: {e}")
        # 线程池重建失败是严重问题，需要警告
        logging.warning("线程池重建失败可能导致新的并发配置无法生效")
    
    # 3. 更新调度器ping间隔
    try:
        old_interval = rollback_info['old_ping_interval']
        _ping_scheduler.ping_interval = config_snapshot['ping_interval_sec']
        rollback_info['scheduler_updated'] = True
        success_count += 1
        
        if old_interval != config_snapshot['ping_interval_sec']:
            logging.info(f"配置热重载: ping间隔更新成功 ({old_interval} -> {config_snapshot['ping_interval_sec']}秒)")
        else:
            logging.debug("配置热重载: ping间隔无变化")
    except Exception as e:
        logging.error(f"配置热重载: ping间隔更新失败: {e}")
        # 尝试回滚ping间隔
        if rollback_info['old_ping_interval'] is not None:
            try:
                _ping_scheduler.ping_interval = rollback_info['old_ping_interval']
                logging.info(f"已回滚ping间隔到: {rollback_info['old_ping_interval']}")
            except Exception as rollback_error:
                logging.error(f"ping间隔回滚也失败: {rollback_error}")
    
    # 汇总配置热重载结果
    if success_count == total_operations:
        logging.info(f"配置热重载完全成功: {success_count}/{total_operations} 项操作成功")
    elif success_count > 0:
        logging.warning(f"配置热重载部分成功: {success_count}/{total_operations} 项操作成功，"
                       f"系统可能处于不一致状态")
    else:
        logging.error(f"配置热重载完全失败: {success_count}/{total_operations} 项操作成功")


def _rebuild_ping_executor_safely():
    """安全地重建线程池 - 使用模块级锁，修复竞态条件"""
    global _ping_executor
    
    # 使用模块级锁确保线程安全，避免并发重建
    with _executor_lock:
        if _ping_executor is None:
            return
        
        logging.info("开始安全重建线程池...")
        old_executor = _ping_executor
        
        try:
            # 1. 创建新线程池
            new_executor = ThreadPoolExecutor(
                max_workers=config.max_concurrent_pings,
                thread_name_prefix=f"ping_worker_{int(time.time())}"
            )
            
            # 2. 原子性替换线程池引用 - 在锁保护下进行
            # 之后所有新任务都会提交到新线程池
            _ping_executor = new_executor
            
            # 3. 标记旧线程池开始关闭流程（在替换之后）
            old_executor.shutdown(wait=False)  # 立即标记关闭，不等待完成
            
            logging.info(f"线程池重建完成: {old_executor._max_workers} -> {new_executor._max_workers} workers")
            
        except Exception as e:
            logging.error(f"线程池重建失败: {e}")
            # 如果新线程池创建失败，确保不会丢失旧的
            if '_ping_executor' not in locals() or _ping_executor is None:
                _ping_executor = old_executor
            raise
        
        # 4. 异步清理旧线程池
        def shutdown_old_executor():
            try:
                logging.debug("异步关闭旧线程池...")
                # 设置合理的超时，避免阻塞太久
                shutdown_timeout = 15  # 15秒超时
                
                # 使用带超时的关闭
                old_executor.shutdown(wait=False)  # 先标记关闭
                
                # 循环检查是否关闭完成，带退避机制
                import time
                check_interval = 0.5  # 开始检查间隔
                max_check_interval = 2.0  # 最大检查间隔
                total_waited = 0.0
                
                while total_waited < shutdown_timeout:
                    # 检查是否还有活跃线程
                    try:
                        if hasattr(old_executor, '_threads'):
                            active_threads = len([t for t in old_executor._threads if t.is_alive()])
                            if active_threads == 0:
                                logging.debug("旧线程池所有线程已退出")
                                break
                            logging.debug(f"旧线程池还有 {active_threads} 个活跃线程")
                        else:
                            # 无法检查线程状态，等待固定时间后退出
                            time.sleep(min(3.0, shutdown_timeout - total_waited))
                            break
                    except Exception:
                        # 检查失败，使用简单等待
                        time.sleep(min(1.0, shutdown_timeout - total_waited))
                        break
                    
                    # 退避等待
                    time.sleep(check_interval)
                    total_waited += check_interval
                    check_interval = min(check_interval * 1.2, max_check_interval)  # 指数退避，上限2秒
                
                if total_waited >= shutdown_timeout:
                    logging.warning(f"旧线程池关闭超时({shutdown_timeout}s)，可能仍有任务在执行")
                else:
                    logging.debug("旧线程池已正常关闭")
                
            except Exception as shutdown_error:
                logging.warning(f"旧线程池关闭时出现异常: {shutdown_error}")
                # 尽力清理资源
                try:
                    if hasattr(old_executor, '_threads'):
                        active_threads = len([t for t in old_executor._threads if t.is_alive()])
                        if active_threads > 0:
                            logging.warning(f"强制清理：仍有 {active_threads} 个活跃线程")
                except Exception:
                    logging.debug("无法获取线程池状态进行强制清理")
        
        # 在独立线程中异步关闭旧执行器，避免阻塞
        shutdown_thread = threading.Thread(
            target=shutdown_old_executor, 
            daemon=True, 
            name="executor_shutdown"
        )
        shutdown_thread.start()


@app.on_event("startup")
def on_startup():
    """FastAPI启动事件处理"""
    try:
        initialize_server()
        logging.info("服务启动成功")
    except Exception as e:
        logging.error(f"服务启动失败: {e}")
        logging.error(f"启动异常详情: {traceback.format_exc()}")
        raise RuntimeError(f"服务启动失败: {e}") from e


@app.on_event("shutdown") 
def on_shutdown():
    """FastAPI关闭事件处理"""
    try:
        cleanup_server()
        logging.info("服务关闭成功")
    except Exception as e:
        logging.error(f"服务关闭异常: {e}")
        logging.error(f"关闭异常详情: {traceback.format_exc()}")


def initialize_server():
    """初始化服务器组件"""
    # 配置日志系统
    setup_logging()
    logging.info("ZeroTier Solver 服务端启动")
    
    # 验证配置
    errors = config.validate()
    if errors:
        logging.error("配置验证失败:")
        for error in errors:
            logging.error(f"  - {error}")
        raise RuntimeError("配置验证失败")
    
    # 加载客户端数据并同步到调度器
    load_client_data()
    sync_clients_to_scheduler()
    
    # 启动ping调度线程
    ping_thread = threading.Thread(
        target=schedule_ping_tasks, 
        daemon=True, 
        name="ping_scheduler"
    )
    ping_thread.start()
    logging.info("Ping调度线程已启动")
    
    # 启动配置热重载监听
    config_path = ServerConfig.get_config_path()
    _config_watcher.add_reload_callback(_apply_config_changes_after_reload)
    _config_watcher.start_watching(str(config_path))
    
    logging.info(f"服务端初始化完成，监听 {config.host}:{config.port}")


def cleanup_server():
    """清理服务器资源"""
    logging.info("正在关闭服务端...")
    
    # 先保存客户端数据（在设置停机信号前）
    try:
        save_client_data(force_save=True)
        logging.info("关停前数据保存完成")
    except Exception as e:
        logging.error(f"关停前保存客户端数据失败: {e}")
    
    # 发送停机信号
    _shutdown_event.set()
    logging.info("已发送停机信号")
    
    # 停止配置监听
    try:
        _config_watcher.stop_watching()
    except Exception as e:
        logging.error(f"停止配置监听失败: {e}")
    
    # 最后再次尝试保存数据（双重保险）
    try:
        save_client_data(force_save=True)
    except Exception as e:
        logging.error(f"最终保存客户端数据失败: {e}")
    
    # 关闭线程池
    global _ping_executor
    if _ping_executor:
        try:
            logging.info("正在关闭线程池...")
            _ping_executor.shutdown(wait=True)
            _ping_executor = None
            logging.info("线程池已正常关闭")
        except Exception as e:
            logging.error(f"关闭线程池失败: {e}")
    
    logging.info("服务端已关闭")
