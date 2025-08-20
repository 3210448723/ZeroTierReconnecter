#!/usr/bin/env python3
"""
自动治愈调试脚本
快速诊断自动治愈功能是否正常工作
"""

import time
import logging
from client.app import ClientApp


def quick_debug():
    """快速调试自动治愈状态"""
    print("="*60)
    print("ZeroTier Reconnecter 自动治愈快速诊断")
    print("="*60)
    
    try:
        # 创建客户端应用实例
        app = ClientApp()
        
        # 显示基本状态
        print("\n1. 基本配置检查:")
        print(f"   目标IP: {app.config.target_ip or '未设置'}")
        print(f"   服务端地址: {app.config.server_base}")
        print(f"   自动治愈启用: {app.config.auto_heal_enabled}")
        print(f"   Ping间隔: {app.config.ping_interval_sec}秒")
        
        # 检查自动治愈状态
        print("\n2. 自动治愈状态:")
        is_running = app._bg_thread and app._bg_thread.is_alive()
        print(f"   运行状态: {'运行中' if is_running else '已停止'}")
        print(f"   失败计数: {app._restart_failure_count}/{app._max_restart_failures}")
        print(f"   停止信号: {'已设置' if app._stop_event.is_set() else '未设置'}")
        
        # 网络连通性测试
        if app.config.target_ip:
            print(f"\n3. 网络连通性测试:")
            print(f"   正在测试 {app.config.target_ip}...")
            
            try:
                from client.platform_utils import ping
                start_time = time.time()
                reachable = ping(app.config.target_ip, app.config.ping_timeout_sec)
                ping_time = (time.time() - start_time) * 1000
                
                if reachable:
                    print(f"   ✓ 目标主机可达 (用时: {ping_time:.1f}ms)")
                else:
                    print(f"   ✗ 目标主机不可达 (用时: {ping_time:.1f}ms)")
                    print("   这可能是自动治愈停止工作的原因!")
            except Exception as e:
                print(f"   ✗ Ping测试异常: {e}")
        else:
            print(f"\n3. 网络连通性测试:")
            print(f"   ⚠️ 未设置目标IP，无法进行测试")
        
        # 服务端连接测试
        print(f"\n4. 服务端连接测试:")
        print(f"   正在测试 {app.config.server_base}...")
        
        try:
            start_time = time.time()
            health_ok = app.check_server_health(silent=True)
            api_time = (time.time() - start_time) * 1000
            
            if health_ok:
                print(f"   ✓ 服务端连接正常 (用时: {api_time:.1f}ms)")
            else:
                print(f"   ✗ 服务端连接失败 (用时: {api_time:.1f}ms)")
        except Exception as e:
            print(f"   ✗ 服务端测试异常: {e}")
        
        # 诊断结论和建议
        print(f"\n5. 诊断结论:")
        
        if not app.config.auto_heal_enabled:
            print(f"   ⚠️ 自动治愈在配置中被禁用")
            print(f"      建议: 在客户端中启用自动治愈")
        
        if not app.config.target_ip:
            print(f"   ⚠️ 未设置目标IP")
            print(f"      建议: 使用客户端菜单选项1设置服务端设备IP")
        
        if app._restart_failure_count >= app._max_restart_failures:
            print(f"   ⚠️ 重启失败次数过多，自动治愈已暂停")
            print(f"      建议: 使用客户端菜单选项16重置失败计数")
        
        if not is_running and app.config.auto_heal_enabled and app.config.target_ip:
            print(f"   ⚠️ 自动治愈未运行但配置正常")
            print(f"      建议: 使用客户端菜单选项14启动自动治愈")
        
        if (is_running and app.config.auto_heal_enabled and app.config.target_ip and 
            app._restart_failure_count < app._max_restart_failures):
            print(f"   ✓ 自动治愈配置和状态正常")
            print(f"      如果仍有问题，请检查日志文件:")
            print(f"      {app.config.log_file}")
        
        # 清理资源
        app.cleanup()
        
    except Exception as e:
        print(f"\n诊断过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n" + "="*60)
    print("诊断完成")
    print("如需详细调试，请运行客户端并使用选项25")
    print("="*60)


if __name__ == "__main__":
    quick_debug()
