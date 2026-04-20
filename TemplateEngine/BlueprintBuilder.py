import json

class BlueprintBuilder:
    """
    Builder Pattern: 逐步建構 template_dna.json。
    """
    def __init__(self):
        self._dna = {
            "template_info": {},
            "visual_cuts": [],
            "audio_beats": {},
            "cinematic_style": {},
            "is_audio_essential": False
        }

    def set_info(self, metadata: str, url: str):
        self._dna["template_info"] = {"music": metadata, "source": url}
        return self

    def set_cuts(self, cuts: list):
        self._dna["visual_cuts"] = cuts
        return self

    def set_audio_features(self, features: dict):
        self._dna["audio_beats"] = features
        return self

    def set_style(self, style: dict):
        self._dna["cinematic_style"] = style
        # 根據 Gemini 的分析結果決定是否保留原音軌
        # 這裡的邏輯可以根據 StyleReverseEngineer 的回傳進一步細化
        return self

    def build(self) -> dict:
        # 在這裡可以實作校準邏輯：例如過濾掉與音樂節拍完全不對齊的微小切點
        return self._dna