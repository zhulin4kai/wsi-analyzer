from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class AnalysisSession:
    def __init__(self, config: AnalysisConfig):
        self.config = config
        self._cancelled = False
        self._valid_coords: list[PatchCoordinate] = []
        self._processed_count = 0

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        self._cancelled = True

    @property
    def valid_coords(self) -> list[PatchCoordinate]:
        return self._valid_coords

    @valid_coords.setter
    def valid_coords(self, value: list[PatchCoordinate]):
        self._valid_coords = value

    @property
    def processed_count(self) -> int:
        return self._processed_count

    @processed_count.setter
    def processed_count(self, value: int):
        self._processed_count = value

    @property
    def remaining_coords(self) -> list[PatchCoordinate]:
        return self._valid_coords[self._processed_count:]
