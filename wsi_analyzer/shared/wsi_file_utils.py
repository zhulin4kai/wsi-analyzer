import os

WSI_EXTENSIONS = {".svs", ".tif", ".ndpi", ".ome.tif"}


def is_wsi_path(path: str) -> bool:
    full_lower = path.lower()
    return os.path.exists(path) and any(
        full_lower.endswith(ext) for ext in WSI_EXTENSIONS
    )


def extract_wsi_paths_from_mime(mime_data) -> list:
    if not mime_data.hasUrls():
        return []

    paths = []
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if is_wsi_path(path):
            paths.append(path)
    return paths
