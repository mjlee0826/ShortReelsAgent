import json

class BlueprintBuilder:
    """
    Builder Pattern: 將 ComplexVideoProcessor 的素材特徵轉化為 Template DNA。
    """
    def __init__(self):
        self._dna = {
            "template_info": {},
            "visual_cuts": [],       # 最終合併後的剪輯點
            "audio_beats": {},
            "cinematic_style": {},
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
        # 1. 轉入語意風格與逐字稿
        self._dna["cinematic_style"] = metadata.get("cinematic_style", {})
        self._dna["audio_transcript"] = metadata.get("audio_transcript", {})
        
        # 2. 判斷聲音重要性 (如果有逐字稿或環境音描述很豐富，設為 True)
        transcript_text = self._dna["audio_transcript"].get("text", "")
        self._dna["is_audio_essential"] = len(transcript_text) > 5
        
        # 3. 語意切點補足邏輯
        # 如果物理切點 (visual_cuts) 為空，我們從 multimodal_event_index 提取 start_time
        semantic_events = metadata.get("multimodal_event_index", [])
        if not self._dna["visual_cuts"] and semantic_events:
            print("[Builder] 偵測到一鏡到底，正在將語意事件轉換為剪輯切點...")
            # 排除 0.0，將每個事件的起點視為一個潛在的切點
            semantic_cuts = [float(e["start_time"]) for e in semantic_events if float(e["start_time"]) > 0]
            self._dna["visual_cuts"] = sorted(list(set(semantic_cuts)))
            
        return self

    def set_physical_cuts(self, physical_cuts: list):
        """
        如果有物理切點，則優先使用物理切點。
        """
        if physical_cuts:
            self._dna["visual_cuts"] = physical_cuts
        return self

    def build(self) -> dict:
        return self._dna