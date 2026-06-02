"""TimecodeStage:在影片上燒錄視覺時間碼供 Gemini 索引(IO,Complex)。"""
from __future__ import annotations

import tempfile

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_work import get_video_work
from media_tools.ffmpeg_adapter import FFmpegAdapter

_STAGE_NAME = "timecode"
# 暫存影片副檔名(對齊原 process() 的 NamedTemporaryFile(suffix=".mp4"))
_VIDEO_SUFFIX = ".mp4"


class TimecodeStage(Stage):
    """
    在影片左上角燒錄視覺時間碼,輸出暫存 mp4,路徑寫入 ``VideoWork.tc_file_path``。

    僅 Complex 影片需要(防止 Gemini 產生時間軸幻覺)。暫存檔登記到 ``context.temp_paths`` 由 Pipeline
    結束時統一刪除。標記為 IO 資源(ffmpeg 重編碼子程序,通常是 Complex 路徑最耗時的一步);其產出只被
    SemanticVideo(Gemini)依賴,故在 DAG 中與音訊 / 場景 / 視覺特徵自然並行重疊。
    """

    def __init__(self):
        """設定 Stage 描述並建立 FFmpeg 配接器。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.IO)
        self._ffmpeg = FFmpegAdapter()

    def run(self, context: AssetContext) -> None:
        """建立 mp4 暫存檔 → 燒錄時間碼 → 記錄路徑並登記待清除。"""
        work = get_video_work(context)
        temp_tc = tempfile.NamedTemporaryFile(suffix=_VIDEO_SUFFIX, delete=False)
        tc_path = temp_tc.name
        temp_tc.close()
        # 先登記待清除,確保即使燒錄後續出錯,Pipeline finally 仍會刪掉此檔
        context.temp_paths.append(tc_path)
        self._ffmpeg.burn_timecode(context.file_path, tc_path)
        work.tc_file_path = tc_path
