from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QMessageBox

from config import AI_PEN_COLOR, AI_PEN_WIDTH
from utils import DatabaseManager


class DetectionLayerMixin:
    """AI 预测框的绘制、结果持久化及图层可见性控制。"""

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
    # LOD 动态视觉控制
    # ------------------------------------------------------------------

    def _on_interaction_start(self):
        """交互开始，隐藏 AI 图层以提升渲染性能"""
        # 记录隐藏前的显示状态，交互结束后按原状恢复
        self._was_ai_visible = self.chk_show_ai.isChecked()
        self.ai_layer_group.setVisible(False)

    def _on_interaction_finish(self):
        """交互结束，恢复 AI 图层显示"""
        if self._was_ai_visible:
            self.ai_layer_group.setVisible(True)

    def toggle_ai_visibility(self, checked):
        """响应"预测框"开关，切换 AI 图层整体可见性。

        Args:
            checked: toggled 信号传入的 bool。
        """
        self.ai_layer_group.setVisible(bool(checked))

    def clear_ai_results(self):
        """清除全部 AI 分析结果、预测框与病灶画廊显示。"""
        if not self.current_ai_results:
            return

        reply = QMessageBox.question(
            self,
            "清除结果",
            "确定要清除当前的所有分析结果吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)

        self.current_ai_results = []
        self.gallery.clear_gallery()
        self.btn_export.setEnabled(False)

        # 同步清空热力图（可选钩子，依赖 HeatmapMixin）
        if hasattr(self, "_clear_heatmap"):
            self._clear_heatmap()

        self.statusBar().showMessage("已清除分析结果。")
