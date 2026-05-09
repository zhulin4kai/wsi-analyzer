from wsi_analyzer.infrastructure.imaging import ImageServer
from wsi_analyzer.infrastructure.persistence import DatabaseManager


class DependencyContainer:
    def __init__(self):
        self.database = DatabaseManager()
        self.image_server = ImageServer.instance()


container = DependencyContainer()
