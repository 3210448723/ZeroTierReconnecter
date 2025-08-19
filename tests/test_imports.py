#!/usr/bin/env python3
"""
测试所有模块导入是否正常工作
"""

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_import(module_name, description):
    try:
        exec(f"import {module_name}")
        print(f"✅ {description}: 导入成功")
        return True
    except Exception as e:
        print(f"❌ {description}: 导入失败 - {e}")
        return False

def main():
    print("=== 模块导入测试 ===\n")
    
    results = []
    
    # 测试基础模块
    results.append(test_import("common.network_utils", "网络工具模块"))
    results.append(test_import("server.config", "服务器配置模块"))
    results.append(test_import("server.client_manager", "客户端管理器"))
    results.append(test_import("server.ping_scheduler", "Ping调度器"))
    results.append(test_import("server.metrics", "指标收集器"))
    results.append(test_import("client.config", "客户端配置模块"))
    results.append(test_import("client.platform_utils", "平台工具"))
    
    # 测试主应用模块
    try:
        import server.app
        print("✅ 服务器应用模块: 导入成功")
        results.append(True)
    except Exception as e:
        print(f"❌ 服务器应用模块: 导入失败 - {e}")
        results.append(False)
        
    try:
        import client.app
        print("✅ 客户端应用模块: 导入成功")
        results.append(True)
    except Exception as e:
        print(f"❌ 客户端应用模块: 导入失败 - {e}")
        results.append(False)
    
    print(f"\n=== 测试结果 ===")
    success_count = sum(results)
    total_count = len(results)
    print(f"成功: {success_count}/{total_count}")
    
    if success_count == total_count:
        print("🎉 所有模块导入测试通过！")
        return True
    else:
        print("⚠️  部分模块导入失败，需要检查依赖关系")
        return False

if __name__ == "__main__":
    main()
