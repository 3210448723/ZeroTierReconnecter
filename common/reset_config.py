#!/usr/bin/env python3
"""
ZeroTier Reconnecter 配置重置工具
提供客户端和服务端配置重置功能
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))


def reset_client_config(preserve_settings=True):
    """
    重置客户端配置
    
    Args:
        preserve_settings: 是否保留用户设置（如目标IP、服务端地址等）
    """
    try:
        from client.config import ClientConfig
        
        config_path = ClientConfig.get_config_path()
        print(f"客户端配置文件路径: {config_path}")
        
        # 保存用户设置
        old_config = None
        if preserve_settings and config_path.exists():
            try:
                old_config = ClientConfig.load()
                print("已读取现有用户设置")
            except Exception as e:
                print(f"读取现有配置失败: {e}")
                old_config = None
        
        # 备份现有配置
        if config_path.exists():
            backup_path = config_path.with_suffix('.json.backup')
            # 如果备份文件已存在，先删除
            if backup_path.exists():
                backup_path.unlink()
                print(f"已删除旧备份文件: {backup_path}")
            config_path.rename(backup_path)
            print(f"已备份现有配置到: {backup_path}")
        
        # 创建新的默认配置
        config = ClientConfig()
        
        # 恢复用户设置
        if preserve_settings and old_config:
            preserved_fields = [
                'server_base', 'api_key', 'target_ip', 
                'ping_interval_sec', 'restart_cooldown_sec', 'ping_timeout_sec'
            ]
            for field in preserved_fields:
                old_value = getattr(old_config, field, None)
                if old_value:  # 只恢复非空值
                    setattr(config, field, old_value)
            print("已恢复用户设置")
        
        config.save()
        
        print(f"✅ 客户端配置已重置")
        print(f"  - 日志文件: {config.log_file}")
        print(f"  - 配置文件: {config_path}")
        if preserve_settings:
            print("  - 用户设置已保留")
        return True
        
    except Exception as e:
        print(f"❌ 重置客户端配置失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return False


def reset_server_config(preserve_settings=True):
    """
    重置服务端配置
    
    Args:
        preserve_settings: 是否保留用户设置（如端口、API密钥等）
    """
    try:
        from server.config import ServerConfig
        
        config_path = ServerConfig.get_config_path()
        print(f"服务端配置文件路径: {config_path}")
        
        # 保存用户设置
        old_config = None
        if preserve_settings and config_path.exists():
            try:
                old_config = ServerConfig.load()
                print("已读取现有用户设置")
            except Exception as e:
                print(f"读取现有配置失败: {e}")
                old_config = None
        
        # 备份现有配置
        if config_path.exists():
            backup_path = config_path.with_suffix('.json.backup')
            # 如果备份文件已存在，先删除
            if backup_path.exists():
                backup_path.unlink()
                print(f"已删除旧备份文件: {backup_path}")
            config_path.rename(backup_path)
            print(f"已备份现有配置到: {backup_path}")
        
        # 创建新的默认配置
        config = ServerConfig()
        
        # 恢复用户设置
        if preserve_settings and old_config:
            preserved_fields = [
                'host', 'port', 'api_key', 'enable_api_auth',
                'ping_interval_sec', 'ping_timeout_sec', 'max_concurrent_pings'
            ]
            for field in preserved_fields:
                old_value = getattr(old_config, field, None)
                if old_value is not None:  # 保留所有非None值，包括False和0
                    setattr(config, field, old_value)
            print("已恢复用户设置")
        
        config.save()
        
        print(f"✅ 服务端配置已重置")
        print(f"  - 日志文件: {config.log_file}")
        print(f"  - 配置文件: {config_path}")
        print(f"  - 数据文件: {config.data_file}")
        if preserve_settings:
            print("  - 用户设置已保留")
        return True
        
    except Exception as e:
        print(f"❌ 重置服务端配置失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return False


def show_current_configs():
    """显示当前配置信息"""
    print("=" * 60)
    print("当前配置文件状态")
    print("=" * 60)
    
    # 客户端配置
    try:
        from client.config import ClientConfig
        client_path = ClientConfig.get_config_path()
        print(f"客户端配置文件: {client_path}")
        print(f"  存在: {'是' if client_path.exists() else '否'}")
        if client_path.exists():
            try:
                config = ClientConfig.load()
                print(f"  服务端地址: {config.server_base}")
                print(f"  目标IP: {config.target_ip or '未设置'}")
                print(f"  日志文件: {config.log_file}")
                print(f"  日志级别: {config.log_level}")
            except Exception as e:
                print(f"  读取失败: {e}")
    except Exception as e:
        print(f"客户端配置检查失败: {e}")
    
    print()
    
    # 服务端配置
    try:
        from server.config import ServerConfig
        server_path = ServerConfig.get_config_path()
        print(f"服务端配置文件: {server_path}")
        print(f"  存在: {'是' if server_path.exists() else '否'}")
        if server_path.exists():
            try:
                config = ServerConfig.load()
                print(f"  监听地址: {config.host}:{config.port}")
                print(f"  API认证: {'已启用' if config.enable_api_auth else '未启用'}")
                print(f"  日志文件: {config.log_file}")
                print(f"  日志级别: {config.log_level}")
                print(f"  数据文件: {config.data_file}")
            except Exception as e:
                print(f"  读取失败: {e}")
    except Exception as e:
        print(f"服务端配置检查失败: {e}")


def interactive_reset():
    """交互式重置"""
    print("ZeroTier Reconnecter 配置重置工具")
    print("=" * 60)
    
    # 显示当前状态
    show_current_configs()
    
    print("\n" + "=" * 60)
    print("重置选项:")
    print("1) 重置客户端配置 (保留用户设置)")
    print("2) 重置服务端配置 (保留用户设置)")
    print("3) 重置所有配置 (保留用户设置)")
    print("4) 完全重置客户端配置 (不保留设置)")
    print("5) 完全重置服务端配置 (不保留设置)")
    print("6) 完全重置所有配置 (不保留设置)")
    print("7) 仅查看当前配置状态")
    print("0) 退出")
    
    while True:
        try:
            choice = input("\n请选择操作 (0-7): ").strip()
            
            if choice == "0":
                print("已取消操作")
                return
            elif choice == "1":
                print("\n重置客户端配置 (保留用户设置)...")
                reset_client_config(preserve_settings=True)
                break
            elif choice == "2":
                print("\n重置服务端配置 (保留用户设置)...")
                reset_server_config(preserve_settings=True)
                break
            elif choice == "3":
                print("\n重置所有配置 (保留用户设置)...")
                client_ok = reset_client_config(preserve_settings=True)
                server_ok = reset_server_config(preserve_settings=True)
                print(f"\n重置结果: 客户端{'成功' if client_ok else '失败'}, 服务端{'成功' if server_ok else '失败'}")
                break
            elif choice == "4":
                confirm = input("确认完全重置客户端配置？这将删除所有用户设置 (y/N): ").strip().lower()
                if confirm == 'y':
                    print("\n完全重置客户端配置...")
                    reset_client_config(preserve_settings=False)
                    break
                else:
                    print("已取消操作")
            elif choice == "5":
                confirm = input("确认完全重置服务端配置？这将删除所有用户设置 (y/N): ").strip().lower()
                if confirm == 'y':
                    print("\n完全重置服务端配置...")
                    reset_server_config(preserve_settings=False)
                    break
                else:
                    print("已取消操作")
            elif choice == "6":
                confirm = input("确认完全重置所有配置？这将删除所有用户设置 (y/N): ").strip().lower()
                if confirm == 'y':
                    print("\n完全重置所有配置...")
                    client_ok = reset_client_config(preserve_settings=False)
                    server_ok = reset_server_config(preserve_settings=False)
                    print(f"\n重置结果: 客户端{'成功' if client_ok else '失败'}, 服务端{'成功' if server_ok else '失败'}")
                    break
                else:
                    print("已取消操作")
            elif choice == "7":
                show_current_configs()
            else:
                print("无效选择，请输入 0-7")
        except KeyboardInterrupt:
            print("\n\n检测到 Ctrl+C，退出程序")
            return
        except Exception as e:
            print(f"操作出错: {e}")


if __name__ == "__main__":
    interactive_reset()
