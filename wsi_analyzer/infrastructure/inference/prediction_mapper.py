from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class PredictionMapper:
    @staticmethod
    def to_level0_single(
        boxes, scores, classes, coord: PatchCoordinate
    ) -> tuple:
        mapped_boxes = []
        mapped_scores = []
        mapped_classes = []
        for box, score, cls_id in zip(boxes, scores, classes):
            lx1, ly1, lx2, ly2 = box
            mapped_boxes.append([lx1 + coord.x, ly1 + coord.y, lx2 + coord.x, ly2 + coord.y])
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
