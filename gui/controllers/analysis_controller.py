import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from utils import DatabaseManager
from workers import AIAnalysisWorker


class AnalysisController:
    def __init__(self, window, viewer, slide_controller):
        self._window = window
        self._viewer = viewer
        self._slide = slide_controller
        self.ai_thread = None
        self.progress_dialog = None
        self._is_canceling = False

    # ── public ─────────────────────────────────────────────────────

    def start_ai_analysis(self):
        w = self._window
        if not self._slide.current_wsi_path:
            QMessageBox.warning(w, "警告", "请先通过'文件'菜单打开一个 WSI 切片！")
            return
        if not w.current_model_path or not os.path.exists(w.current_model_path):
            QMessageBox.warning(w, "警告", "请先选择有效的模型权重 (.pt) 文件！")
            return

        db = DatabaseManager()
        cache_data = db.get_analysis(self._slide.current_wsi_path)
        resume_data = None

        if cache_data and cache_data.get("status") == "interrupted":
            msg_box = QMessageBox(w)
            msg_box.setWindowTitle("发现中断的分析")
            msg_box.setText(
                "检测到该病理切片有未完成的分析记录。\n是否继续上次的分析进度？\n选择'否'将重新开始。"
            )
            msg_box.setIcon(QMessageBox.Question)
            btn_yes = msg_box.addButton("是", QMessageBox.ActionRole)
            btn_no = msg_box.addButton("否", QMessageBox.ActionRole)
            msg_box.exec()
            if msg_box.clickedButton() == btn_yes:
                resume_data = cache_data
            else:
                db.delete_analysis(self._slide.current_wsi_path)

        w.btn_analyze.setEnabled(False)
        w.settings_action.setEnabled(False)
        w.btn_export.setEnabled(False)

        self.progress_dialog = QProgressDialog(
            "正在进行全片 AI 检测...", "取消", 0, 100, w
        )
        self.progress_dialog.setWindowTitle("分析进度")
        self.progress_dialog.setWindowModality(Qt.NonModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setValue(0)
        self.progress_dialog.canceled.connect(self.cancel_ai_analysis)

        self.ai_thread = AIAnalysisWorker(
            svs_path=self._slide.current_wsi_path,
            model_path=w.current_model_path,
            resume_data=resume_data,
        )

        self.ai_thread.progress_updated.connect(self.progress_dialog.setValue)
        self.ai_thread.status_updated.connect(w.statusBar().showMessage)
        self.ai_thread.analysis_finished.connect(w.render_ai_results)
        self.ai_thread.error_occurred.connect(self.handle_ai_error)
        self.ai_thread.finished.connect(lambda: w.btn_analyze.setEnabled(True))
        self.ai_thread.finished.connect(lambda: w.settings_action.setEnabled(True))

        self.progress_dialog.show()
        self.ai_thread.start()

    def toggle_roi_mode(self, checked):
        if self.ai_thread and self.ai_thread.isRunning():
            self._window.btn_roi_analyze.setChecked(False)
            QMessageBox.warning(
                self._window, "警告",
                "后台 AI 分析正在进行中，请先等待或取消当前任务。"
            )
            return
        self._viewer.toggle_roi_mode(checked)

    def start_roi_analysis(self, roi_coords):
        w = self._window
        w.btn_roi_analyze.setChecked(False)
        self._viewer.toggle_roi_mode(False)

        if not getattr(w, "current_model_path", None):
            self._viewer.clear_roi_box()
            QMessageBox.warning(w, "警告", "请先选择 AI 模型权重文件 (.pt)！")
            return

        w.btn_analyze.setEnabled(False)
        w.btn_roi_analyze.setEnabled(False)
        w.settings_action.setEnabled(False)
        w.btn_export.setEnabled(False)

        self.progress_dialog = QProgressDialog(
            "正在进行局部 ROI AI 检测...", "取消", 0, 100, w
        )
        self.progress_dialog.setWindowTitle("分析进度")
        self.progress_dialog.setWindowModality(Qt.NonModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setValue(0)
        self.progress_dialog.canceled.connect(self.cancel_ai_analysis)

        self.ai_thread = AIAnalysisWorker(
            svs_path=self._slide.current_wsi_path,
            model_path=w.current_model_path,
            resume_data=None,
            roi_bbox=roi_coords,
        )

        self.ai_thread.progress_updated.connect(self.progress_dialog.setValue)
        self.ai_thread.status_updated.connect(w.statusBar().showMessage)
        self.ai_thread.analysis_finished.connect(self._on_roi_finished)
        self.ai_thread.error_occurred.connect(self.handle_ai_error)
        self.ai_thread.finished.connect(lambda: w.btn_analyze.setEnabled(True))
        self.ai_thread.finished.connect(lambda: w.btn_roi_analyze.setEnabled(True))
        self.ai_thread.finished.connect(lambda: w.settings_action.setEnabled(True))
        self.ai_thread.finished.connect(lambda: w.btn_export.setEnabled(True))

        self.progress_dialog.show()
        self.ai_thread.start()

    def cancel_ai_analysis(self):
        w = self._window
        if self._is_canceling:
            return
        if not self.ai_thread or not self.ai_thread.isRunning():
            return

        self._is_canceling = True

        if self.progress_dialog:
            try:
                self.progress_dialog.canceled.disconnect(self.cancel_ai_analysis)
            except Exception:
                pass

        msg_box = QMessageBox(w)
        msg_box.setWindowTitle("取消确认")
        msg_box.setText("确定要中断当前的 AI 分析吗？进度将被保存。")
        msg_box.setIcon(QMessageBox.Question)
        btn_yes = msg_box.addButton("是", QMessageBox.ActionRole)
        btn_no = msg_box.addButton("否", QMessageBox.ActionRole)
        msg_box.exec()

        if msg_box.clickedButton() == btn_yes:
            if self.ai_thread and self.ai_thread.isRunning():
                self.ai_thread.cancel()
            if self.progress_dialog:
                self.progress_dialog.canceled.connect(self.cancel_ai_analysis)
        else:
            if self.progress_dialog:
                current_val = self.progress_dialog.value()
                self.progress_dialog.reset()
                self.progress_dialog.setValue(current_val)
                self.progress_dialog.canceled.connect(self.cancel_ai_analysis)
                QTimer.singleShot(0, self.progress_dialog.show)

        self._is_canceling = False

    def handle_ai_error(self, err_msg):
        self._close_progress_dialog()
        if hasattr(self._viewer, "clear_roi_box"):
            self._viewer.clear_roi_box()
        self._window.statusBar().showMessage("分析失败或被中断。")
        QMessageBox.critical(self._window, "AI 引擎错误", err_msg)

    # ── internal ───────────────────────────────────────────────────

    def _close_progress_dialog(self):
        if not self.progress_dialog:
            return
        try:
            self.progress_dialog.canceled.disconnect(self.cancel_ai_analysis)
        except (TypeError, RuntimeError):
            pass
        self.progress_dialog.close()
        self.progress_dialog = None

    def _on_roi_finished(self, results_dict):
        w = self._window
        self._close_progress_dialog()
        self._viewer.clear_roi_box()

        if results_dict.get("status") == "interrupted":
            w.statusBar().showMessage("局部 ROI 分析已取消，结果未保存。")
            QMessageBox.information(w, "提示", "ROI 分析已取消，结果未保存。")
            return

        new_results = results_dict.get("results", [])
        if not new_results:
            w.statusBar().showMessage("局部 ROI 分析完成，未检测到病灶。")
            QMessageBox.information(w, "提示", "未在该区域检测到病灶。")
            return

        db = DatabaseManager()
        nms_iou_thresh = db.get_setting("ai_nms_iou_thresh", 0.25)

        from core import fuse_results

        fused = fuse_results(
            getattr(w, "current_ai_results", []), new_results, nms_iou_thresh
        )

        w._commit_results({
            "status": "completed",
            "results": fused,
            "total_patches": results_dict.get("total_patches", 0),
            "processed_patches": results_dict.get("processed_patches", 0),
            "valid_coords": None,
        })

        w.statusBar().showMessage(
            f"局部 ROI 分析完成，合并后共 {len(fused)} 处病灶。"
        )
        QMessageBox.information(
            w, "完成",
            f"局部 ROI 分析完成！合并后共检测到 {len(fused)} 个病灶。",
        )
