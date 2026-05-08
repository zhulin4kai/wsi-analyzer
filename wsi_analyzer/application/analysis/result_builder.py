class AnalysisResultBuilder:
    @staticmethod
    def completed(results, valid_coords, processed_patches, total_patches):
        return {
            "status": "completed",
            "results": results,
            "valid_coords": valid_coords,
            "processed_patches": processed_patches,
            "total_patches": total_patches,
        }

    @staticmethod
    def interrupted(
        results,
        raw_boxes,
        raw_scores,
        raw_classes,
        valid_coords,
        processed_patches,
        total_patches,
    ):
        return {
            "status": "interrupted",
            "results": results,
            "raw_boxes": raw_boxes,
            "raw_scores": raw_scores,
            "raw_classes": raw_classes,
            "valid_coords": valid_coords,
            "processed_patches": processed_patches,
            "total_patches": total_patches,
        }

    @staticmethod
    def error(message):
        return {
            "status": "error",
            "message": message,
            "results": [],
            "valid_coords": [],
            "processed_patches": 0,
            "total_patches": 0,
        }
