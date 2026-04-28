from .ai_engine import WSIAnalyzer
from .image_server import ImageServer, SlideMetadata
from .slide_engine import (
    WSIDataEngine,  # 内部实现；外部代码应通过 ImageServer.acquire/release_engine 访问引擎
)
