#!/usr/bin/env python3
"""
测试导入问题是否修复 - 使用pytest框架
"""
import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))


class TestImports:
    """导入测试类"""
    
    def test_client_imports(self):
        """测试客户端导入"""
        # 测试核心模块
        from client.app import ClientApp
        from client.config import ClientConfig
        from client.platform_utils import ping, get_zerotier_ips
        
        # 验证类型
        assert callable(ClientApp)
        assert callable(ClientConfig)
        assert callable(ping)
        assert callable(get_zerotier_ips)

    def test_server_imports(self):
        """测试服务端导入"""
        from server.config import ServerConfig
        from server.app import app  # FastAPI应用
        from server.client_manager import ThreadSafeClientManager
        from server.ping_scheduler import OptimizedPingScheduler
        
        # 验证类型
        assert callable(ServerConfig)
        assert hasattr(app, 'get')  # FastAPI应用应该有get方法
        assert callable(ThreadSafeClientManager)
        assert callable(OptimizedPingScheduler)

    def test_common_imports(self):
        """测试公共模块导入"""
        from common.network_utils import ping, validate_ip_address
        from common.logging_utils import setup_unified_logging
        
        # 验证函数存在
        assert callable(ping)
        assert callable(validate_ip_address)
        assert callable(setup_unified_logging)

    @pytest.mark.integration
    def test_app_instantiation(self):
        """测试应用实例化（集成测试）"""
        from client.config import ClientConfig
        from client.app import ClientApp
        
        # 创建配置
        config = ClientConfig()
        
        # 实例化应用（不应抛出异常）
        app = ClientApp()
        assert app is not None
        assert hasattr(app, 'config')


if __name__ == "__main__":
    # 支持直接运行
    pytest.main([__file__, "-v"])
