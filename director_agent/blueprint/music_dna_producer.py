"""Music 分支:委派 MusicDirector 解析配樂 DNA。"""
from __future__ import annotations

from director_agent.music_director import MusicDirector
from media_processor.pipeline.progress import ProgressTracker
from director_agent.blueprint.dna_producer import DnaProducer
from director_agent.blueprint.prep_context import PrepContext


class MusicDnaProducer(DnaProducer):
    """Music 分支:委派 ``MusicDirector`` 解析配樂 DNA。

    ``MusicDirector`` → ``MusicEngineFacade`` 的 Whisper/VAD 已改 borrow 共享 ``ModelPoolRegistry``,
    與 template 分支的 GPU 工作共用同一 GpuGate,並行不搶 VRAM(見 docs §5)。
    """

    name = "music_dna"

    def __init__(self):
        """持一個 MusicDirector(與 change_music 共用同一解析入口,邏輯一致)。"""
        self._director = MusicDirector()

    def produce(self, ctx: PrepContext, tracker: ProgressTracker | None = None) -> dict:
        """解析配樂 DNA;純對話微調(``regenerate_music=False``)不重抓配樂,回空 dict(對齊原 IntentState)。"""
        if not ctx.regenerate_music:
            return {}
        # tracker 透傳:music 分支於 download / beats / lyrics 發 STAGE_*,與 template 分支交錯上前端
        return self._director.resolve(
            music_strategy=ctx.music_strategy,
            user_music_file=ctx.user_music_file,
            user_prompt=ctx.user_prompt,
            tracker=tracker,
        )
