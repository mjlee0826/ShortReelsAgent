from TemplateEngine.MediaDownloader import MediaDownloader
from TemplateEngine.MediaDemuxer import MediaDemuxer
from TemplateEngine.SceneCutExtractor import SceneCutExtractor
from TemplateEngine.AudioBeatExtractor import AudioBeatExtractor
from TemplateEngine.BlueprintBuilder import BlueprintBuilder
# 直接引入 Phase 1 的核心處理器
from MediaProcessor.ComplexVideoProcessor import ComplexVideoProcessor

class TemplateAnalyzerFacade:
    """
    Facade Pattern: Phase 2 指揮官。
    整合物理分析與 ComplexVideoProcessor 的強大解析力。
    """
    def __init__(self):
        self.downloader = MediaDownloader()
        self.demuxer = MediaDemuxer()
        self.cut_extractor = SceneCutExtractor()
        self.beat_extractor = AudioBeatExtractor()
        # 直接使用 Phase 1 寫好的 Processor
        self.complex_processor = ComplexVideoProcessor()
        self.builder = BlueprintBuilder()

    def extract_dna(self, input_source: str) -> dict:
        """
        一鍵提取 Template DNA：融合物理層與全感知語意層。
        """
        # 1. 獲取與下載
        media_info = self.downloader.fetch_video(input_source)
        video_file = media_info["video_path"]

        # 2. 軌道剝離 (為了物理節拍分析)
        v_only, a_only = self.demuxer.extract_tracks(video_file)

        # 3. 物理層分析 (BPM 與 硬切點)
        physical_cuts = self.cut_extractor.get_cuts(v_only)
        beats = self.beat_extractor.get_beats(a_only)

        # 4. 🔥 重點：讓 Template 跑一次 Phase 1 的 Complex 流程
        # 這會自動執行：燒錄時間碼、VAD 偵測、Gemini 多模態分析 (包含逐字稿)
        print(f"[Facade] 正在啟動 ComplexVideoProcessor 進行深度感知...")
        complex_result = self.complex_processor.process(video_file)
        
        if complex_result.get("status") != "success":
            raise RuntimeError(f"Template 深度分析失敗: {complex_result.get('message')}")

        # 5. 封裝藍圖
        # 這裡會將物理切點與 Gemini 抓到的語意時間軸進行對齊與補足
        dna = self.builder \
            .set_info(media_info["music_metadata"], media_info["original_url"]) \
            .set_physical_cuts(physical_cuts) \
            .set_audio_features(beats) \
            .ingest_complex_metadata(complex_result.get("metadata", {})) \
            .build()

        return dna