from dataclasses import dataclass
import logging

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceGeometry:
    """Unified spatial contract for the entire inference pipeline.

    Every patch is defined as:
      - A Level-0 window of level0_window_size x level0_window_size pixels
        starting at (x, y) in WSI Level-0 coordinates.
      - Read from OpenSlide at read_level / read_downsample.
      - Resized to model_input_size x model_input_size before feeding to YOLO.
      - Model local bbox output mapped back to Level-0 by
        local_to_level0_scale = level0_window_size / model_input_size.

    Fields:
        model_input_size:   Side length (pixels) of the image tensor fed to YOLO.
        target_mpp:         Model training resolution in microns/pixel.
        slide_mpp:          WSI native resolution in microns/pixel (from metadata).
                            May be None for slides without calibration.
        level0_window_size: Side length (pixels) the patch covers on Level-0.
                            Computed as round(model_input_size * target_mpp / slide_mpp)
                            when slide_mpp is available, otherwise model_input_size.
        level0_stride:      Step size (pixels) between consecutive patches on Level-0.
        read_level:         OpenSlide pyramid level used for read_region().
        read_downsample:    Downsample factor of read_level relative to Level-0.
    """

    model_input_size: int
    target_mpp: float
    slide_mpp: float | None
    level0_window_size: int
    level0_stride: int
    read_level: int
    read_downsample: float

    @property
    def local_to_level0_scale(self) -> float:
        """Ratio to map model-local pixel coords to Level-0 coords."""
        return self.level0_window_size / self.model_input_size

    @classmethod
    def from_config_and_slide(
        cls,
        model_input_size: int,
        target_mpp: float,
        level0_stride: int,
        slide_mpp: float | None,
        objective_power: float | None,
        read_level: int,
        read_downsample: float,
    ) -> "InferenceGeometry":
        """
        Factory: assemble geometry from config values and WSI metadata.

        MPP resolution priority:
          1. slide_mpp from WSI metadata (most reliable).
          2. Estimated from objective_power: 10.0 / objective_power.
          3. Degenerate 1:1 fallback (level0_window_size = model_input_size).
        """
        if slide_mpp is None or slide_mpp <= 0:
            if objective_power is not None and objective_power > 0:
                estimated = 10.0 / objective_power
                _logger.warning(
                    "slide_mpp unavailable, estimated MPP=%.3f from "
                    "objective_power=%.1fx", estimated, objective_power,
                )
                slide_mpp = estimated
            else:
                _logger.warning(
                    "slide_mpp and objective_power both unavailable; "
                    "using 1:1 fallback (level0_window_size = model_input_size = %d)",
                    model_input_size,
                )

        if slide_mpp is not None and slide_mpp > 0:
            l0_size = max(1, round(model_input_size * target_mpp / slide_mpp))
        else:
            l0_size = model_input_size

        return cls(
            model_input_size=model_input_size,
            target_mpp=target_mpp,
            slide_mpp=slide_mpp,
            level0_window_size=l0_size,
            level0_stride=level0_stride,
            read_level=read_level,
            read_downsample=read_downsample,
        )

    def __repr__(self) -> str:
        return (
            f"InferenceGeometry(model_input={self.model_input_size}, "
            f"target_mpp={self.target_mpp}, slide_mpp={self.slide_mpp}, "
            f"level0_win={self.level0_window_size}, "
            f"scale={self.local_to_level0_scale:.3f}, "
            f"stride={self.level0_stride}, "
            f"read_level={self.read_level}/{self.read_downsample})"
        )
