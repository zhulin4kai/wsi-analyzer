import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMessageBox,
    QProgressDialog,
)

from utils import DatabaseManager
from workers import AIAnalysisWorker


class AnalysisRunnerMixin:
    """AIAnalysisWorker 线程的启动、进度对话框管理、ROI 结果融合与取消/错误处理。"""

    def _close_progress_dialog(self):
        """断开取消信号后安全关闭进度对话框。

        QProgressDialog.closeEvent 会主动 emit canceled() 信号，若不提前断开
        会意外触发 cancel_ai_analysis，导致确认框在分析正常结束后再次弹出。
        """
        if not hasattr(self, "progress_dialog") or not self.progress_dialog:
            return
        try:
            self.progress_dialog.canceled.disconnect(self.cancel_ai_analysis)
        except (TypeError, RuntimeError):
            pass
        self.progress_dialog.close()
        self.progress_dialog = None

    def start_ai_analysis(self):
        """启动全片后台推断"""
        if not self.current_wsi_path:
            QMessageBox.warning(self, "警告", "请先通过'文件'菜单打开一个 WSI 切片！")
            return
        if not self.current_model_path or not os.path.exists(self.current_model_path):
            QMessageBox.warning(self, "警告", "请先选择有效的模型权重 (.pt) 文件！")
            return

        db = DatabaseManager()
        cache_data = db.get_analysis(self.current_wsi_path)
        resume_data = None

        if cache_data and cache_data.get("status") == "interrupted":
            msg_box = QMessageBox(self)
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
                db.delete_analysis(self.current_wsi_path)

        self.btn_analyze.setEnabled(False)
        self.settings_action.setEnabled(False)
        self.btn_export.setEnabled(False)

        self.progress_dialog = QProgressDialog(
            "正在进行全片 AI 检测...", "取消", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("分析进度")
        self.progress_dialog.setWindowModality(Qt.NonModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setValue(0)
        self.progress_dialog.canceled.connect(self.cancel_ai_analysis)

        self.ai_thread = AIAnalysisWorker(
            svs_path=self.current_wsi_path,
            model_path=self.current_model_path,
            resume_data=resume_data,
        )

        self.ai_thread.progress_updated.connect(self.progress_dialog.setValue)
        self.ai_thread.status_updated.connect(self.statusBar().showMessage)
        self.ai_thread.analysis_finished.connect(self.render_ai_results)
        self.ai_thread.error_occurred.connect(self.handle_ai_error)
        self.ai_thread.finished.connect(lambda: self.btn_analyze.setEnabled(True))
        self.ai_thread.finished.connect(lambda: self.settings_action.setEnabled(True))

        self.progress_dialog.show()
        self.ai_thread.start()

    def toggle_roi_mode(self, checked):
        """切换框选 ROI 模式；若后台分析正在运行则拒绝切换。"""
        if hasattr(self, "ai_thread") and self.ai_thread and self.ai_thread.isRunning():
            self.btn_roi_analyze.setChecked(False)
            QMessageBox.warning(
                self, "警告", "后台 AI 分析正在进行中，请先等待或取消当前任务。"
            )
            return
        self.viewer.toggle_roi_mode(checked)

    def start_roi_analysis(self, roi_coords):
        """启动局部 ROI 后台推断。由 viewer.roi_drawn 信号触发。"""
        self.btn_roi_analyze.setChecked(False)
        self.viewer.toggle_roi_mode(False)

        if not getattr(self, "current_model_path", None):
            self.viewer.clear_roi_box()
            QMessageBox.warning(
                self, "警告", "请先选择 AI 模型权重文件 (.pt)！"
            )
            return

        self.btn_analyze.setEnabled(False)
        self.btn_roi_analyze.setEnabled(False)
        self.settings_action.setEnabled(False)
        self.btn_export.setEnabled(False)

        self.progress_dialog = QProgressDialog(
            "正在进行局部 ROI AI 检测...", "取消", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("分析进度")
        self.progress_dialog.setWindowModality(Qt.NonModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setValue(0)
        self.progress_dialog.canceled.connect(self.cancel_ai_analysis)

        self.ai_thread = AIAnalysisWorker(
            svs_path=self.current_wsi_path,
            model_path=self.current_model_path,
            resume_data=None,
            roi_bbox=roi_coords,
        )

        self.ai_thread.progress_updated.connect(self.progress_dialog.setValue)
        self.ai_thread.status_updated.connect(self.statusBar().showMessage)
        self.ai_thread.analysis_finished.connect(self.on_ai_finished_roi)
        self.ai_thread.error_occurred.connect(self.handle_ai_error)
        self.ai_thread.finished.connect(lambda: self.btn_analyze.setEnabled(True))
        self.ai_thread.finished.connect(lambda: self.btn_roi_analyze.setEnabled(True))
        self.ai_thread.finished.connect(lambda: self.settings_action.setEnabled(True))
        self.ai_thread.finished.connect(lambda: self.btn_export.setEnabled(True))

        self.progress_dialog.show()
        self.ai_thread.start()

    def on_ai_finished_roi(self, results_dict):
        """ROI 分析完成回调：融合结果后委托 _commit_results 统一提交。"""
        self._close_progress_dialog()
        self.viewer.clear_roi_box()

        if results_dict.get("status") == "interrupted":
            self.statusBar().showMessage("局部 ROI 分析已取消，结果未保存。")
            QMessageBox.information(self, "提示", "ROI 分析已取消，结果未保存。")
            return

        new_results = results_dict.get("results", [])
        if not new_results:
            self.statusBar().showMessage("局部 ROI 分析完成，未检测到病灶。")
            QMessageBox.information(self, "提示", "未在该区域检测到病灶。")
            return

        db = DatabaseManager()
        nms_iou_thresh = db.get_setting("ai_nms_iou_thresh", 0.25)

        from core import fuse_results

        fused = fuse_results(
            getattr(self, "current_ai_results", []), new_results, nms_iou_thresh
        )

        # ROI 完成后以 completed 状态覆盖写入；不携带续传字段
        self._commit_results(
            {
                "status": "completed",
                "results": fused,
                "total_patches": results_dict.get("total_patches", 0),
                "processed_patches": results_dict.get("processed_patches", 0),
                "valid_coords": None,
            }
        )

        self.statusBar().showMessage(
            f"局部 ROI 分析完成，合并后共 {len(fused)} 处病灶。"
        )
        QMessageBox.information(
            self,
            "完成",
            f"局部 ROI 分析完成！合并后共检测到 {len(fused)} 个病灶。",
        )

    def cancel_ai_analysis(self):
        """弹出确认框后中断当前 AI 分析线程；用户选择继续则重新绑定取消信号。"""
        if getattr(self, "_is_canceling", False):
            return
        if (
            not hasattr(self, "ai_thread")
            or not self.ai_thread
            or not self.ai_thread.isRunning()
        ):
            return

        self._is_canceling = True

        # 在弹出确认框前先断开信号，防止 QProgressDialog 在 QMessageBox.exec()
        # 运行期间再次触发 canceled 信号导致确认框二次弹出
        if hasattr(self, "progress_dialog"):
            try:
                self.progress_dialog.canceled.disconnect(self.cancel_ai_analysis)
            except Exception:
                pass

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("取消确认")
        msg_box.setText("确定要中断当前的 AI 分析吗？进度将被保存。")
        msg_box.setIcon(QMessageBox.Question)
        btn_yes = msg_box.addButton("是", QMessageBox.ActionRole)
        btn_no = msg_box.addButton("否", QMessageBox.ActionRole)
        msg_box.exec()

        if msg_box.clickedButton() == btn_yes:
            if self.ai_thread and self.ai_thread.isRunning():
                self.ai_thread.cancel()
            # 重新连接信号，确保后续 _close_progress_dialog 能正常断开；
            # 之后 on_ai_finished_roi 会统一关闭进度对话框
            if hasattr(self, "progress_dialog") and self.progress_dialog:
                self.progress_dialog.canceled.connect(self.cancel_ai_analysis)
        else:
            if hasattr(self, "progress_dialog"):
                # 重置进度条以清除内部的 wasCanceled 锁定状态
                current_val = self.progress_dialog.value()
                self.progress_dialog.reset()
                self.progress_dialog.setValue(current_val)
                # 用户选择继续，重新连接取消信号
                self.progress_dialog.canceled.connect(self.cancel_ai_analysis)
                # 延迟执行 show()，避开 QProgressDialog 在触发 close 事件后的自动隐藏机制
                QTimer.singleShot(0, self.progress_dialog.show)

        self._is_canceling = False

    def handle_ai_error(self, err_msg):
        """处理 AI 线程 error_occurred 信号：关闭进度框并弹出错误提示。"""
        self._close_progress_dialog()

        if hasattr(self, "viewer"):
            self.viewer.clear_roi_box()

        self.statusBar().showMessage("分析失败或被中断。")
        QMessageBox.critical(self, "AI 引擎错误", err_msg)
