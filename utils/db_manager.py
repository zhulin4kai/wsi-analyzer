import hashlib
import json
import os
import sqlite3
from datetime import datetime

from utils.logger import logger

# 数据库存储路径配置
DB_DIR = "data"
DB_FILE = os.path.join(DB_DIR, "wsi_data.db")


class DatabaseManager:
    """
    统一的 SQLite 数据库管理器，替代原有的 .wsi_cache 本地文件缓存系统。
    用于管理：
    1. 已经完成的 WSI 全片分析结果（替代原有的 JSON 缓存）。
    2. 被用户手动中断的分析进度（用于断点续传）。
    """

    _instance = None

    def __new__(cls, db_path=DB_FILE):
        """单例模式，确保全局复用同一个数据库连接池"""
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path):
        if (
            not os.path.exists(os.path.dirname(db_path))
            and os.path.dirname(db_path) != ""
        ):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 创建核心数据表
                # status: 'completed' (已完成) 或 'interrupted' (被中断)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS wsi_analysis (
                        wsi_hash TEXT PRIMARY KEY,
                        file_path TEXT,
                        model_path TEXT,
                        status TEXT,
                        total_patches INTEGER,
                        processed_patches INTEGER,
                        results_json TEXT,
                        valid_coords_json TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")

    @staticmethod
    def get_wsi_hash(file_path):
        """
        基于文件元数据的轻量级哈希算法秒级运算
        联合要素: 文件绝对路径 + 字节级精确大小 + 最后修改时间戳
        """
        try:
            abs_path = os.path.abspath(file_path)
            file_size = os.path.getsize(abs_path)
            mtime = os.path.getmtime(abs_path)
            feature_str = f"{abs_path}_{file_size}_{mtime}"
            return hashlib.md5(feature_str.encode("utf-8")).hexdigest()
        except Exception as e:
            logger.error(f"获取特征哈希失败: {e}")
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
    ):
        """
        保存分析结果或中断进度到数据库。

        :param file_path: WSI 切片绝对路径
        :param model_path: AI 权重绝对路径
        :param status: 'completed' 或 'interrupted'
        :param total_patches: 总需要推理的图块数量
        :param processed_patches: 已经推断完成的图块数量
        :param results: 当前检测到的病灶框数据 (List)
        :param valid_coords: 所有的组织坐标点阵 (断点续传需要)
        """
        wsi_hash = self.get_wsi_hash(file_path)
        if not wsi_hash:
            return

        results_json = json.dumps(results, ensure_ascii=False)
        valid_coords_json = json.dumps(valid_coords) if valid_coords else None
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO wsi_analysis
                    (wsi_hash, file_path, model_path, status, total_patches, processed_patches, results_json, valid_coords_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(wsi_hash) DO UPDATE SET
                        file_path=excluded.file_path,
                        model_path=excluded.model_path,
                        status=excluded.status,
                        total_patches=excluded.total_patches,
                        processed_patches=excluded.processed_patches,
                        results_json=excluded.results_json,
                        valid_coords_json=excluded.valid_coords_json,
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
                        updated_at,
                    ),
                )
                conn.commit()
                logger.info(f"已将分析进度存储至数据库 (状态: {status})")
        except Exception as e:
            logger.error(f"保存分析数据到数据库失败: {e}")

    def get_analysis(self, file_path):
        """
        读取当前 WSI 的分析记录 (完成的或被中断的均可读取)。

        :return: dict 包含数据库中的记录，如果没有则返回 None
        """
        wsi_hash = self.get_wsi_hash(file_path)
        if not wsi_hash:
            return None

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # 使结果支持列名索引
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
                    # 删除冗余的原始 json 字符串
                    del data["results_json"]
                    del data["valid_coords_json"]
                    return data
                return None
        except Exception as e:
            logger.error(f"读取数据库分析记录失败: {e}")
            return None

    def delete_analysis(self, file_path):
        """
        删除指定的 WSI 分析记录 (用于用户选择重新分析时清理旧的断点)
        """
        wsi_hash = self.get_wsi_hash(file_path)
        if not wsi_hash:
            return

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM wsi_analysis WHERE wsi_hash = ?", (wsi_hash,)
                )
                conn.commit()
                logger.info(f"已清除数据库中的 WSI 记录 (hash: {wsi_hash})")
        except Exception as e:
            logger.error(f"删除分析记录失败: {e}")
