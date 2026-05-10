import os
from MediaTools.MediaDownloader import MediaDownloader
from MediaTools.FFmpegAdapter import FFmpegAdapter
from MediaTools.AudioBeatExtractor import AudioBeatExtractor
from MusicEngine.LyricsAdapter import LyricsAdapter

class MusicEngineFacade:
    """
    Facade Pattern: Phase 3 音樂引擎指揮官。
    統一對外提供三種音樂取得管道：
      - fetch_and_analyze()：yt-dlp 搜尋下載（情境1，含版權）
      - fetch_free_music()：JamendoAdapter 搜尋（情境3，無版權）
      - use_local_audio()：直接使用用戶上傳的本地檔案（情境2 方案1）
    歌詞走 Chain of Responsibility：LRClib → VAD + Whisper。
    """
    def __init__(self):
        self.downloader = MediaDownloader()
        self.ffmpeg = FFmpegAdapter()
        self.beat_extractor = AudioBeatExtractor()
        # LyricsAdapter 是純 HTTP client，不耗 VRAM，eager init
        self.lyrics_adapter = LyricsAdapter()

        # 延遲載入 AI 大腦，節省啟動時的 VRAM
        self._whisper = None
        self._vad = None

    @property
    def whisper_engine(self):
        if self._whisper is None:
            from Model.WhisperModelManager import WhisperModelManager
            self._whisper = WhisperModelManager()
        return self._whisper

    @property
    def vad_engine(self):
        if self._vad is None:
            from Model.VadModelManager import VadModelManager
            self._vad = VadModelManager()
        return self._vad

    def fetch_and_analyze(self, query: str) -> dict:
        """
        一鍵式工作流：搜尋 -> 下載 -> 標準化 -> 節拍分析 -> 歌詞分析 -> 封裝 DNA。
        歌詞分析路徑：LRClib（query 直查歌詞 DB）→ Whisper transcribe（fallback）。
        """
        print(f"[MusicEngine] 開始處理音樂請求: {query}")

        # 1. 動態直取 (yt-dlp 搜尋與下載)
        raw_audio_path = self.downloader.search_and_download_audio(query)

        # 建立標準化的分析路徑 (16kHz, Mono WAV)
        base_name = os.path.splitext(os.path.basename(raw_audio_path))[0]
        standard_wav_path = os.path.join(os.path.dirname(raw_audio_path), f"{base_name}_std.wav")

        try:
            # 2. 音訊標準化 (呼叫 FFmpegAdapter)
            # 使用 extract_ai_audio 確保輸出符合 Whisper 與音訊處理標準
            self.ffmpeg.extract_ai_audio(raw_audio_path, standard_wav_path)

            # 3. 物理特徵萃取 (DSP: BPM, Beats, Onsets)
            audio_beats = self.beat_extractor.get_beats(standard_wav_path)

            # 4. 語意層（NLP: Lyrics with Timestamps）：先試歌詞 DB，失敗才走 Whisper
            lyrics_data = self._fetch_lyrics(query, standard_wav_path)

            # 5. 封裝 Audio DNA
            # 此結構將直接餵給 Phase 4 的 Director LLM 進行剪輯決策
            audio_dna = {
                "status": "success",
                "query": query,
                "local_path": {
                    "raw": raw_audio_path,
                    "standard": standard_wav_path
                },
                "analysis": {
                    "bpm": audio_beats.get("bpm"),
                    "beats": audio_beats.get("beats"),
                    "onsets": audio_beats.get("onsets"),
                    "lyrics": lyrics_data.get("chunks", []),
                    "full_lyrics_text": lyrics_data.get("text", ""),
                    "lyrics_source": lyrics_data.get("source", "unknown"),
                }
            }

            print(
                f"[MusicEngine] Audio DNA 萃取完成！"
                f"(BPM: {audio_dna['analysis']['bpm']}, lyrics: {audio_dna['analysis']['lyrics_source']})"
            )
            return audio_dna

        except Exception as e:
            print(f"[MusicEngine Error] 流程中斷: {e}")
            return {"status": "error", "message": str(e)}

    def use_local_audio(self, file_path: str) -> dict:
        """
        直接使用本地音訊檔（用戶上傳），跳過下載步驟。
        後續流程與 fetch_and_analyze() 相同：標準化 → beats → lyrics。
        """
        print(f"[MusicEngine] 使用本地音訊: {file_path}")

        if not os.path.exists(file_path):
            return {"status": "error", "message": f"找不到音訊檔案: {file_path}"}

        base_name = os.path.splitext(os.path.basename(file_path))[0]
        standard_wav_path = os.path.join(os.path.dirname(file_path), f"{base_name}_std.wav")

        try:
            self.ffmpeg.extract_ai_audio(file_path, standard_wav_path)
            audio_beats = self.beat_extractor.get_beats(standard_wav_path)

            # 以檔名作為歌詞查詢提示（鼓勵用戶命名為「歌手 歌名」格式）
            query_hint = os.path.splitext(os.path.basename(file_path))[0]
            lyrics_data = self._fetch_lyrics(query_hint, standard_wav_path)

            print(f"[MusicEngine] 本地音訊處理完成！(BPM: {audio_beats.get('bpm')})")
            return {
                "status": "success",
                "query": query_hint,
                "source": "user_upload",
                "local_path": {"raw": file_path, "standard": standard_wav_path},
                "analysis": {
                    "bpm": audio_beats.get("bpm"),
                    "beats": audio_beats.get("beats"),
                    "onsets": audio_beats.get("onsets"),
                    "lyrics": lyrics_data.get("chunks", []),
                    "full_lyrics_text": lyrics_data.get("text", ""),
                    "lyrics_source": lyrics_data.get("source", "unknown"),
                }
            }
        except Exception as e:
            print(f"[MusicEngine Error] 本地音訊處理失敗: {e}")
            return {"status": "error", "message": str(e)}

    def fetch_free_music(self, query: str) -> dict:
        """
        取得無版權音樂（情境3）。
        Chain of Responsibility：優先走 JamendoAdapter，失敗時 fallback 至 yt-dlp 無版權搜尋。
        """
        print(f"[MusicEngine] 開始搜尋免費音樂: {query}")

        music_dir = os.path.join("temp_templates", "music_cache")
        os.makedirs(music_dir, exist_ok=True)

        source_tag = "jamendo"
        try:
            from MusicEngine.JamendoAdapter import JamendoAdapter
            raw_audio_path = JamendoAdapter().search_and_download(query, music_dir)
        except Exception as e:
            print(f"[MusicEngine] Jamendo 失敗 ({e})，回退至 yt-dlp 無版權搜尋")
            raw_audio_path = self.downloader.search_and_download_audio(
                f"{query} no copyright free music"
            )
            source_tag = "yt_free"

        base_name = os.path.splitext(os.path.basename(raw_audio_path))[0]
        standard_wav_path = os.path.join(os.path.dirname(raw_audio_path), f"{base_name}_std.wav")

        try:
            self.ffmpeg.extract_ai_audio(raw_audio_path, standard_wav_path)
            audio_beats = self.beat_extractor.get_beats(standard_wav_path)
            lyrics_data = self._fetch_lyrics(query, standard_wav_path)

            audio_dna = {
                "status": "success",
                "query": query,
                "source": source_tag,
                "local_path": {"raw": raw_audio_path, "standard": standard_wav_path},
                "analysis": {
                    "bpm": audio_beats.get("bpm"),
                    "beats": audio_beats.get("beats"),
                    "onsets": audio_beats.get("onsets"),
                    "lyrics": lyrics_data.get("chunks", []),
                    "full_lyrics_text": lyrics_data.get("text", ""),
                    "lyrics_source": lyrics_data.get("source", "unknown"),
                }
            }
            print(
                f"[MusicEngine] 免費音樂取得完成！"
                f"(來源: {source_tag}, BPM: {audio_dna['analysis']['bpm']})"
            )
            return audio_dna

        except Exception as e:
            print(f"[MusicEngine Error] 免費音樂處理失敗: {e}")
            return {"status": "error", "message": str(e)}

    def _fetch_lyrics(self, query: str, fallback_audio_path: str) -> dict:
        """
        Chain of Responsibility：依序嘗試多個歌詞來源，第一個成功即停止。
          路 1：LRClib（query 直查歌詞 DB，含時間戳）
          路 2：VAD 把關 + Whisper transcribe（純人聲偵測過後再轉錄）
        路 1 命中即停止，路 2 才會耗 GPU；查無人聲時連 Whisper 都不啟動。
        """
        # 路 1：LRClib 歌詞 DB（無 GPU 成本）
        lyrics_from_db = self.lyrics_adapter.fetch_synced_lyrics(query)
        if lyrics_from_db:
            return lyrics_from_db

        # 路 2：VAD 防衛 → Whisper 聽寫
        print(f"[MusicEngine] LRClib 無命中，回退至 Whisper transcribe...")
        if not self.vad_engine.has_speech(fallback_audio_path):
            print(f"[MusicEngine] 判定為純配樂/環境音，跳過聽寫流程。")
            return {"chunks": [], "text": "", "source": "vad_silent"}

        print(f"[MusicEngine] 偵測到人聲內容，啟動 Whisper 聽寫...")
        whisper_result = self.whisper_engine.transcribe(fallback_audio_path)
        return {
            "chunks": whisper_result.get("chunks", []),
            "text": whisper_result.get("text", ""),
            "source": "whisper",
        }