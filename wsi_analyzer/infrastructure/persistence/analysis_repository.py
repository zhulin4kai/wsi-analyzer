import hashlib
import json
import os
import sqlite3
from datetime import datetime

from wsi_analyzer.infrastructure.logging.logger import logger


class AnalysisCache:
    """
    WSI 分析结果缓存。
    管理 wsi_analysis 表的增删改查 + 容量控制（依赖 SettingsStore 提供上限）。
    不感知 settings / system_profile 表。
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self):
        return sqlite3.connect(self._db_path, timeout=5000)

    @staticmethod
    def get_wsi_hash(file_path):
        try:
            abs_path = os.path.abspath(file_path)
            file_size = os.path.getsize(abs_path)
            chunk_size = min(file_size, 1024 * 1024)
            with open(abs_path, "rb") as f:
                header_bytes = f.read(chunk_size)
            header_md5 = hashlib.md5(header_bytes).hexdigest()
            feature_str = f"{header_md5}_{file_size}"
            return hashlib.md5(feature_str.encode("utf-8")).hexdigest()
        except Exception as e:
            logger.error(f"获取特征哈希失败 ({file_path}): {e}")
            return None

    def save_analysis(
        self,
        file_path,
        model_path,
        status,
        total_patches,
        processed_patches,
        results,
        valid_coords=None,
        raw_boxes=None,
        raw_scores=None,
        raw_classes=None,
    ):
        wsi_hash = self.get_wsi_hash(file_path)
        if not wsi_hash:
            return

        results_json = json.dumps(results, ensure_ascii=False)
        valid_coords_json = json.dumps(valid_coords) if valid_coords else None
        raw_detections_json = (
            json.dumps(
                {"boxes": raw_boxes, "scores": raw_scores, "classes": raw_classes},
                ensure_ascii=False,
            )
            if raw_boxes is not None
            else None
        )
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO wsi_analysis
                    (wsi_hash, file_path, model_path, status, total_patches,
                     processed_patches, results_json, valid_coords_json,
                     raw_detections_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(wsi_hash) DO UPDATE SET
                        file_path=excluded.file_path,
                        model_path=excluded.model_path,
                        status=excluded.status,
                        total_patches=excluded.total_patches,
                        processed_patches=excluded.processed_patches,
                        results_json=excluded.results_json,
                        valid_coords_json=excluded.valid_coords_json,
                        raw_detections_json=excluded.raw_detections_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        wsi_hash,
                        file_path,
                        model_path,
                        status,
                        total_patches,
                        processed_patches,
                        results_json,
                        valid_coords_json,
                        raw_detections_json,
                        updated_at,
                    ),
                )
                conn.commit()
                logger.info(f"已将分析进度存储至数据库 (状态: {status})")
        except Exception as e:
            logger.error(f"保存分析数据到数据库失败: {e}")

    def get_analysis(self, file_path):
        wsi_hash = self.get_wsi_hash(file_path)
        if not wsi_hash:
            return None

        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM wsi_analysis WHERE wsi_hash = ?", (wsi_hash,)
                )
                row = cursor.fetchone()

                if row:
                    data = dict(row)
                    data["results"] = (
                        json.loads(data["results_json"]) if data["results_json"] else []
                    )
                    data["valid_coords"] = (
                        json.loads(data["valid_coords_json"])
                        if data["valid_coords_json"]
                        else None
                    )
                    raw_str = data.pop("raw_detections_json", None)
                    if raw_str:
                        raw = json.loads(raw_str)
                        data["raw_boxes"] = raw.get("boxes")
                        data["raw_scores"] = raw.get("scores")
                        data["raw_classes"] = raw.get("classes")
                    del data["results_json"]
                    del data["valid_coords_json"]
                    return data
                return None
        except Exception as e:
            logger.error(f"读取数据库分析记录失败: {e}")
            return None

    def delete_analysis(self, file_path):
        wsi_hash = self.get_wsi_hash(file_path)
        if not wsi_hash:
            return

        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM wsi_analysis WHERE wsi_hash = ?", (wsi_hash,)
                )
                conn.commit()
                logger.info(f"已清除数据库中的 WSI 记录 (hash: {wsi_hash})")
        except Exception as e:
            logger.error(f"删除分析记录失败: {e}")

    def enforce_capacity_limit(self, max_bytes: int):
        try:
            if not os.path.exists(self._db_path):
                return

            deleted = False
            while os.path.getsize(self._db_path) > max_bytes:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT wsi_hash FROM wsi_analysis "
                        "ORDER BY updated_at ASC LIMIT 1"
                    )
                    row = cursor.fetchone()
                    if not row:
                        break
                    cursor.execute(
                        "DELETE FROM wsi_analysis WHERE wsi_hash = ?",
                        (row[0],),
                    )
                    conn.commit()
                    deleted = True
                    logger.info(f"数据库容量超限，已自动淘汰最旧记录: {row[0]}")

            if deleted:
                try:
                    with self._connect() as conn:
                        conn.isolation_level = None
                        conn.execute("VACUUM")
                except sqlite3.OperationalError as ve:
                    logger.warning(f"VACUUM 当前被占用，稍后重试: {ve}")

        except Exception as e:
            logger.error(f"执行容量限制清理失败: {e}")
