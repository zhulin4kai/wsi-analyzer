import csv
import json
import os

from PySide6.QtWidgets import QFileDialog, QMessageBox


class ReportExporter:
    @staticmethod
    def export(parent, current_wsi_path, current_ai_results):
        """生成并导出CSV/JSON 格式的结构化报告"""
        if not current_ai_results:
            QMessageBox.warning(parent, "提示", "暂无分析数据可导出！")
            return

        # 1. 基础统计学计算
        total_lesions = len(current_ai_results)
        confidences = [item["confidence"] for item in current_ai_results]
        avg_conf = sum(confidences) / total_lesions if total_lesions > 0 else 0

        # 寻找置信度最高的病灶
        max_conf_item = max(current_ai_results, key=lambda x: x["confidence"])
        max_conf = max_conf_item["confidence"]
        max_conf_bbox = max_conf_item["bbox"]

        # 2. 弹出保存文件对话框
        default_name = "WSI_AI_Report.csv"
        if current_wsi_path:
            base_name = os.path.splitext(os.path.basename(current_wsi_path))[0]
            default_name = f"{base_name}_诊断报告.csv"

        save_path, filter_type = QFileDialog.getSaveFileName(
            parent, "导出诊断报告", default_name, "CSV 文件 (*.csv);;JSON 文件 (*.json)"
        )

        if not save_path:
            return

        # 3. 写入文件 (包含 I/O 异常捕获)
        try:
            if save_path.endswith(".csv"):
                # 使用 utf-8-sig 编码，防止 Excel 打开中文乱码
                with open(save_path, mode="w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)

                    # 写入总览信息
                    writer.writerow(["=== 智能病理辅助诊断报告 ==="])
                    writer.writerow(["分析文件", current_wsi_path])
                    writer.writerow(["病灶总数", total_lesions])
                    writer.writerow(["平均置信度", f"{avg_conf:.2%}"])
                    writer.writerow(
                        ["最高置信度", f"{max_conf:.2%} (坐标: {max_conf_bbox})"]
                    )
                    writer.writerow([])

                    # 写入明细表头
                    writer.writerow(
                        ["序号", "类别ID", "置信度", "X_min", "Y_min", "X_max", "Y_max"]
                    )
                    for idx, item in enumerate(current_ai_results, 1):
                        b = item["bbox"]
                        writer.writerow(
                            [
                                idx,
                                item["class_id"],
                                f"{item['confidence']:.4f}",
                                b[0],
                                b[1],
                                b[2],
                                b[3],
                            ]
                        )

            elif save_path.endswith(".json"):
                # JSON 格式导出
                export_data = {
                    "summary": {
                        "file": current_wsi_path,
                        "total_lesions": total_lesions,
                        "average_confidence": round(avg_conf, 4),
                        "max_confidence_bbox": max_conf_bbox,
                    },
                    "details": current_ai_results,
                }
                with open(save_path, mode="w", encoding="utf-8") as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=4)

            QMessageBox.information(
                parent, "导出成功", f"报告已成功保存至:\n{save_path}"
            )

        except PermissionError:
            QMessageBox.critical(
                parent,
                "导出失败",
                "文件被占用！\n请检查该文件是否正在被 Excel 或其他程序打开，关闭后再试。",
            )
        except Exception as e:
            QMessageBox.critical(parent, "导出失败", f"写入文件时发生错误:\n{str(e)}")
