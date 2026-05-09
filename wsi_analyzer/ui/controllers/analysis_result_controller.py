import json

from PySide6.QtWidgets import QFileDialog, QMessageBox

from wsi_analyzer.app.dependency_container import container


class AnalysisResultController:
    def __init__(self, window, viewer, layers, gallery, btn_export, chk_show_ai):
        self._window = window
        self._viewer = viewer
        self._layers = layers
        self._gallery = gallery
        self._btn_export = btn_export
        self._chk_show_ai = chk_show_ai

    # ── AI box drawing ─────────────────────────────────────────────

    def _draw_ai_boxes(self, results):
        self._layers.detection.render(results)
        self._layers.detection.set_visible(self._chk_show_ai.isChecked())

    # ── imported annotation drawing ────────────────────────────────

    def import_annotations(self):
        w = self._window
        if not w.current_wsi_path:
            QMessageBox.warning(w, "提示", "请先加载切片后再导入标注。")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            w, "导入标注", "", "GeoJSON 文件 (*.geojson *.json)"
        )
        if not file_path:
            return

        try:
            from wsi_analyzer.ui.widgets.report_exporter import ReportExporter
            results = ReportExporter.import_geojson(file_path)
        except json.JSONDecodeError:
            QMessageBox.critical(w, "导入失败", "文件格式错误，无法解析 JSON。")
            return
        except Exception as e:
            QMessageBox.critical(w, "导入失败", f"读取文件时发生错误:\n{e}")
            return

        if not results:
            QMessageBox.information(w, "提示", "文件中未找到标注数据。")
            return

        w.current_imported_annotations = results
        self._layers.annotation.render(results)
        self._layers.annotation.set_visible(self._chk_show_ai.isChecked())
        w.statusBar().showMessage(f"已导入 {len(results)} 个标注")
        if hasattr(w, "_update_heatmap_layer"):
            w.heatmap_controller._update_heatmap_layer()

    # ── LOD interaction ────────────────────────────────────────────

    def on_interaction_start(self):
        self._was_ai_visible = self._chk_show_ai.isChecked()
        self._layers.set_ai_visible(False)

    def on_interaction_finish(self):
        if getattr(self, "_was_ai_visible", True):
            self._layers.set_ai_visible(True)

    def toggle_ai_visibility(self, checked):
        self._layers.set_ai_visible(bool(checked))

    # ── clear ──────────────────────────────────────────────────────

    def clear_ai_results(self):
        w = self._window
        if not w.current_ai_results and not w.current_imported_annotations:
            return

        reply = QMessageBox.question(
            w, "清除结果",
            "确定要清除当前的所有分析结果与导入标注吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._layers.clear_ai_items()
        w.current_ai_results = []
        w.current_imported_annotations = []
        self._gallery.clear_gallery()
        self._btn_export.setEnabled(False)
        if hasattr(w, "_clear_heatmap"):
            w.heatmap_controller._clear_heatmap()
        w.statusBar().showMessage("已清除分析结果。")

    # ── result commit ──────────────────────────────────────────────

    def merge_and_commit(
        self, new_results, existing_results, total_patches, processed_patches
    ):
        db = container.database
        nms_iou_thresh = db.get_setting("ai_nms_iou_thresh", 0.25)

        from wsi_analyzer.domain.detection import fuse_results

        fused = fuse_results(existing_results, new_results, nms_iou_thresh)

        self._commit_results({
            "status": "completed",
            "results": fused,
            "total_patches": total_patches,
            "processed_patches": processed_patches,
            "valid_coords": None,
        })

        return fused

    def _commit_results(self, results_dict):
        w = self._window
        w.analysis_controller._close_progress_dialog()

        results = results_dict.get("results", [])
        status = results_dict.get("status", "completed")

        w.current_ai_results = results
        self._draw_ai_boxes(results)
        self._btn_export.setEnabled(len(results) > 0)

        if hasattr(w, "_update_heatmap_layer"):
            w.heatmap_controller._update_heatmap_layer()

        if w.current_wsi_path:
            container.database.analysis.save_analysis(
                file_path=w.current_wsi_path,
                model_path=w.current_model_path or "",
                status=status,
                total_patches=results_dict.get("total_patches", 0),
                processed_patches=results_dict.get("processed_patches", 0),
                results=results,
                valid_coords=results_dict.get("valid_coords"),
                raw_boxes=results_dict.get("raw_boxes"),
                raw_scores=results_dict.get("raw_scores"),
                raw_classes=results_dict.get("raw_classes"),
            )

        self._gallery.load_results(w.current_wsi_path, results)

    def render_ai_results(self, results_dict):
        self._commit_results(results_dict)
        status = results_dict.get("status", "completed")
        count = len(results_dict.get("results", []))
        if status == "completed":
            QMessageBox.information(self._window, "分析完成", f"共标记 {count} 处疑似病灶。")
        else:
            QMessageBox.information(
                self._window, "分析已中止", f"进度已保存。当前标记 {count} 处疑似病灶。"
            )
