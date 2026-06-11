"""Template 分支:委派共享 PipelineRunner 走既有 complex 影片 DAG,再補節奏與 DNA 組裝。"""
from __future__ import annotations

import os

from media_tools.media_downloader import MediaDownloader
from media_tools.ffmpeg_adapter import FFmpegAdapter
from media_tools.audio_beat_extractor import AudioBeatExtractor
from media_processor.video_strategy import VideoStrategy
from media_processor.pipeline.progress import ProgressTracker
from template_engine.blueprint_builder import BlueprintBuilder
from director_agent.blueprint.dna_producer import DnaProducer
from director_agent.blueprint.prep_context import PrepContext

# 物理節奏分析用的純音軌檔名後綴(librosa 吃 wav);與舊 facade 命名一致,禁 magic string
_AUDIO_ONLY_SUFFIX = "_a_only.wav"
# 新流程不再產 video-only 軌(下游已無人消費),local_assets.video_only 留空
_NO_VIDEO_ONLY = ""


class TemplateDnaProducer(DnaProducer):
    """Template 分支:素材深度感知委派共享 ``PipelineRunner``(走既有 complex 影片 DAG),
    再補物理節奏(beats)與 DNA 組裝(Builder)。

    重點:不自己造 DAG —— complex 影片分析的 DAG 已存在於 pipeline,本生產者只是它的
    consumer + 後處理。``scene_cuts`` 直接取 pipeline metadata,不再重跑場景偵測(解 P2)。
    """

    name = "template_dna"

    def __init__(self, runner):
        """注入 director_service 已建好、模型已 warm 的共享 runner(跨請求重用,不可 new)。"""
        self._runner = runner
        self._downloader = MediaDownloader()
        self._ffmpeg = FFmpegAdapter()
        self._beat_extractor = AudioBeatExtractor()

    def produce(self, ctx: PrepContext, tracker: ProgressTracker | None = None) -> dict:
        """下載 template → 走共享 pipeline 深度感知 → 補 beats → 組裝 Template DNA。"""
        if not ctx.template_url:
            return {}

        # 1. 下載 template 影片
        media_info = self._downloader.fetch_video(ctx.template_url)
        video = media_info["video_path"]
        base_dir = os.path.dirname(video)
        asset_id = os.path.basename(video)

        # 2. 深度感知:走共享 pipeline(stage 並行、內部自動 borrow 模型);強制逐檔 COMPLEX 策略。
        #    tracker 透傳讓 stage 事件帶正確 job_id 上前端(無前端時為 None,退化純 print)。
        results = self._runner.run(
            [video],
            base_dir=base_dir,
            asset_strategies={asset_id: VideoStrategy.COMPLEX.value},
            tracker=tracker,
        )
        if not results:
            raise RuntimeError("Template 深度分析失敗(pipeline 無 success 結果)")
        complex_meta = results[0]["metadata"]

        # 3. 物理節奏:beats 是 template 專屬、librosa 純 CPU,留在本分支(不入 pipeline)。
        a_only = os.path.join(base_dir, f"{os.path.splitext(asset_id)[0]}{_AUDIO_ONLY_SUFFIX}")
        self._ffmpeg.extract_ai_audio(video, a_only)
        beats = self._beat_extractor.get_beats(a_only)

        # 4. 組裝 DNA;scene_cuts 取自 pipeline metadata(解 P2,不再自跑場景偵測)。
        return (
            BlueprintBuilder()
            .set_info(media_info["music_metadata"], media_info["original_url"])
            .set_local_assets(original_video=video, video_only=_NO_VIDEO_ONLY, audio_only=a_only)
            .set_physical_cuts(complex_meta.get("scene_cuts", []))
            .set_audio_features(beats)
            .ingest_complex_metadata(complex_meta)
            .build()
        )
