from dataclasses import dataclass


@dataclass(frozen=True)
class InferenceScaleConfig:
    model_input_size: int
    level0_stride: int
    nms_iou_thresh: float
    conf_thresh: float
    device: str
    batch_size: int
    target_mpp: float

    @classmethod
    def from_raw(
        cls,
        patch_size: int,
        stride: int,
        nms_iou_thresh: float,
        conf_thresh: float,
        device: str,
        batch_size: int,
        target_mpp: float,
        patch_size_min: int = 128,
        patch_size_max: int = 4096,
        stride_min: int = 64,
        stride_max: int = 4096,
        iou_min: float = 0.01,
        iou_max: float = 1.0,
        conf_min: float = 0.01,
        conf_max: float = 1.0,
        batch_cap: int = 64,
    ):
        return cls(
            model_input_size=max(patch_size_min, min(patch_size, patch_size_max)),
            level0_stride=max(stride_min, min(stride, stride_max)),
            nms_iou_thresh=max(iou_min, min(nms_iou_thresh, iou_max)),
            conf_thresh=max(conf_min, min(conf_thresh, conf_max)),
            device=device,
            batch_size=min(batch_size, batch_cap),
            target_mpp=target_mpp,
        )
