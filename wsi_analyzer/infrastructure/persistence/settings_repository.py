import sqlite3

import config
from wsi_analyzer.infrastructure.logging.logger import logger


class SettingsStore:
    """
    用户设置持久化存储。
    管理 settings 表的增删改查 + 容量控制键的读写。
    不感知 wsi_analysis / system_profile 表。
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self):
        return sqlite3.connect(self._db_path, timeout=5000)

    # ── 通用键值读写 ──────────────────────────────────────────────────

    def get_setting(self, key: str, default=None):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    val_str = row[0]
                    if isinstance(default, bool):
                        return val_str.lower() == "true"
                    if isinstance(default, int):
                        return int(val_str)
                    if isinstance(default, float):
                        return float(val_str)
                    return val_str
                return default
        except Exception as e:
            logger.error(f"读取设置 {key} 失败: {e}")
            return default

    def set_setting(self, key: str, value):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, str(value)),
                )
                conn.commit()
                logger.info(f"已更新设置 {key} = {value}")
        except Exception as e:
            logger.error(f"保存设置 {key} 失败: {e}")

    # ── 快捷方法 ──────────────────────────────────────────────────────

    def get_auto_tune_enabled(self) -> bool:
        return self.get_setting("auto_tune_enabled", True)

    def set_auto_tune_enabled(self, enabled: bool):
        self.set_setting("auto_tune_enabled", str(enabled))

    def get_max_capacity(self) -> int:
        try:
            with self._connect() as conn:
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
                return max(getattr(config, "DB_MIN_CAPACITY_MB", 50), val)
        except Exception as e:
            logger.error(f"读取容量设置失败: {e}")
            return 150

    def set_max_capacity(self, mb: int):
        mb = max(getattr(config, "DB_MIN_CAPACITY_MB", 50), mb)
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('max_capacity_mb', ?)",
                    (str(mb),),
                )
                conn.commit()
                logger.info(f"已将数据库最大存储容量设置为 {mb} MB")
        except Exception as e:
            logger.error(f"设置容量限制失败: {e}")
