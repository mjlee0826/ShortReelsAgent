from TemplateEngine.MediaDownloader import MediaDownloader
from TemplateEngine.MediaDemuxer import MediaDemuxer
from TemplateEngine.SceneCutExtractor import SceneCutExtractor
from TemplateEngine.AudioBeatExtractor import AudioBeatExtractor
from TemplateEngine.StyleReverseEngineer import StyleReverseEngineer
from TemplateEngine.BlueprintBuilder import BlueprintBuilder

class TemplateAnalyzerFacade:
    """
    Facade Pattern: Phase 2 的最高指揮官。
    """
    def __init__(self):
        self.downloader = MediaDownloader()
        self.demuxer = MediaDemuxer()
        self.cut_extractor = SceneCutExtractor()
        self.beat_extractor = AudioBeatExtractor()
        self.style_engineer = StyleReverseEngineer()
        self.builder = BlueprintBuilder()

    def extract_dna(self, input_source: str) -> dict:
        """
        一鍵提取影片 DNA 的唯一入口。
        """
        # 1. 獲取
        media_info = self.downloader.fetch_video(input_source)
        video_file = media_info["video_path"]

        # 2. 剝離軌道
        v_only, a_only = self.demuxer.extract_tracks(video_file)

        # 3. 物理分析
        cuts = self.cut_extractor.get_cuts(v_only)
        beats = self.beat_extractor.get_beats(a_only)

        # 4. 語意逆向
        style = self.style_engineer.reverse_style(video_file)

        # 5. 建構與封裝
        dna = self.builder \
            .set_info(media_info["music_metadata"], media_info["original_url"]) \
            .set_cuts(cuts) \
            .set_audio_features(beats) \
            .set_style(style) \
            .build()

        return dna