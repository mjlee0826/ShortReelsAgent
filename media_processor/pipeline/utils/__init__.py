"""
media_processor.pipeline.utils 套件:pipeline 共用的支援工具(非 DAG 節點)。

- ``video_frame_utils``:影片 Stage 共用的 cv2 取幀 / metadata 輔助函式。
- ``startup_report``:暖機後印出 GPU 配置 / pool 併發表的診斷報表。

刻意不在此 ``__init__`` 做 eager re-export:``startup_report`` 會牽動 model 層
(torch/GPU)的重型 import,呼叫端一律以子模組路徑直接 import,避免載入整個套件時被拖重。
"""
