import hashlib
import json
import os
import sqlite3
from datetime import datetime

import config
from utils.db_schema import DDL_STATEMENTS, SETTINGS_DEFAULTS
from utils.logger import logger

# 数据库存储路径配置
DB_DIR = getattr(config, "DB_DIR", "data")
DB_FILE = getattr(config, "DB_FILE", os.path.join(DB_DIR, "wsi_data.db"))


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
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")

                # 创建所有数据表（DDL 定义见 utils/db_schema.py）
                for ddl in DDL_STATEMENTS:
                    cursor.execute(ddl)

                # 写入默认配置（已存在的行不会被覆盖）
                for key, value in SETTINGS_DEFAULTS:
                    cursor.execute(
                        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                        (key, value),
                    )

                conn.commit()

            self.enforce_capacity_limit()
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")

    @staticmethod
    def get_wsi_hash(file_path):
        """
        基于部分文件特征的极速哈希算法（免疫文件重命名和移动）
        联合要素: 文件头部 1MB 字节的 MD5 + 文件字节级精确大小
        """
        try:
            abs_path = os.path.abspath(file_path)
            file_size = os.path.getsize(abs_path)

            # 读取头部最多 1MB 数据进行哈希，速度极快且唯一性有保障
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
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
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

            self.enforce_capacity_limit()
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
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
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
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM wsi_analysis WHERE wsi_hash = ?", (wsi_hash,)
                )
                conn.commit()
                logger.info(f"已清除数据库中的 WSI 记录 (hash: {wsi_hash})")
        except Exception as e:
            logger.error(f"删除分析记录失败: {e}")

    def get_max_capacity(self) -> int:
        """获取设置的数据库最大存储容量(MB)"""
        try:
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT value FROM settings WHERE key = 'max_capacity_mb'"
                )
                row = cursor.fetchone()
                val = (
                    int(row[0])
                    if row
                    else getattr(config, "DB_DEFAULT_CAPACITY_MB", 150)
                )
                return max(
                    getattr(config, "DB_MIN_CAPACITY_MB", 50), val
                )  # 强制最低 50MB
        except Exception as e:
            logger.error(f"读取容量设置失败: {e}")
            return 150

    def get_setting(self, key: str, default: any = None) -> any:
        """通用读取设置方法，如果数据库中没有则返回 default"""
        try:
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    val_str = row[0]
                    if isinstance(default, int):
                        return int(val_str)
                    elif isinstance(default, float):
                        return float(val_str)
                    return val_str
                return default
        except Exception as e:
            logger.error(f"读取设置 {key} 失败: {e}")
            return default

    def set_setting(self, key: str, value: any):
        """通用保存设置方法"""
        try:
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, str(value)),
                )
                conn.commit()
                logger.info(f"已更新设置 {key} = {value}")
        except Exception as e:
            logger.error(f"保存设置 {key} 失败: {e}")

    def get_auto_tune_enabled(self) -> bool:
        """获取是否开启 AI 智能调优"""
        val = self.get_setting("auto_tune_enabled", "True")
        return str(val).lower() == "true"

    def set_auto_tune_enabled(self, enabled: bool):
        """设置是否开启 AI 智能调优"""
        self.set_setting("auto_tune_enabled", str(enabled))

    def set_max_capacity(self, mb: int):
        """设置数据库最大存储容量(MB)"""
        mb = max(
            getattr(config, "DB_MIN_CAPACITY_MB", 50), mb
        )  # 强制限制最低 50MB，防止异常设置导致数据被清空
        try:
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('max_capacity_mb', ?)",
                    (str(mb),),
                )
                conn.commit()
                logger.info(f"已将数据库最大存储容量设置为 {mb} MB")
            self.enforce_capacity_limit()
        except Exception as e:
            logger.error(f"设置容量限制失败: {e}")

    def enforce_capacity_limit(self):
        """自动容量控制：如果超出限制，则按时间顺序淘汰最旧的分析记录"""
        try:
            max_bytes = self.get_max_capacity() * 1024 * 1024
            if not os.path.exists(self.db_path):
                return

            while os.path.getsize(self.db_path) > max_bytes:
                with sqlite3.connect(self.db_path, timeout=5000) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT wsi_hash FROM wsi_analysis ORDER BY updated_at ASC LIMIT 1"
                    )
                    row = cursor.fetchone()
                    if not row:
                        break

                    wsi_hash = row[0]
                    cursor.execute(
                        "DELETE FROM wsi_analysis WHERE wsi_hash = ?", (wsi_hash,)
                    )
                    conn.commit()
                    logger.info(f"数据库容量超限，已自动淘汰最旧记录: {wsi_hash}")

                # 删除单条后立刻执行 VACUUM 以实际回收文件系统空间
                # 注意：VACUUM 会锁定数据库，如果并发占用时可能抛出 OperationalError
                try:
                    with sqlite3.connect(self.db_path, timeout=5000) as conn:
                        conn.isolation_level = None  # VACUUM 不能在事务中运行
                        conn.execute("VACUUM")
                except sqlite3.OperationalError as ve:
                    logger.warning(f"VACUUM 当前被占用，稍后重试: {ve}")
                    break  # 必须立刻跳出循环，否则文件大小不缩小会导致把整张表清空！

        except Exception as e:
            logger.error(f"执行容量限制清理失败: {e}")

    def save_system_profile(self, drive_prefix: str, profile: dict):
        try:
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO system_profile
                    (drive_prefix, device, io_speed, io_rating, batch_size, tile_cache_limit, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(drive_prefix) DO UPDATE SET
                        device=excluded.device,
                        io_speed=excluded.io_speed,
                        io_rating=excluded.io_rating,
                        batch_size=excluded.batch_size,
                        tile_cache_limit=excluded.tile_cache_limit,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        drive_prefix,
                        profile.get("device"),
                        profile.get("io_speed"),
                        profile.get("io_rating"),
                        profile.get("batch_size"),
                        profile.get("tile_cache_limit"),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"保存 system_profile 失败: {e}")

    def get_system_profile(self, drive_prefix: str) -> dict:
        try:
            with sqlite3.connect(self.db_path, timeout=5000) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM system_profile WHERE drive_prefix = ?",
                    (drive_prefix,),
                )
                row = cursor.fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            logger.error(f"读取 system_profile 失败: {e}")
        return None
