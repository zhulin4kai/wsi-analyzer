from wsi_analyzer.application.analysis import AnalysisServiceFactory
from wsi_analyzer.infrastructure.imaging import ImageServer
from wsi_analyzer.infrastructure.persistence import DatabaseManager


class DependencyContainer:
    def __init__(self):
        self.database = DatabaseManager()
        self.image_server = ImageServer.instance()
        self.analysis_service_factory = AnalysisServiceFactory(
            database=self.database,
            image_server=self.image_server,
        )


container = DependencyContainer()
