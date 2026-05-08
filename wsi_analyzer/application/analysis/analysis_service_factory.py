from wsi_analyzer.app.dependency_container import container as _container, AnalysisServiceHandle


class AnalysisServiceFactory:
    create = staticmethod(_container.create_analysis_service)
