import time
from typing import Optional

from tqdm import tqdm

from wsi_analyzer.domain.analysis import PatchPlanner, ROIPlanner
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.domain.slide.slide_read_port import SlideReadPort
from wsi_analyzer.infrastructure.logging import logger


class AnalysisCoordinateService:
    def __init__(self, mask_generator, geometry, slide_port: SlideReadPort):
        self._mask_generator = mask_generator
        self._geometry = geometry
        self._slide_port = slide_port

    def build_full_slide_coords(self, progress_callback=None) -> list[PatchCoordinate]:
        total_start = time.perf_counter()
        pbar = tqdm(total=3, desc="组织掩膜/全片", unit="步", colour="green")
        level, dim, ds = self._slide_port.get_level_info(3)
        _emit_stage_progress(progress_callback, "tissue_mask", 0, 3, "读取缩略图")
        read_start = time.perf_counter()
        thumbnail = self._slide_port.read_thumbnail_rgb(level)
        read_seconds = time.perf_counter() - read_start
        pbar.update(1)

        _emit_stage_progress(progress_callback, "tissue_mask", 1, 3, "生成组织掩膜")
        mask_start = time.perf_counter()
        mask = self._mask_generator.generate(thumbnail)
        mask_seconds = time.perf_counter() - mask_start
        pbar.update(1)

        if hasattr(self._mask_generator, "last_stats"):
            stats = self._mask_generator.last_stats
            logger.info(
                "[mask/full] tissue_ratio=%.4f components=%s",
                stats.get("mask_tissue_ratio", 0.0),
                stats.get("component_count", 0),
            )
        else:
            stats = {}

        _emit_stage_progress(progress_callback, "patch_planning", 2, 3, "规划有效 patch")
        planner = PatchPlanner(self._geometry)
        coords = planner.plan(
            solid_mask=mask,
            level_0_dim=self._slide_port.level0_dimensions,
            downsample_factor=ds,
        )
        pbar.update(1)
        pbar.close()
        _emit_stage_progress(progress_callback, "patch_planning", 3, 3, "patch 规划完成")
        _log_coord_summary(
            mode="全片检测",
            level=level,
            downsample=ds,
            thumbnail_shape=getattr(thumbnail, "shape", None),
            mask_stats=stats,
            plan_stats=planner.last_stats,
            read_seconds=read_seconds,
            mask_seconds=mask_seconds,
            total_seconds=time.perf_counter() - total_start,
        )
        return coords

    def build_roi_coords(self, roi_bbox: tuple, progress_callback=None) -> list[PatchCoordinate]:
        total_start = time.perf_counter()
        pbar = tqdm(total=3, desc="组织掩膜/ROI", unit="步", colour="green")
        level, dim, ds = self._slide_port.get_level_info(3)
        _emit_stage_progress(progress_callback, "tissue_mask", 0, 3, "读取缩略图")
        read_start = time.perf_counter()
        thumbnail = self._slide_port.read_thumbnail_rgb(level)
        read_seconds = time.perf_counter() - read_start
        pbar.update(1)

        _emit_stage_progress(progress_callback, "tissue_mask", 1, 3, "生成组织掩膜")
        mask_start = time.perf_counter()
        mask = self._mask_generator.generate(thumbnail)
        mask_seconds = time.perf_counter() - mask_start
        pbar.update(1)

        if hasattr(self._mask_generator, "last_stats"):
            stats = self._mask_generator.last_stats
            logger.info(
                "[mask/roi] tissue_ratio=%.4f components=%s",
                stats.get("mask_tissue_ratio", 0.0),
                stats.get("component_count", 0),
            )
        else:
            stats = {}
        _emit_stage_progress(progress_callback, "patch_planning", 2, 3, "规划 ROI patch")
        planner = ROIPlanner(self._geometry)
        coords = planner.plan(
            roi_bbox=roi_bbox,
            level_0_dim=self._slide_port.level0_dimensions,
            solid_mask=mask,
            downsample_factor=ds,
        )
        pbar.update(1)
        pbar.close()
        _emit_stage_progress(progress_callback, "patch_planning", 3, 3, "ROI patch 规划完成")
        _log_coord_summary(
            mode="ROI 检测",
            level=level,
            downsample=ds,
            thumbnail_shape=getattr(thumbnail, "shape", None),
            mask_stats=stats,
            plan_stats=planner.last_stats,
            read_seconds=read_seconds,
            mask_seconds=mask_seconds,
            total_seconds=time.perf_counter() - total_start,
            roi_bbox=roi_bbox,
        )
        return coords

    def build_coords(
        self, roi_bbox: Optional[tuple] = None, progress_callback=None
    ) -> list[PatchCoordinate]:
        if roi_bbox:
            return self.build_roi_coords(roi_bbox, progress_callback=progress_callback)
        return self.build_full_slide_coords(progress_callback=progress_callback)


def _emit_stage_progress(callback, stage: str, completed: int, total: int, message: str):
    if callback:
        callback(stage, completed, total, message)


def _log_coord_summary(
    mode: str,
    level: int,
    downsample: float,
    thumbnail_shape,
    mask_stats: dict,
    plan_stats: dict,
    read_seconds: float,
    mask_seconds: float,
    total_seconds: float,
    roi_bbox=None,
):
    h = thumbnail_shape[0] if thumbnail_shape is not None else "未知"
    w = thumbnail_shape[1] if thumbnail_shape is not None else "未知"
    roi_line = f"ROI 范围               {roi_bbox}\n" if roi_bbox else ""
    logger.info(
        "\n========== 组织掩膜与 Patch 规划 ==========\n"
        "模式                   %s\n"
        "%s"
        "掩膜层级               level=%s, downsample=%.2f\n"
        "缩略图尺寸             %s x %s\n"
        "读取缩略图耗时         %.3fs\n"
        "组织分割耗时           %.3fs\n"
        "积分图构建耗时         %.3fs\n"
        "候选窗口数量           %s\n"
        "实际扫描窗口           %s\n"
        "有效 patch 数          %s\n"
        "组织占比               %.4f\n"
        "组织连通域             %s\n"
        "patch 规划耗时         %.3fs\n"
        "阶段总耗时             %.3fs\n"
        "==========================================",
        mode,
        roi_line,
        level,
        downsample,
        w,
        h,
        read_seconds,
        mask_seconds,
        plan_stats.get("index_seconds", 0.0),
        plan_stats.get("candidate_count", 0),
        plan_stats.get("scanned_count", 0),
        plan_stats.get("patch_count", 0),
        mask_stats.get("mask_tissue_ratio", 0.0),
        mask_stats.get("component_count", 0),
        plan_stats.get("total_seconds", 0.0),
        total_seconds,
    )
