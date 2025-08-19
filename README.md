# 🌐 ZeroTier Reconnecter

> **自动化维护 ZeroTier 连接稳定性的智能跨平台解决方案**

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-26%20passed-brightgreen.svg)](tests/)

当 ZeroTier 连接不稳定时，ZeroTier Reconnecter 能够自动检测网络问题、重启服务和应用程序，并维护分布式客户端的健康状态监控。

## ✨ 功能特性

- **🌍 跨平台支持**: Windows、Linux、macOS 全平台兼容
- **🔍 智能网络识别**: 自动识别 ZeroTier 网络适配器和 IP 地址
- **⚙️ 服务管理**: 一键启动/停止/重启 ZeroTier 服务和应用
- **🔄 自动故障恢复**: 智能监控目标主机连通性，断联时自动执行修复策略
- **📋 交互式菜单**: 友好的交互式配置和管理界面
- ** 分布式监控**: 集中管理和监控所有客户端状态
- ** RESTful API**: 完整的客户端管理和状态查询接口
- **� 高级日志**: 可配置的日志级别、文件输出和自动轮转

## 🏗️ 项目架构

```
ZerotierSolver/
├── client/                      # 客户端模块
│   ├── app.py                   # 主应用逻辑和交互界面
│   ├── config.py                # 配置管理和验证
│   └── platform_utils.py       # 跨平台系统操作
├── server/                      # 服务端模块  
│   ├── app.py                   # FastAPI 应用和路由
│   ├── client_manager.py        # 线程安全的客户端状态管理
│   ├── ping_scheduler.py        # 智能 Ping 调度器
│   ├── metrics.py               # 性能指标收集
│   └── config_watcher.py        # 配置热重载监控
├── common/                      # 共享模块
│   ├── network_utils.py         # 网络工具
│   ├── logging_utils.py         # 日志系统
│   └── monitoring.py           # 性能监控
├── tests/                       # 测试套件
├── main.py                      # 统一启动入口
└── requirements.txt             # 依赖管理
```

## 🚀 快速开始

### 1️⃣ 环境准备
```bash
# 克隆项目
git clone https://github.com/3210448723/ZeroTierReconnecter.git
cd ZeroTierReconnecter

# 安装依赖
pip install -r requirements.txt

# 验证安装
python -m pytest tests/ -v
```

### 2️⃣ 启动服务端
```bash
# 推荐方式
python main.py server

# Windows 一键启动
start_server.bat

# Linux/Mac 快捷启动
./start_server.sh
```

服务端启动后，可通过以下地址访问：
- **Web界面**: http://localhost:8080/docs
- **健康检查**: http://localhost:8080/health
- **监控指标**: http://localhost:8080/metrics

### 3️⃣ 启动客户端
```bash
# 推荐方式
python main.py client

# Windows 一键启动（需要管理员权限）
start_client.bat

# Linux/Mac 快捷启动
./start_client.sh
```

**注意**: 客户端需要管理员权限来控制系统服务。

## 📖 配置与使用

### 🔧 配置文件

#### 服务端配置
```json
{
    "host": "0.0.0.0",
    "port": 8080,
    "ping_interval_sec": 30,
    "ping_timeout_sec": 5,
    "max_concurrent_pings": 10,
    "enable_api_auth": false,
    "log_level": "INFO"
}
```

#### 客户端配置
```json
{
    "server_base": "http://localhost:8080",
    "target_ip": "192.168.1.1",
    "auto_heal_enabled": true,
    "ping_interval_sec": 30,
    "log_level": "INFO"
}
```

### 🎛️ 客户端交互菜单

启动客户端后，您将看到功能丰富的交互式菜单：

```
==========================================
ZeroTier Reconnecter 客户端

配置管理:
  1) 设置目标主机 ZeroTier IP    
  2) 设置服务端地址
  3) 设置服务端API密钥
  4) 查看当前配置

ZeroTier 管理:
  8) 启动 ZeroTier 服务
  9) 停止 ZeroTier 服务
  12) 执行重启策略

网络功能:
  13) 向服务端上报本机 IP
  14) 启动自动治愈
  15) 停止自动治愈

状态查看:
  22) 查看本地系统状态
  23) 查看网络接口信息
```

### 🏥 自动治愈机制

客户端的自动治愈功能会：

1. **定期 Ping 目标主机**（默认 30 秒间隔）
2. **检测连接状态**：如果无法 Ping 通目标主机
3. **执行重启策略**：
   - 停止 ZeroTier 应用
   - 停止 ZeroTier 服务  
   - 启动 ZeroTier 服务
   - 启动 ZeroTier 应用
4. **上报本机 IP**：重启后向服务端上报当前 IP
5. **冷却期**：避免频繁重启（默认 30 秒冷却）

### 🌐 API 接口

服务端提供完整的 RESTful API：

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 服务健康检查 |
| `/clients` | GET | 获取所有客户端 |
| `/clients/remember` | POST | 客户端上报IP |
| `/clients/stats` | GET | 客户端统计信息 |
| `/config` | GET | 获取服务端配置 |
| `/metrics` | GET | Prometheus 监控指标 |

### � 日志管理

程序默认会创建日志文件：
- **客户端日志**: `~/.zerotier_reconnecter_client.log`
- **服务端日志**: `~/.zerotier_reconnecter_server.log`
- **Windows路径**: `C:\Users\用户名\.zerotier_reconnecter_*.log`

日志功能特性：
- ✅ 同时输出到控制台和文件
- ✅ 自动日志轮转（10MB文件，保留5个备份）
- ✅ UTF-8编码支持中文
- ✅ 时间戳和级别标识

**实时监控日志**：
```bash
# Windows PowerShell
Get-Content ~/.zerotier_reconnecter_client.log -Wait

# Linux/Mac
tail -f ~/.zerotier_reconnecter_client.log
```

## 🔧 故障排除

### 常见问题

1. **找不到 ZeroTier 服务**
   - 检查 ZeroTier One 是否已正确安装
   - 使用菜单查看网络接口信息，确认适配器名称

2. **权限问题**
   - Windows: 确保以管理员身份运行客户端
   - Linux: 确保当前用户有 sudo 权限

3. **服务端连接失败**
   - 检查防火墙设置，确保端口开放
   - 验证服务端地址配置是否正确

### 调试模式
启用详细日志：
```json
{
    "log_level": "DEBUG"
}
```

## 🤝 贡献指南

欢迎所有形式的贡献！

### 开发环境设置
```bash
# 克隆项目
git clone https://github.com/3210448723/ZeroTierReconnecter.git
cd ZeroTierReconnecter

# 安装开发依赖
pip install -r requirements.txt
pip install pytest black flake8

# 运行测试
python -m pytest tests/ -v
```

### 提交代码
1. Fork 项目
2. 创建功能分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 提交 Pull Request

## � 支持与反馈

- 🐛 [问题报告](https://github.com/3210448723/ZeroTierReconnecter/issues)
- 💬 [讨论区](https://github.com/3210448723/ZeroTierReconnecter/discussions)

## 💡 致谢

感谢以下项目和技术：
- [ZeroTier](https://zerotier.com/) - 优秀的 SD-WAN 解决方案
- [FastAPI](https://fastapi.tiangolo.com/) - 现代高性能 Web 框架
- [Requests](https://docs.python-requests.org/) - 简洁优雅的 HTTP 库
- [psutil](https://psutil.readthedocs.io/) - 跨平台系统监控库

## � 许可证

本项目采用 [MIT 许可证](LICENSE)。

---

⭐ 如果这个项目对您有帮助，请给我们一个 Star！
