#!/usr/bin/env python3
"""
测试ZeroTier服务和应用分离修复
验证停止服务和停止应用的操作是否正确分离
"""

import psutil
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

from client.platform_utils import get_service_status, get_app_status
from client.config import ClientConfig

def show_zerotier_processes():
    """显示所有ZeroTier相关进程"""
    print("=== 当前ZeroTier相关进程 ===")
    found_processes = []
    
    try:
        for process in psutil.process_iter(attrs=["name", "pid", "exe"]):
            try:
                name = process.info.get("name", "").lower()
                exe_path = process.info.get("exe", "") or ""
                
                # 检查是否为ZeroTier相关进程
                zerotier_keywords = ["zerotier", "zt"]
                is_zerotier = any(keyword in name for keyword in zerotier_keywords)
                
                if is_zerotier:
                    pid = process.info['pid']
                    process_name = process.info['name']
                    
                    # 判断进程类型
                    process_type = "未知"
                    if "desktop_ui" in name:
                        process_type = "GUI应用"
                    elif "one_x64" in name or "one_x86" in name:
                        process_type = "服务进程"
                    elif "one.exe" in name:
                        if "programdata" in exe_path.lower():
                            process_type = "服务进程"
                        elif "program files" in exe_path.lower():
                            process_type = "GUI应用"
                        else:
                            process_type = "未确定"
                    
                    found_processes.append({
                        'name': process_name,
                        'pid': pid,
                        'path': exe_path,
                        'type': process_type
                    })
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        print(f"检查进程时出错: {e}")
    
    if found_processes:
        for proc in found_processes:
            print(f"  [{proc['type']}] {proc['name']} (PID: {proc['pid']})")
            if proc['path']:
                print(f"      路径: {proc['path']}")
            print()
    else:
        print("  未找到ZeroTier相关进程")
    
    return found_processes

def test_status_functions():
    """测试状态检查函数"""
    print("=== 测试状态检查函数 ===")
    
    try:
        config = ClientConfig.load()
        
        service_status = get_service_status(config)
        app_status = get_app_status()
        
        print(f"ZeroTier服务状态: {service_status}")
        print(f"ZeroTier应用状态: {app_status}")
        
    except Exception as e:
        print(f"状态检查出错: {e}")

def test_process_classification():
    """测试进程分类逻辑"""
    print("=== 测试进程分类逻辑 ===")
    
    # 模拟测试用例
    test_cases = [
        {
            'name': 'zerotier-one_x64.exe',
            'path': 'C:\\ProgramData\\ZeroTier\\One\\zerotier-one_x64.exe',
            'expected_type': '服务进程'
        },
        {
            'name': 'zerotier_desktop_ui.exe', 
            'path': 'C:\\Program Files (x86)\\ZeroTier\\One\\zerotier_desktop_ui.exe',
            'expected_type': 'GUI应用'
        },
        {
            'name': 'ZeroTier One.exe',
            'path': 'C:\\Program Files\\ZeroTier\\One\\ZeroTier One.exe',
            'expected_type': 'GUI应用'
        }
    ]
    
    for case in test_cases:
        name = case['name'].lower()
        path = case['path'].lower()
        
        # 模拟服务进程识别逻辑
        is_service = False
        service_keywords = ["zerotier-one_x64.exe", "zerotier-one_x86.exe", "zerotier-one.exe"]
        for keyword in service_keywords:
            if keyword in name:
                service_path_indicators = ["programdata", "system32", "windows"]
                if any(indicator in path for indicator in service_path_indicators):
                    is_service = True
                    break
        
        # 模拟GUI应用识别逻辑
        is_gui = False
        gui_names = ["zerotier one.exe", "zerotier_desktop_ui.exe"]
        for gui_name in gui_names:
            if gui_name in name:
                service_paths = ["programdata", "system32", "windows"]
                if not any(service_path in path for service_path in service_paths):
                    is_gui = True
                    break
        
        actual_type = "未知"
        if is_service:
            actual_type = "服务进程"
        elif is_gui:
            actual_type = "GUI应用"
        
        status = "✅" if actual_type == case['expected_type'] else "❌"
        print(f"{status} {case['name']}")
        print(f"    路径: {case['path']}")
        print(f"    预期: {case['expected_type']}, 实际: {actual_type}")
        print()

def main():
    """主函数"""
    print("开始测试ZeroTier服务和应用分离修复...")
    print()
    
    # 显示当前进程状态
    show_zerotier_processes()
    print()
    
    # 测试状态检查函数
    test_status_functions()
    print()
    
    # 测试进程分类逻辑
    test_process_classification()
    
    print("测试完成！")
    print()
    print("现在您可以测试以下功能:")
    print("1. 运行客户端，选择菜单 '11 - 停止 ZeroTier 应用' (应该只停止GUI，不影响服务)")
    print("2. 运行客户端，选择菜单 '9 - 停止 ZeroTier 服务' (应该只停止服务，不影响GUI)")

if __name__ == "__main__":
    main()
