"""
高级客户端界面 - 双栏终端模式

功能说明：
- 左栏：交互式菜单面板，支持命令输入
- 右栏：只读输出历史，支持滚动和清除
- 实时状态显示
- 增强的用户体验

注意：这是一个高级功能，目前处于开发阶段。
如需使用完整功能，请使用标准客户端 app.py
"""

from .app import main as client_main
from .config import ClientConfig
import logging


class AdvancedClient:
    """高级客户端界面 - 双栏模式（开发中）"""
    
    def __init__(self):
        self.config = ClientConfig.load()
        
    def run(self):
        """运行高级界面"""
        print("=" * 60)
        print("ZeroTier Solver 高级界面")
        print("=" * 60)
        print()
        print("注意：高级双栏界面功能正在开发中")
        print("当前版本将回退到标准界面")
        print()
        print("计划功能：")
        print("- 左栏：交互式菜单面板")
        print("- 右栏：实时输出历史")
        print("- 增强的状态显示")
        print()
        
        # 回退到标准客户端
        print("启动标准客户端...")
        client_main()


def main():
    """主入口函数"""
    try:
        client = AdvancedClient()
        client.run()
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
    except Exception as e:
        logging.error(f"高级客户端运行错误: {e}")
        print(f"运行错误: {e}")


if __name__ == "__main__":
    main()