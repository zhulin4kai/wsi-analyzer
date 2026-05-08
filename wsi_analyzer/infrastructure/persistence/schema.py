# WSI 全片分析结果与断点续传进度
# status: 'completed' (已完成) | 'interrupted' (被中断)
# raw_detections_json: 仅 interrupted 状态时有值，存储 pre-NMS 原始检测数据
#   格式: {"boxes": [[x1,y1,x2,y2],...], "scores": [...], "classes": [...]}
#   续传时优先使用此字段，以保证全局 NMS 结果正确
SQL_CREATE_WSI_ANALYSIS = """
    CREATE TABLE IF NOT EXISTS wsi_analysis (
        wsi_hash            TEXT PRIMARY KEY,
        file_path           TEXT,
        model_path          TEXT,
        status              TEXT,
        total_patches       INTEGER,
        processed_patches   INTEGER,
        results_json        TEXT,
        valid_coords_json   TEXT,
        raw_detections_json TEXT,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

# 通用用户配置（键值对）
SQL_CREATE_SETTINGS = """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
"""

# 硬件配置与 I/O 测速缓存
SQL_CREATE_SYSTEM_PROFILE = """
    CREATE TABLE IF NOT EXISTS system_profile (
        drive_prefix     TEXT PRIMARY KEY,
        device           TEXT,
        io_speed         REAL,
        io_rating        TEXT,
        batch_size       INTEGER,
        tile_cache_limit INTEGER,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

# 初始化数据：仅在对应行不存在时插入（INSERT OR IGNORE）
# 格式：(key, value) 元组列表，对应 settings 表
SETTINGS_DEFAULTS = [
    ("max_capacity_mb", "150"),
    ("auto_tune_enabled", "True"),
    ("ai_model_target_mpp", "2.0"),
    ("show_imported_heatmap", "True"),
]

# 便捷集合：_init_db 按序执行所有 DDL 即可，无需关心具体表名
DDL_STATEMENTS = [
    SQL_CREATE_WSI_ANALYSIS,
    SQL_CREATE_SETTINGS,
    SQL_CREATE_SYSTEM_PROFILE,
]
