#!/usr/bin/env python3
"""
测试修复的功能
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

def test_reset_config():
    """测试配置重置功能"""
    print("=== 测试配置重置功能 ===")
    try:
        from common.reset_config import reset_client_config
        
        # 创建一个测试备份文件来测试冲突处理
        from client.config import ClientConfig
        config_path = ClientConfig.get_config_path()
        backup_path = config_path.with_suffix('.json.backup')
        
        # 如果备份文件存在，创建测试内容
        if backup_path.exists():
            print(f"发现已存在的备份文件: {backup_path}")
        
        print("测试重置配置（不保留设置）...")
        success = reset_client_config(preserve_settings=False)
        print(f"重置结果: {'成功' if success else '失败'}")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_zerotier_paths():
    """测试ZeroTier路径发现"""
    print("\n=== 测试ZeroTier路径发现 ===")
    try:
        from client.platform_utils import discover_zerotier_paths, find_executable
        from client.config import ClientConfig
        
        # 测试路径发现
        paths = discover_zerotier_paths()
        print("发现的路径:")
        for key, value in paths.items():
            print(f"  {key}: {value}")
        
        # 测试配置中的路径
        config = ClientConfig()
        print(f"\n配置中的服务路径: {config.zerotier_bin_paths}")
        print(f"配置中的GUI路径: {config.zerotier_gui_paths}")
        print(f"配置中的服务名称: {config.zerotier_service_names}")
        
        # 测试可执行文件查找
        exe_path = find_executable(config.zerotier_bin_paths or [])
        print(f"\n找到的可执行文件: {exe_path}")
        
        gui_path = find_executable(config.zerotier_gui_paths or [])
        print(f"找到的GUI文件: {gui_path}")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

def test_service_operations():
    """测试服务操作（仅检查状态，不实际操作）"""
    print("\n=== 测试服务状态检查 ===")
    try:
        from client.platform_utils import get_service_status, get_app_status
        from client.config import ClientConfig
        
        config = ClientConfig()
        
        service_status = get_service_status(config)
        print(f"ZeroTier 服务状态: {service_status}")
        
        app_status = get_app_status()
        print(f"ZeroTier 应用状态: {app_status}")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("开始测试修复的功能...\n")
    
    test_reset_config()
    test_zerotier_paths() 
    test_service_operations()
    
    print("\n测试完成！")
