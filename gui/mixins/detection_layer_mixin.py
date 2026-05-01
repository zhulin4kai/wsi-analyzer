import json

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QFileDialog, QGraphicsRectItem, QMessageBox

from config import (
    AI_PEN_COLOR,
    AI_PEN_WIDTH,
    IMPORTED_ANNOTATION_COLOR,
    IMPORTED_ANNOTATION_WIDTH,
)
from utils import DatabaseManager


class DetectionLayerMixin:
    """AI 预测框的绘制、结果持久化、导入标注及图层可见性控制。"""

    # ------------------------------------------------------------------
    # 结果提交与渲染
    # ------------------------------------------------------------------

    def _commit_results(self, results_dict):
        """统一提交分析结果：更新内存、绘制预测框、热力图、DB 持久化、画廊刷新。
        全图扫描与 ROI 分析共用此入口；调用前应已完成结果融合。
        """
        self._close_progress_dialog()

        results = results_dict.get("results", [])
        status = results_dict.get("status", "completed")

        self.current_ai_results = results
        self._draw_ai_boxes(results)
        self.btn_export.setEnabled(len(results) > 0)

        if hasattr(self, "_update_heatmap_layer"):
            self._update_heatmap_layer()

        if self.current_wsi_path:
            db = DatabaseManager()
            db.save_analysis(
                file_path=self.current_wsi_path,
                model_path=self.current_model_path or "",
                status=status,
                total_patches=results_dict.get("total_patches", 0),
                processed_patches=results_dict.get("processed_patches", 0),
                results=results,
                valid_coords=results_dict.get("valid_coords"),
                raw_boxes=results_dict.get("raw_boxes"),
                raw_scores=results_dict.get("raw_scores"),
                raw_classes=results_dict.get("raw_classes"),
            )

        self.gallery.load_results(self.current_wsi_path, results)

    def render_ai_results(self, results_dict):
        """全图扫描完成/中断时的回调，委托 _commit_results 完成持久化与 UI 更新。"""
        self._commit_results(results_dict)

        status = results_dict.get("status", "completed")
        count = len(results_dict.get("results", []))
        if status == "completed":
            QMessageBox.information(self, "分析完成", f"共标记 {count} 处疑似病灶。")
        else:
            QMessageBox.information(
                self, "分析已中止", f"进度已保存。当前标记 {count} 处疑似病灶。"
            )

    # ------------------------------------------------------------------
    # AI 预测框绘制
    # ------------------------------------------------------------------

    def _draw_ai_boxes(self, results):
        """清空旧预测框并根据传入结果在 Scene 上重新绘制。"""
        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)

        for data in results:
            x_min, y_min, x_max, y_max = data["bbox"]
            rect_item = QGraphicsRectItem(
                QRectF(x_min, y_min, x_max - x_min, y_max - y_min)
            )
            pen = QPen(QColor(*AI_PEN_COLOR))
            pen.setWidth(AI_PEN_WIDTH)
            pen.setCosmetic(True)
            rect_item.setPen(pen)
            rect_item.setToolTip(f"微乳头状癌病灶\n置信度: {data['confidence']:.2%}")
            self.ai_layer_group.addToGroup(rect_item)

        self.ai_layer_group.setVisible(self.chk_show_ai.isChecked())

    # ------------------------------------------------------------------
    # 导入标注（GeoJSON）
    # ------------------------------------------------------------------

    def import_annotations(self):
        """打开文件对话框，解析 GeoJSON 并绘制导入标注框。"""
        if not self.current_wsi_path:
            QMessageBox.warning(self, "提示", "请先加载切片后再导入标注。")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入标注", "", "GeoJSON 文件 (*.geojson *.json)"
        )
        if not file_path:
            return

        try:
            from gui.widgets.report_exporter import ReportExporter

            results = ReportExporter.import_geojson(file_path)
        except json.JSONDecodeError:
            QMessageBox.critical(self, "导入失败", "文件格式错误，无法解析 JSON。")
            return
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"读取文件时发生错误:\n{e}")
            return

        if not results:
            QMessageBox.information(self, "提示", "文件中未找到标注数据。")
            return

        self.current_imported_annotations = results
        self._draw_imported_boxes(results)
        self.statusBar().showMessage(
            f"已导入 {len(results)} 个标注"
        )
        if hasattr(self, "_update_heatmap_layer"):
            self._update_heatmap_layer()

    def _draw_imported_boxes(self, results):
        """清空旧导入标注，用黄色虚线样式绘制。"""
        self._clear_imported_layer()

        for data in results:
            x_min, y_min, x_max, y_max = data["bbox"]
            rect_item = QGraphicsRectItem(
                QRectF(x_min, y_min, x_max - x_min, y_max - y_min)
            )
            pen = QPen(QColor(*IMPORTED_ANNOTATION_COLOR))
            pen.setWidth(IMPORTED_ANNOTATION_WIDTH)
            pen.setCosmetic(True)
            rect_item.setPen(pen)
            rect_item.setToolTip(
                f"导入标注: {data.get('class_id', '-')}"
                f"\n置信度: {data.get('confidence', 0):.2%}"
            )
            self.imported_layer_group.addToGroup(rect_item)

        self.imported_layer_group.setVisible(self.chk_show_ai.isChecked())

    def _clear_imported_layer(self):
        """清空导入标注图层。"""
        if not hasattr(self, "imported_layer_group"):
            return
        for item in self.imported_layer_group.childItems():
            self.imported_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)

    # ------------------------------------------------------------------
    # LOD 动态视觉控制
    # ------------------------------------------------------------------

    def _on_interaction_start(self):
        """交互开始，隐藏 AI 图层与导入标注图层以提升渲染性能。"""
        self._was_ai_visible = self.chk_show_ai.isChecked()
        self.ai_layer_group.setVisible(False)
        if hasattr(self, "imported_layer_group"):
            self.imported_layer_group.setVisible(False)

    def _on_interaction_finish(self):
        """交互结束，恢复图层显示。"""
        if self._was_ai_visible:
            self.ai_layer_group.setVisible(True)
            if hasattr(self, "imported_layer_group"):
                self.imported_layer_group.setVisible(True)

    def toggle_ai_visibility(self, checked):
        """响应"预测框"开关，同时切换 AI 图层与导入标注图层的可见性。"""
        self.ai_layer_group.setVisible(bool(checked))
        if hasattr(self, "imported_layer_group"):
            self.imported_layer_group.setVisible(bool(checked))

    # ------------------------------------------------------------------
    # 清除
    # ------------------------------------------------------------------

    def clear_ai_results(self):
        """清除全部 AI 分析结果、预测框、导入标注与病灶画廊显示。"""
        if not self.current_ai_results and not self.current_imported_annotations:
            return

        reply = QMessageBox.question(
            self,
            "清除结果",
            "确定要清除当前的所有分析结果与导入标注吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)

        self._clear_imported_layer()
        self.current_ai_results = []
        self.current_imported_annotations = []

        self.gallery.clear_gallery()
        self.btn_export.setEnabled(False)

        if hasattr(self, "_clear_heatmap"):
            self._clear_heatmap()

        self.statusBar().showMessage("已清除分析结果。")
