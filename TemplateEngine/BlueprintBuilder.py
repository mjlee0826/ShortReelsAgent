import json

class BlueprintBuilder:
    """
    Builder Pattern: 將 ComplexVideoProcessor 的素材特徵轉化為 Template DNA。
    """
    def __init__(self):
        self._dna = {
            "template_info": {},
            "visual_cuts": [],       
            "audio_beats": {},
            "cinematic_critique": "",
            # 【核心新增】保留 Template 每一段的語意劇本 (視覺層、聽覺層、關鍵高潮點)
            "multimodal_event_index": [], 
            "audio_transcript": {},
            "is_audio_essential": False
        }

    def set_info(self, music_metadata: str, url: str):
        self._dna["template_info"] = {"music": music_metadata, "source": url}
        return self

    def set_audio_features(self, beats: dict):
        self._dna["audio_beats"] = beats
        return self

    def ingest_complex_metadata(self, metadata: dict):
        """
        核心邏輯：從 ComplexVideoProcessor 的輸出中萃取 DNA。
        """
        # 1. 轉入全局評論與逐字稿 (加上最強防呆)
        self._dna["cinematic_critique"] = metadata.get("cinematic_critique", "")
        self._dna["audio_transcript"] = metadata.get("audio_transcript") or {}
        
        # 2. 判斷聲音重要性 (如果有逐字稿，設為 True)
        transcript_text = self._dna["audio_transcript"].get("text", "")
        self._dna["is_audio_essential"] = len(transcript_text) > 5
        
        # 3. 轉入多模態事件索引 (完整劇本保留)
        semantic_events = metadata.get("multimodal_event_index", [])
        self._dna["multimodal_event_index"] = semantic_events
        
        # 4. 語意切點補足邏輯 (拯救一鏡到底的影片)
        # 如果物理切點是空的，我們就利用上面的 semantic_events 來生成切點
        if not self._dna["visual_cuts"] and semantic_events:
            print("[Builder] 偵測到一鏡到底，正在將語意事件轉換為剪輯切點...")
            # 排除 0.0，將每個事件的起點視為一個潛在的切點
            semantic_cuts = [float(e["start_time"]) for e in semantic_events if float(e["start_time"]) > 0]
            self._dna["visual_cuts"] = sorted(list(set(semantic_cuts)))
            
        return self

    def set_physical_cuts(self, physical_cuts: list):
        if physical_cuts:
            self._dna["visual_cuts"] = physical_cuts
        return self

    def build(self) -> dict:
        return self._dna