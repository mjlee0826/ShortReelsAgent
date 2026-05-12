import copy
import json

class BlueprintBuilder:
    """
    Builder Pattern: 將 ComplexVideoProcessor 的素材特徵轉化為 Template DNA。
    """
    def __init__(self):
        self._dna = {
            "template_info": {},
            # 【新增】記錄實體檔案在 Server / 工作站上的絕對路徑
            "local_assets": {
                "original_video": "",
                "video_only": "",
                "audio_only": ""
            },
            "visual_cuts": [],       
            "audio_beats": {},
            "cinematic_critique": "",
            "multimodal_event_index": [], 
            "audio_transcript": {},
            "is_audio_essential": False
        }

    def set_info(self, music_metadata: str, url: str):
        self._dna["template_info"] = {"music": music_metadata, "source": url}
        return self

    # 【新增】將路徑寫入藍圖的方法
    def set_local_assets(self, original_video: str, video_only: str, audio_only: str):
        self._dna["local_assets"] = {
            "original_video": original_video,
            "video_only": video_only,
            "audio_only": audio_only
        }
        return self

    def set_audio_features(self, beats: dict):
        self._dna["audio_beats"] = beats
        return self

    def ingest_complex_metadata(self, metadata: dict):
        self._dna["cinematic_critique"] = metadata.get("cinematic_critique", "")
        self._dna["audio_transcript"] = metadata.get("audio_transcript") or {}
        
        transcript_text = self._dna["audio_transcript"].get("text", "")
        self._dna["is_audio_essential"] = len(transcript_text) > 5
        
        semantic_events = metadata.get("multimodal_event_index", [])
        self._dna["multimodal_event_index"] = semantic_events
        
        if not self._dna["visual_cuts"] and semantic_events:
            print("[Builder] 偵測到一鏡到底，正在將語意事件轉換為剪輯切點...")
            semantic_cuts = [float(e["start_time"]) for e in semantic_events if float(e["start_time"]) > 0]
            self._dna["visual_cuts"] = sorted(list(set(semantic_cuts)))
            
        return self

    def set_physical_cuts(self, physical_cuts: list):
        if physical_cuts:
            self._dna["visual_cuts"] = physical_cuts
        return self

    def build(self) -> dict:
        return copy.deepcopy(self._dna)