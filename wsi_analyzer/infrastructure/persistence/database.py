import os
import sqlite3
import threading

import config
from wsi_analyzer.infrastructure.logging.logger import logger
from wsi_analyzer.infrastructure.persistence.analysis_repository import AnalysisCache
from wsi_analyzer.infrastructure.persistence.profile_repository import ProfileStore
from wsi_analyzer.infrastructure.persistence.schema import DDL_STATEMENTS, SETTINGS_DEFAULTS
from wsi_analyzer.infrastructure.persistence.settings_repository import SettingsStore

DB_DIR = getattr(config, "DB_DIR", "data")
DB_FILE = getattr(config, "DB_FILE", os.path.join(DB_DIR, "wsi_data.db"))


class DatabaseManager:
    """
    SQLite 数据库统一入口（组合门面）。
    内部委托给三个领域 facade：
      - SettingsStore   — settings 表
      - AnalysisCache   — wsi_analysis 表
      - ProfileStore    — system_profile 表

    保有单例与 DB 初始化职责；外部代码可按需直接使用对应 facade。
    """

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, db_path=DB_FILE):
        if cls._instance is None:
            with cls._init_lock:
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

        try:
            with sqlite3.connect(db_path, timeout=5000) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                for ddl in DDL_STATEMENTS:
                    cursor.execute(ddl)
                for key, value in SETTINGS_DEFAULTS:
                    cursor.execute(
                        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                        (key, value),
                    )
                try:
                    cursor.execute(
                        "ALTER TABLE wsi_analysis ADD COLUMN raw_detections_json TEXT"
                    )
                except sqlite3.OperationalError:
                    pass
                conn.commit()

            self._settings = SettingsStore(db_path)
            self._analysis = AnalysisCache(db_path)
            self._profile = ProfileStore(db_path)
            self._enforce_capacity()
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")

    def _enforce_capacity(self):
        max_bytes = self._settings.get_max_capacity() * 1024 * 1024
        self._analysis.enforce_capacity_limit(max_bytes)

    @staticmethod
    def get_wsi_hash(file_path):
        return AnalysisCache.get_wsi_hash(file_path)

    @property
    def analysis(self):
        return self._analysis

    def save_analysis(
        self, file_path, model_path, status, total_patches,
        processed_patches, results, valid_coords=None,
        raw_boxes=None, raw_scores=None, raw_classes=None,
    ):
        self._analysis.save_analysis(
            file_path, model_path, status, total_patches,
            processed_patches, results, valid_coords,
            raw_boxes, raw_scores, raw_classes,
        )
        self._enforce_capacity()

    def get_analysis(self, file_path):
        return self._analysis.get_analysis(file_path)

    def delete_analysis(self, file_path):
        self._analysis.delete_analysis(file_path)

    @property
    def settings(self):
        return self._settings

    def get_setting(self, key: str, default=None):
        return self._settings.get_setting(key, default)

    def set_setting(self, key: str, value):
        self._settings.set_setting(key, value)

    def get_auto_tune_enabled(self) -> bool:
        return self._settings.get_auto_tune_enabled()

    def set_auto_tune_enabled(self, enabled: bool):
        self._settings.set_auto_tune_enabled(enabled)

    def get_max_capacity(self) -> int:
        return self._settings.get_max_capacity()

    def set_max_capacity(self, mb: int):
        self._settings.set_max_capacity(mb)
        self._enforce_capacity()

    def enforce_capacity_limit(self):
        self._enforce_capacity()

    @property
    def profile(self):
        return self._profile

    def get_system_profile(self, drive_prefix: str):
        return self._profile.get_system_profile(drive_prefix)

    def save_system_profile(self, drive_prefix: str, profile: dict):
        self._profile.save_system_profile(drive_prefix, profile)
