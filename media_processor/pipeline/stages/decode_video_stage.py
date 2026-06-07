"""DecodeVideoStage:抽影片 metadata + 中間代表幀,建立 VideoWork(DAG 起點)。"""
from __future__ import annotations

from config.media_processor_config import MIDDLE_FRAME_POSITION
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.work.frame_analysis import FrameAnalysis
from media_processor.pipeline.stages.video_frame_utils import (
    extract_video_metadata,
    grab_frame_at_time,
)
from media_processor.pipeline.work.video_work import VIDEO_WORK_KEY, VideoWork
from media_tools.ffmpeg_adapter import FFmpegAdapter

_STAGE_NAME = "decode_video"


class DecodeVideoStage(Stage):
    """
    影片 Pipeline 起點:以一次 cv2 session 取得影片 metadata 與中間代表幀,建立 VideoWork。

    合併原 ``_extract_video_metadata`` + ``_extract_middle_frame_pil`` 為一個 Stage(少開一次 VideoCapture、
    讓代表幀在最前面就緒,後續共用的 frame 分析 Stage 可立即並行)。標記為 IO 資源(ffprobe 子程序 + 檔案讀取);
    代表幀抽取失敗時 ``frame.pil_image=None``,下游守門退預設(對齊原 ``pil_mid is None`` 路徑)。
    """

    def __init__(self):
        """設定 Stage 描述並建立 FFmpeg 配接器。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.IO)
        self._ffmpeg = FFmpegAdapter()

    def run(self, context: AssetContext) -> None:
        """抽 metadata + 代表幀 → 建立並存入 VideoWork。"""
        meta = extract_video_metadata(context.file_path, self._ffmpeg)
        # 代表幀位置與原版一致(duration × MIDDLE_FRAME_POSITION)
        pil_mid = grab_frame_at_time(context.file_path, meta["duration"] * MIDDLE_FRAME_POSITION)
        context.scratch[VIDEO_WORK_KEY] = VideoWork(
            width=meta["width"],
            height=meta["height"],
            aspect_ratio=meta["aspect_ratio"],
            fps=meta["fps"],
            duration=meta["duration"],
            creation_time=meta["creation_time"],
            location_gps=meta["location_gps"],
            frame=FrameAnalysis(pil_image=pil_mid),
        )
