"""
媒體副檔名白名單集中管理 (Configuration Object Pattern)。

「什麼副檔名算圖片 / 影片 / 音訊」是橫跨 media_processor(Pipeline 路由)、backend(素材探索與
音訊上傳驗證)與 ingestion_engine(雲端列檔過濾)的共同契約。原本散落於
``media_processor.pipeline.context``、``backend.api.director`` 與 ``config.ingestion_config`` 三處、
靠註解「對齊」維持一致,任一處增減副檔名都可能與其他處 drift。集中於此最底層 config 作為唯一
事實來源:各層一律從這裡 import,新增格式只改一處。
"""
from __future__ import annotations

# 圖片副檔名白名單(含 HEIC/HEIF;HEIC 經 media_standardizer 轉 JPG 後才進瀏覽器)。
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})

# 影片副檔名白名單(與 MediaProcessorFactory 路由一致;非 .mp4 容器由 standardizer 轉 H.264)。
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov"})

# 純音訊副檔名白名單(供使用者自訂配樂上傳驗證,與 Phase 3 音訊處理支援格式對齊)。
AUDIO_EXTENSIONS: frozenset[str] = frozenset({".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"})

# 所有受支援媒體副檔名的聯集(圖片 ∪ 影片 ∪ 音訊):供雲端攝取列檔過濾,
# 避免把雲端雜檔(文件 / 壓縮檔)一起拉下來。
MEDIA_EXTENSIONS: frozenset[str] = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
