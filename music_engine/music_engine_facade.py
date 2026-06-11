import os
from media_tools.media_downloader import MediaDownloader
from media_tools.ffmpeg_adapter import FFmpegAdapter
from media_tools.audio_beat_extractor import AudioBeatExtractor
from media_processor.pipeline.executor.model_pool_registry import borrow_for_batch, run_vad
from media_processor.pipeline.progress import ProgressTracker, stage_span
from model.managers.whisper_model_manager import WhisperModelManager

# 歌詞聽寫向共享 GPU 池借出 Whisper 時的 stage 名稱(供 borrow 等待事件標示,禁 magic string)
_MUSIC_LYRICS_STAGE = "music_lyrics"
# music 分支對前端可見的工作步驟 stage 名稱(下載 / 節拍);music 無真 asset,用合成 id 供事件歸屬
_MUSIC_STAGE_DOWNLOAD = "music_download"
_MUSIC_STAGE_BEATS = "music_beats"
_MUSIC_ASSET_ID = "music"

class MusicEngineFacade:
    """
    Facade Pattern: Phase 3 音樂引擎指揮官。
    統一對外提供三種音樂取得管道：
      - fetch_and_analyze()：yt-dlp 搜尋下載（情境1，含版權）
      - fetch_free_music()：JamendoAdapter 搜尋（情境3，無版權）
      - use_local_audio()：直接使用用戶上傳的本地檔案（情境2 方案1）
    歌詞一律走 VAD + Whisper（直接轉錄手上音檔，時間戳與音訊天然對齊）。
    """
    def __init__(self):
        self.downloader = MediaDownloader()
        self.ffmpeg = FFmpegAdapter()
        self.beat_extractor = AudioBeatExtractor()
        # AI 大腦(Whisper / VAD)不再自建 singleton:改向共享 ModelPoolRegistry borrow,
        # 與 template 分支共用同一 GpuGate / VRAM 預算,並行不撞車(見 docs §5)。

    def fetch_and_analyze(self, query: str, tracker: ProgressTracker | None = None) -> dict:
        """
        一鍵式工作流：搜尋 -> 下載 -> 標準化 -> 節拍分析 -> 歌詞分析 -> 封裝 DNA。
        歌詞分析路徑：LRClib（query 直查歌詞 DB）→ Whisper transcribe（fallback）。
        tracker 非 None 時於下載 / 節拍 / 聽寫三步發 STAGE_*,讓前端看到「下載中 / 分析節拍中 / 聽寫中」。
        """
        print(f"[music_engine] 開始處理音樂請求: {query}")

        # 1. 動態直取 (yt-dlp 搜尋與下載)
        with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_STAGE_DOWNLOAD):
            raw_audio_path = self.downloader.search_and_download_audio(query)

        # 建立標準化的分析路徑 (16kHz, Mono WAV)
        base_name = os.path.splitext(os.path.basename(raw_audio_path))[0]
        standard_wav_path = os.path.join(os.path.dirname(raw_audio_path), f"{base_name}_std.wav")

        try:
            # 2. 音訊標準化 (呼叫 FFmpegAdapter)
            # 使用 extract_ai_audio 確保輸出符合 Whisper 與音訊處理標準
            self.ffmpeg.extract_ai_audio(raw_audio_path, standard_wav_path)

            # 3. 物理特徵萃取 (DSP: BPM, Beats, Onsets)
            with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_STAGE_BEATS):
                audio_beats = self.beat_extractor.get_beats(standard_wav_path)

            # 4. 語意層（NLP: Lyrics with Timestamps）：先試歌詞 DB，失敗才走 Whisper
            lyrics_data = self._fetch_lyrics(query, standard_wav_path, tracker)

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
                f"[music_engine] Audio DNA 萃取完成！"
                f"(BPM: {audio_dna['analysis']['bpm']}, lyrics: {audio_dna['analysis']['lyrics_source']})"
            )
            return audio_dna

        except Exception as e:
            print(f"[music_engine Error] 流程中斷: {e}")
            return {"status": "error", "message": str(e)}

    def use_local_audio(self, file_path: str, tracker: ProgressTracker | None = None) -> dict:
        """
        直接使用本地音訊檔（用戶上傳），跳過下載步驟。
        後續流程與 fetch_and_analyze() 相同：標準化 → beats → lyrics（tracker 非 None 時發節拍 / 聽寫 STAGE_*）。
        """
        print(f"[music_engine] 使用本地音訊: {file_path}")

        if not os.path.exists(file_path):
            return {"status": "error", "message": f"找不到音訊檔案: {file_path}"}

        base_name = os.path.splitext(os.path.basename(file_path))[0]
        standard_wav_path = os.path.join(os.path.dirname(file_path), f"{base_name}_std.wav")

        try:
            self.ffmpeg.extract_ai_audio(file_path, standard_wav_path)
            with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_STAGE_BEATS):
                audio_beats = self.beat_extractor.get_beats(standard_wav_path)

            # 以檔名作為歌詞查詢提示（鼓勵用戶命名為「歌手 歌名」格式）
            query_hint = os.path.splitext(os.path.basename(file_path))[0]
            lyrics_data = self._fetch_lyrics(query_hint, standard_wav_path, tracker)

            print(f"[music_engine] 本地音訊處理完成！(BPM: {audio_beats.get('bpm')})")
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
            print(f"[music_engine Error] 本地音訊處理失敗: {e}")
            return {"status": "error", "message": str(e)}

    def fetch_free_music(self, query: str, tracker: ProgressTracker | None = None) -> dict:
        """
        取得無版權音樂（情境3）。
        Chain of Responsibility：優先走 JamendoAdapter，失敗時 fallback 至 yt-dlp 無版權搜尋。
        tracker 非 None 時於下載 / 節拍 / 聽寫三步發 STAGE_*（Jamendo→yt-dlp 的回退屬同一下載 stage 內）。
        """
        print(f"[music_engine] 開始搜尋免費音樂: {query}")

        music_dir = os.path.join("temp_templates", "music_cache")
        os.makedirs(music_dir, exist_ok=True)

        source_tag = "jamendo"
        # Jamendo→yt-dlp 的回退視為同一個「下載」stage:整段成功才 FINISH,皆失敗才 ERROR
        with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_STAGE_DOWNLOAD):
            try:
                from music_engine.jamendo_adapter import JamendoAdapter
                raw_audio_path = JamendoAdapter().search_and_download(query, music_dir)
            except Exception as e:
                print(f"[music_engine] Jamendo 失敗 ({e})，回退至 yt-dlp 無版權搜尋")
                raw_audio_path = self.downloader.search_and_download_audio(
                    f"{query} no copyright free music"
                )
                source_tag = "yt_free"

        base_name = os.path.splitext(os.path.basename(raw_audio_path))[0]
        standard_wav_path = os.path.join(os.path.dirname(raw_audio_path), f"{base_name}_std.wav")

        try:
            self.ffmpeg.extract_ai_audio(raw_audio_path, standard_wav_path)
            with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_STAGE_BEATS):
                audio_beats = self.beat_extractor.get_beats(standard_wav_path)
            lyrics_data = self._fetch_lyrics(query, standard_wav_path, tracker)

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
                f"[music_engine] 免費音樂取得完成！"
                f"(來源: {source_tag}, BPM: {audio_dna['analysis']['bpm']})"
            )
            return audio_dna

        except Exception as e:
            print(f"[music_engine Error] 免費音樂處理失敗: {e}")
            return {"status": "error", "message": str(e)}

    def _fetch_lyrics(self, query: str, fallback_audio_path: str,
                      tracker: ProgressTracker | None = None) -> dict:
        """
        歌詞解析：VAD 把關 + Whisper transcribe（直接轉錄手上音檔）。

        原 LRClib 歌詞 DB 路徑已移除：眾包同步歌詞對的是另一個版本，時間戳常與我們實際播放的
        音檔系統性偏移；改為一律以 Whisper 轉錄實體音檔，時間戳本質上與音訊對齊、不會錯。
        ``query`` 保留於簽章供呼叫端相容（歌名提示），目前不再用於 DB 查詢。查無人聲時連 Whisper
        都不啟動（回 ``vad_silent``）。整段以 ``music_lyrics`` stage 包覆，前端看到「聽寫中」。
        """
        with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_LYRICS_STAGE):
            # VAD 防衛(borrow 共享 CPU 池,與 pipeline VAD 同池):純配樂 / 環境音直接跳過,省 GPU
            if not run_vad(lambda v: v.has_speech(fallback_audio_path)):
                print(f"[music_engine] 判定為純配樂/環境音，跳過聽寫流程。")
                return {"chunks": [], "text": "", "source": "vad_silent"}

            # 偵測到人聲：borrow 共享 GPU 池做 Whisper 聽寫(與 template 分支共用 GpuGate / VRAM 預算)
            print(f"[music_engine] 偵測到人聲內容，啟動 Whisper 聽寫...")
            whisper_result = borrow_for_batch(
                WhisperModelManager,
                _MUSIC_LYRICS_STAGE,
                lambda m: m.transcribe(fallback_audio_path),
            )
            return {
                "chunks": whisper_result.get("chunks", []),
                "text": whisper_result.get("text", ""),
                "source": "whisper",
            }