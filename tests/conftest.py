#!/usr/bin/env python3
"""
pytest配置文件和公共测试工具
"""
import sys
from pathlib import Path

import pytest

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root():
    """返回项目根目录路径"""
    return PROJECT_ROOT


@pytest.fixture
def temp_config_dir(tmp_path):
    """创建临时配置目录"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def mock_zerotier_env(monkeypatch, tmp_path):
    """模拟ZeroTier环境"""
    # 创建模拟的ZeroTier二进制文件
    zerotier_bin = tmp_path / "zerotier-one"
    zerotier_bin.write_text("#!/bin/bash\necho 'mock zerotier'")
    zerotier_bin.chmod(0o755)
    
    # 设置环境变量
    monkeypatch.setenv("PATH", f"{tmp_path}:{monkeypatch.getenv('PATH', '')}")
    
    return {
        "bin_path": str(zerotier_bin),
        "temp_dir": str(tmp_path)
    }


def pytest_configure(config):
    """pytest配置钩子"""
    # 添加自定义标记
    config.addinivalue_line(
        "markers", "integration: 标记集成测试"
    )
    config.addinivalue_line(
        "markers", "slow: 标记慢速测试"
    )
    config.addinivalue_line(
        "markers", "unit: 标记单元测试"
    )


def pytest_collection_modifyitems(config, items):
    """修改测试收集项"""
    for item in items:
        # 为所有测试添加单元测试标记（除非已有其他标记）
        if not any(mark.name in ['integration', 'slow'] for mark in item.iter_markers()):
            item.add_marker(pytest.mark.unit)
