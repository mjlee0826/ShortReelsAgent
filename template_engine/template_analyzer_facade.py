import os
from media_tools.media_downloader import MediaDownloader
from media_tools.ffmpeg_adapter import FFmpegAdapter
from media_tools.audio_beat_extractor import AudioBeatExtractor
from media_processor.complex_video_processor import ComplexVideoProcessor

from template_engine.scene_cut_extractor import SceneCutExtractor
from template_engine.blueprint_builder import BlueprintBuilder

class TemplateAnalyzerFacade:
    """
    Facade Pattern: Phase 2 指揮官。
    整合物理分析與 ComplexVideoProcessor 的強大解析力。
    """
    def __init__(self):
        self.downloader = MediaDownloader()
        # 【修正】使用大一統的 FFmpegAdapter
        self.ffmpeg = FFmpegAdapter()
        self.cut_extractor = SceneCutExtractor()
        self.beat_extractor = AudioBeatExtractor()
        self.complex_processor = ComplexVideoProcessor()
        self.builder = BlueprintBuilder()

    def extract_dna(self, input_source: str) -> dict:
        """
        一鍵提取 Template DNA：融合物理層與全感知語意層。
        """
        # 1. 獲取與下載
        media_info = self.downloader.fetch_video(input_source)
        video_file = media_info["video_path"]
        base_path = os.path.splitext(video_file)[0]

        # 2. 軌道剝離 (為了物理節拍分析)
        # 【修正】使用新 Adapter 分別處理畫面與音訊
        v_only = f"{base_path}_v_only.mp4"
        a_only = f"{base_path}_a_only.wav"
        
        self.ffmpeg.strip_audio_fast(video_file, v_only)
        self.ffmpeg.extract_ai_audio(video_file, a_only)

        # 3. 物理層分析
        physical_cuts = self.cut_extractor.get_cuts(v_only)
        beats = self.beat_extractor.get_beats(a_only)

        # 4. 深度感知
        print(f"[Facade] 正在啟動 ComplexVideoProcessor 進行深度感知...")
        complex_result = self.complex_processor.process(video_file)
        
        if complex_result.get("status") != "success":
            raise RuntimeError(f"Template 深度分析失敗: {complex_result.get('message')}")

        # 5. 封裝藍圖 (把路徑資訊也帶進去)
        dna = self.builder \
            .set_info(media_info["music_metadata"], media_info["original_url"]) \
            .set_local_assets(original_video=video_file, video_only=v_only, audio_only=a_only) \
            .set_physical_cuts(physical_cuts) \
            .set_audio_features(beats) \
            .ingest_complex_metadata(complex_result.get("metadata", {})) \
            .build()

        return dna