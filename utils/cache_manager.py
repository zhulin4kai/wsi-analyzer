import hashlib
import os
import json
from config import CACHE_DIR


class CacheManager:
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
            return hashlib.md5(feature_str.encode('utf-8')).hexdigest()
        except Exception as e:
            print(f"获取特征哈希失败: {e}")
            return None

    @classmethod
    def save_analysis(cls, file_path, data):
        wsi_hash = cls.get_wsi_hash(file_path)
        if not wsi_hash: return
        if not os.path.exists(CACHE_DIR):
            os.mkdir(CACHE_DIR)
        cache_file = os.path.join(CACHE_DIR, wsi_hash)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    @classmethod
    def load_analysis(cls, file_path):
        wsi_hash = cls.get_wsi_hash(file_path)
        if not wsi_hash: return
        cache_file = os.path.join(CACHE_DIR, f"{wsi_hash}.json")
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

