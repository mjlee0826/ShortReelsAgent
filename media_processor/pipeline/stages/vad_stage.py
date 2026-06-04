"""VadStage:對抽出的 wav 做語音活動偵測(VAD),寫入 has_speech(CPU pool,單張)。"""
from __future__ import annotations

from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.executor.model_pool_registry import run_vad
from media_processor.pipeline.stage import ResourceType, Stage, StageMeta
from media_processor.pipeline.stages.video_work import audio_file_ready, get_video_work

_STAGE_NAME = "vad"


class VadStage(Stage):
    """
    以 Silero VAD 偵測 wav 是否含人聲,寫入 ``VideoWork.has_speech``,作為 WhisperStage 的閘門。

    Week 3a 由 ``AudioInferenceStage`` 全拆而來:VAD 底層不支援 batch(plan §4.2),維持單張呼叫。
    音訊檔不存在 / 過小(靜音)時跳過、保留預設(無語音),對齊原 ``_analyze_audio`` 短路。
    Silero VAD 在 **CPU** 推論(模型極輕、ms 級;搬上 GPU 的 H2D/D2H 開銷反而更慢、又佔 VRAM 跟
    Qwen 搶),故標記為 **CPU 資源**。改走 ``run_vad`` 從 CPU pool 借出(``VAD_POOL_SIZE`` 個獨立
    Silero instance、各有獨立 L3 lock),讓多支影片的 VAD 真平行 —— 修正原單例序列化(實測 3 片
    VAD 共用單一 instance 排隊到 250s+)。借出阻塞由 ``run_vad`` 計入 ResourceWaitClock。
    """

    def __init__(self):
        """設定 Stage 靜態描述。"""
        self.meta = StageMeta(name=_STAGE_NAME, resource_type=ResourceType.CPU)

    def run(self, context: AssetContext) -> None:
        """音訊有效才跑 VAD 並寫入 has_speech;無效則保留預設 False(維持無語音路徑)。"""
        work = get_video_work(context)
        if audio_file_ready(work.audio_path):
            # 從 CPU pool 借一個 VAD instance（不同 slot_id → 獨立 Silero + 獨立 L3 lock → 多影片真平行）
            work.has_speech = run_vad(lambda vad: vad.has_speech(work.audio_path))
