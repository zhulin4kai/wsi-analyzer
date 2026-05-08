import sqlite3

from wsi_analyzer.infrastructure.logging.logger import logger


class ProfileStore:
    """
    硬件画像持久化存储。
    管理 system_profile 表的增改查。
    不感知 settings / wsi_analysis 表。
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self):
        return sqlite3.connect(self._db_path, timeout=5000)

    def get_system_profile(self, drive_prefix: str) -> dict:
        try:
            with self._connect() as conn:
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

    def save_system_profile(self, drive_prefix: str, profile: dict):
        try:
            with self._connect() as conn:
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
