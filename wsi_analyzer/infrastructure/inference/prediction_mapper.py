from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class PredictionMapper:
    """Map model-local bbox predictions to WSI Level-0 coordinates.

    The scale factor comes from PatchCoordinate:
      local_to_level0_scale = level0_size / model_input_size

    A model output box [lx1, ly1, lx2, ly2] (in model input pixel space)
    maps to Level-0 as:
      level0_x1 = coord.x  + lx1 * scale
      level0_y1 = coord.y  + ly1 * scale
      level0_x2 = coord.x  + lx2 * scale
      level0_y2 = coord.y  + ly2 * scale
    """

    @staticmethod
    def to_level0_single(
        boxes, scores, classes, coord: PatchCoordinate
    ) -> tuple:
        scale = coord.local_to_level0_scale
        mapped_boxes = []
        mapped_scores = []
        mapped_classes = []
        for box, score, cls_id in zip(boxes, scores, classes):
            lx1, ly1, lx2, ly2 = box
            mapped_boxes.append([
                coord.x + lx1 * scale,
                coord.y + ly1 * scale,
                coord.x + lx2 * scale,
                coord.y + ly2 * scale,
            ])
            mapped_scores.append(score)
            mapped_classes.append(cls_id)
        return mapped_boxes, mapped_scores, mapped_classes

    @staticmethod
    def to_level0_batch(raw_predictions, batch_coords) -> tuple:
        all_boxes = []
        all_scores = []
        all_classes = []
        for j, (boxes, scores, classes) in enumerate(raw_predictions):
            if len(boxes) == 0:
                continue
            coord = batch_coords[j]
            mb, ms, mc = PredictionMapper.to_level0_single(boxes, scores, classes, coord)
            all_boxes.extend(mb)
            all_scores.extend(ms)
            all_classes.extend(mc)
        return all_boxes, all_scores, all_classes
