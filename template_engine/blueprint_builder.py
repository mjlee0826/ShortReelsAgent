import copy


class BlueprintBuilder:
    """
    Builder Pattern: 把範本影片的精簡感知訊號組裝成輕量 Template DNA。

    範本的視覺理解改由導演 ``view_template`` 親眼看原始幀(見 media_processor 的 TEMPLATE DAG),
    故 DNA 不再承載 Gemini 文字評論 / 逐字稿 / 事件索引 / 配樂偵測等重欄位,只留:
      - 導演視覺還原不了的物理訊號(剪輯切點 visual_cuts、節奏 bpm、總長 duration)
      - view_template 解析原始影片所需的實體路徑(local_assets.original_video)
      - 來源資訊(template_info:yt-dlp 帶出的歌名提示與原始 URL,免費附帶)
    """
    def __init__(self):
        self._dna = {
            # yt-dlp 帶出的來源資訊:music 為歌名提示(非可播放音檔)、source 為原始 URL
            "template_info": {},
            # view_template 需要原始影片實體路徑來抓幀
            "local_assets": {"original_video": ""},
            # 場景物理切點(秒):範本剪輯節奏,供導演取樣 / 卡點參考
            "visual_cuts": [],
            # 範本總長(秒)
            "duration": 0.0,
            # librosa 估的範本節奏 BPM(風格參考;實際 BGM 卡點仍以選定配樂的 beats 為準)
            "bpm": None,
        }

    def set_info(self, music_metadata: str, url: str):
        """寫入來源資訊(yt-dlp 歌名提示 + 原始 URL)。"""
        self._dna["template_info"] = {"music": music_metadata, "source": url}
        return self

    def set_local_assets(self, original_video: str):
        """寫入原始影片實體路徑,供 view_template 抓幀。"""
        self._dna["local_assets"] = {"original_video": original_video}
        return self

    def set_physical_cuts(self, physical_cuts: list):
        """寫入場景物理切點(空清單時不覆寫,保留預設空陣列)。"""
        if physical_cuts:
            self._dna["visual_cuts"] = physical_cuts
        return self

    def set_duration(self, duration: float):
        """寫入範本總長(秒)。"""
        self._dna["duration"] = duration or 0.0
        return self

    def set_bpm(self, bpm):
        """寫入 librosa 估的節奏 BPM(可能為 None,代表未測得)。"""
        self._dna["bpm"] = bpm
        return self

    def build(self) -> dict:
        """產出 Template DNA 的深拷貝(避免外部就地改動 builder 內部狀態)。"""
        return copy.deepcopy(self._dna)
