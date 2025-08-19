# ZeroTier Solver

一个用于自动化维护 ZeroTier 连接稳定性的跨平台解决方案。当 ZeroTier 连接不稳定时，自动重启服务和应用程序，并维护客户端与服务端的连接状态。

## 功能特性

### 客户端功能
- **跨平台支持**: Windows / Linux / macOS
- **智能网络适配器识别**: 通过网络适配器名称自动识别 ZeroTier 接口
- **ZeroTier 服务管理**: 启动/停止/重启 ZeroTier 服务和应用
- **自动故障恢复**: 监控目标主机连通性，断联时自动执行重启策略
- **配置管理**: 完整的配置文件支持，包含验证和用户友好的菜单
- **详细日志**: 可配置的日志级别和文件输出

### 服务端功能
- **客户端监控**: 接收并追踪所有客户端的 IP 地址和状态
- **智能 Ping 调度**: 多线程但错开的 Ping 机制，避免网络拥塞
- **数据持久化**: 自动保存客户端状态，支持服务重启后恢复
- **RESTful API**: 提供完整的客户端管理和状态查询接口
- **实时统计**: 客户端在线/离线状态统计

## 目录结构
```
ZerotierSolver/
├── client/
│   ├── __init__.py
│   ├── __main__.py          # 客户端入口
│   ├── app.py               # 主应用逻辑
│   ├── app_advanced.py      # 高级界面（开发中）
│   ├── config.py            # 客户端配置管理
│   └── platform_utils.py    # 跨平台工具函数
├── server/
│   ├── __init__.py
│   ├── __main__.py          # 服务端入口
│   ├── app.py               # FastAPI 应用
│   ├── client_manager.py    # 客户端状态管理
│   ├── config.py            # 服务端配置管理
│   ├── config_watcher.py    # 配置文件监控
│   ├── log_sanitizer.py     # 日志脱敏处理
│   ├── metrics.py           # 性能指标收集
│   └── ping_scheduler.py    # 智能Ping调度
├── common/
│   ├── __init__.py
│   └── network_utils.py     # 统一网络工具
├── requirements.txt         # 依赖列表
└── README.md               # 说明文档
```

## 安装与配置

### 环境要求
- Python 3.9+
- 已安装 ZeroTier One 客户端
- Windows 需要管理员权限（用于服务管理）

### 安装步骤

1. **创建虚拟环境**
   ```bash
   python -m venv .venv
   
   # Windows
   .\.venv\Scripts\Activate.ps1
   
   # Linux/macOS
   source .venv/bin/activate
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

## 使用说明

### 启动服务端

服务端通常部署在稳定的服务器上：

```bash
python -m server
```

服务端将在 `0.0.0.0:5418` 上启动（可通过配置修改）。

### 启动客户端

客户端运行在需要监控的机器上：

```bash
# Windows 需要以管理员身份运行
python -m client
```

### 配置说明

#### 客户端配置

首次运行时，客户端会创建配置文件 `~/.zerotier_solver_client.json`。

主要配置项：
- `server_base`: 服务端地址
- `target_ip`: 目标主机 ZeroTier IP
- `zerotier_adapter_keywords`: ZeroTier 网络适配器关键词
- `ping_interval_sec`: Ping 间隔（秒）
- `restart_cooldown_sec`: 重启冷却时间（秒）
- `log_level`: 日志级别 (DEBUG/INFO/WARNING/ERROR)

### 客户端菜单说明

客户端提供友好的交互式菜单，包含：

- **配置管理**: 设置目标 IP、服务端地址、查看和验证配置
- **ZeroTier 管理**: 启动/停止服务和应用、执行重启策略
- **网络功能**: 上报本机 IP、启动/停止自动治愈
- **状态查看**: 查看系统状态和网络接口信息

### 自动治愈机制

客户端的自动治愈功能会：

1. **定期 Ping 目标主机**（默认 20 秒间隔）
2. **检测连接状态**：如果无法 Ping 通目标主机
3. **执行重启策略**：
   - 停止 ZeroTier 应用
   - 停止 ZeroTier 服务  
   - 启动 ZeroTier 服务
   - 启动 ZeroTier 应用
4. **上报本机 IP**：重启后向服务端上报当前 IP
5. **冷却期**：避免频繁重启（默认 30 秒冷却）

## API 接口

服务端提供以下 REST API：

- `POST /clients/remember` - 客户端上报 IP
- `GET /clients` - 获取所有客户端信息
- `GET /clients/active` - 获取活跃客户端
- `GET /clients/stats` - 获取客户端统计
- `GET /health` - 健康检查
- `GET /config` - 获取服务端配置

## 故障排除

### 常见问题

1. **找不到 ZeroTier 服务**
   - 检查 ZeroTier One 是否已正确安装
   - 使用菜单查看网络接口信息，确认适配器名称

2. **权限问题**
   - Windows: 确保以管理员身份运行客户端
   - Linux: 确保当前用户有 sudo 权限

3. **服务端连接失败**
   - 检查防火墙设置，确保端口 5418 开放
   - 验证服务端地址配置是否正确

### 日志调试

通过菜单修改配置，启用 DEBUG 日志级别获取详细信息。

## 注意事项

- **安全性**: 服务端默认绑定 0.0.0.0，请确保在安全的网络环境中使用
- **系统权限**: 客户端需要足够权限管理系统服务
- **ZeroTier 依赖**: 必须预先安装并配置 ZeroTier One

## Todo

- 客户端实现更高级的菜单形式，如双栏：终端左边始终是菜单面板，可以输入命令；右边是输出历史（只读），可以滚动，也可以清除历史

## 许可证

此项目仅供学习和个人使用。
