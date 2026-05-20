from typing import Optional

from wsi_analyzer.config import config
from wsi_analyzer.domain.analysis import PatchPlanner, ROIPlanner
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.domain.slide.slide_read_port import SlideReadPort
from wsi_analyzer.infrastructure.logging import logger


class AnalysisCoordinateService:
    def __init__(self, mask_generator, geometry, slide_port: SlideReadPort, device: str = "cpu"):
        self._mask_generator = mask_generator
        self._geometry = geometry
        self._slide_port = slide_port
        self._device = device

    def build_full_slide_coords(self) -> list[PatchCoordinate]:
        level, dim, ds = self._slide_port.get_level_info(3)
        mask = self._mask_generator.generate(self._slide_port.read_thumbnail_rgb(level))
        if hasattr(self._mask_generator, "last_stats"):
            stats = self._mask_generator.last_stats
            logger.info(
                "[mask/full] tissue_ratio=%.4f components=%s",
                stats.get("mask_tissue_ratio", 0.0),
                stats.get("component_count", 0),
            )

        planner = PatchPlanner(self._geometry)
        coords = planner.plan(
            solid_mask=mask,
            level_0_dim=self._slide_port.level0_dimensions,
            downsample_factor=ds,
        )
        if self._device == "cpu" and getattr(config, "AI_COARSE_TO_FINE_ENABLED", True):
            coords = self._coarse_to_fine_reduce(coords)
        return self._apply_patch_budget(coords, roi_mode=False)

    def build_roi_coords(self, roi_bbox: tuple) -> list[PatchCoordinate]:
        level, dim, ds = self._slide_port.get_level_info(3)
        mask = self._mask_generator.generate(self._slide_port.read_thumbnail_rgb(level))
        if hasattr(self._mask_generator, "last_stats"):
            stats = self._mask_generator.last_stats
            logger.info(
                "[mask/roi] tissue_ratio=%.4f components=%s",
                stats.get("mask_tissue_ratio", 0.0),
                stats.get("component_count", 0),
            )
        planner = ROIPlanner(self._geometry)
        coords = planner.plan(
            roi_bbox=roi_bbox,
            level_0_dim=self._slide_port.level0_dimensions,
            solid_mask=mask,
            downsample_factor=ds,
        )
        return self._apply_patch_budget(coords, roi_mode=True)

    def build_coords(self, roi_bbox: Optional[tuple] = None) -> list[PatchCoordinate]:
        if roi_bbox:
            return self.build_roi_coords(roi_bbox)
        return self.build_full_slide_coords()

    def _coarse_to_fine_reduce(self, coords: list[PatchCoordinate]) -> list[PatchCoordinate]:
        if not coords:
            return []
        stride_mult = max(1, int(getattr(config, "AI_COARSE_STRIDE_MULTIPLIER", 2)))
        keep_ratio = float(getattr(config, "AI_COARSE_KEEP_RATIO", 0.35))
        coarse = coords[::stride_mult]
        keep_n = max(1, int(len(coords) * keep_ratio))
        return (coarse + coords[:keep_n])[:max(len(coarse), keep_n)]

    def _apply_patch_budget(self, coords: list[PatchCoordinate], roi_mode: bool) -> list[PatchCoordinate]:
        if self._device != "cpu":
            return coords
        max_patches = int(
            getattr(config, "AI_MAX_PATCHES_ROI", 8000) if roi_mode
            else getattr(config, "AI_MAX_PATCHES_CPU", 20000)
        )
        if self._geometry and len(coords) > max_patches:
            logger.warning("patch budget applied: %d -> %d", len(coords), max_patches)
            return coords[:max_patches]
        return coords
