import uvicorn
from .config import ServerConfig

if __name__ == "__main__":
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
