#!/usr/bin/env python3
"""
ZeroTier Reconnecter 统一启动脚本
提供简单的命令行界面来启动客户端或服务端
"""
import sys
import os
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))


def start_client():
    """启动客户端"""
    try:
        from client.app import main
        print("正在启动 ZeroTier Reconnecter 客户端...")
        main()
    except ImportError as e:
        print(f"导入客户端模块失败: {e}")
        print("请确保所有依赖已安装: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"客户端启动失败: {e}")
        sys.exit(1)


def start_server():
    """启动服务端"""
    try:
        import uvicorn
        from server.config import ServerConfig
        
        print("正在启动 ZeroTier Reconnecter 服务端...")
        
        # 加载配置
        config = ServerConfig.load()
        
        # 启动服务器
        uvicorn.run(
            "server.app:app",
            host=config.host,
            port=config.port,
            reload=False,
            log_level=config.log_level.lower()
        )
    except ImportError as e:
        print(f"导入服务端模块失败: {e}")
        print("请确保所有依赖已安装: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"服务端启动失败: {e}")
        sys.exit(1)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="ZeroTier Reconnecter - 自动化维护 ZeroTier 连接稳定性",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py client          # 启动客户端（交互式菜单）
  python main.py server          # 启动服务端
  python main.py --help          # 显示此帮助信息

快捷启动（推荐）:
  python main.py client          # 最简单的客户端启动方式
  python main.py server          # 最简单的服务端启动方式
        """
    )
    
    parser.add_argument(
        'mode',
        choices=['client', 'server'],
        help='启动模式: client (客户端) 或 server (服务端)'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='ZeroTier Reconnecter 1.0.0'
    )
    
    args = parser.parse_args()
    
    # 根据模式启动相应组件
    if args.mode == 'client':
        start_client()
    elif args.mode == 'server':
        start_server()


if __name__ == "__main__":
    main()
