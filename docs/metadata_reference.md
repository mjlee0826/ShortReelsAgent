# Metadata 參考文件

本文件記錄五類素材經感知分析後產出的 metadata：**欄位 / 格式 / 內容 / 由誰取得 / ContextCompressor 是否丟棄**。
反映「LRClib 移除 + Complex 音訊改 Gemini + Template 深分 + ContextCompressor 重定位」後的狀態。

## 全局觀念（先讀這段）

- **ContextCompressor 只作用在使用者素材**（Image / Video / Complex Video，即 `raw_assets`）。它做兩件事：
  1. **寬容過濾閘** `_is_low_quality`：只有「技術分 AND 美學分**雙低**」才剔除（任一缺值即放行）。
  2. **塑形降維**：改短鍵、壓縮候選主體，輸出乾淨 JSON 給導演 LLM。
- **Template 與 Music 不經 ContextCompressor**：
  - Template → `BlueprintBuilder` 組成 `template_dna`，整包當「範本 DNA」進導演 prompt。
  - Music → `MusicEngineFacade` 組成 `audio_dna`，整包當「配樂 DNA」進導演 prompt。
- **`COMPLEX_AUDIO_VIA_GEMINI`（env 旗標，預設 True）** 決定 Complex 影片四個音訊欄位的來源：
  - True：Gemini 在 `VIDEO_EVENT_INDEX` 一併輸出（不建 VAD/Whisper/AudioEnv 音訊鏈）。
  - False：回退原 `VAD(Silero) → Whisper(faster-whisper) → AudioEnv(PANNs CNN14)` 鏈。
  - 兩種來源寫進的欄位結構相同，下游（assembly / compressor）無感。

來源（Stage / 模型）對照：DecodeImage/DecodeVideo(cv2 + ffprobe)、TechScore(**MUSIQ**)、AesScore(**LAION**)、CVFeatures(cv2/PIL/KMeans)、FaceDetect(**MediaPipe**)、Exif、SemanticImage/Video(**Qwen** 本地 / **Gemini** 雲端)、SceneCut(**PySceneDetect**)、MotionIntensity(cv2)、VAD(**Silero**)、Whisper(**faster-whisper**)、AudioEnv(**PANNs CNN14**)、AudioBeat(**librosa**)、MediaDownloader(**yt-dlp**)。

---

## ① Image（`ImageMetadata`；本次未改）

| 欄位 | 格式 | 內容 | 來源 | ContextCompressor |
|---|---|---|---|---|
| width / height | int | 像素寬高 | DecodeImage | 保留→`res.w/h` |
| aspect_ratio | float | 寬高比 | DecodeImage | **丟棄**（可由 w/h 算） |
| creation_time | str | 拍攝時間 | Exif | 保留→`time` |
| location_gps | str | GPS | Exif | 保留→`geo` |
| caption | str | 客觀內容描述 | SemanticImage(Qwen/Gemini) | 保留→`cap` |
| cinematic_critique | str | 攝影評論 | SemanticImage | 保留→`critique` |
| mood | str | 情緒（列舉） | SemanticImage | 保留→`mood` |
| scene_tags | list[str] | 場景標籤 | SemanticImage | 保留→`scene_tags` |
| camera_angle | str | 鏡頭視角 | SemanticImage | 保留→`cam` |
| action_tags | list[str] | 動作標籤 | SemanticImage | 保留→`actions` |
| time_of_day | str | 時段 | SemanticImage | 保留→`tod` |
| technical_score | float | MUSIQ 技術畫質分 | TechScore | 保留→`tech`（+ 供過濾閘） |
| aesthetic_score | float | LAION 美學分 | AesScore | 保留→`aes`（+ 供過濾閘） |
| brightness | float | 平均亮度 0–100 | CVFeatures | 保留→`bright` |
| color_temperature | str | warm/cool/neutral | CVFeatures | 保留→`color_temp` |
| dominant_colors | list[str] | 主色 hex | CVFeatures | 保留→`colors` |
| subject_bbox | `{x1,y1,x2,y2}`(0–100) | 最佳主體框 | SemanticImage + assembly | 保留→`bbox` |
| subject_candidates | list[`{bbox,label,confidence}`] | top-N 候選主體 | SemanticImage | 保留→`subjects`（≥1 即帶） |
| crop_feasibility | str | full/... 可裁性 | assembly | 保留→`crop` |
| faces | `{face_count,has_faces,largest_face_ratio}` | 臉部摘要 | FaceDetect | 有臉→`face_count`+`face_ratio`（`has_faces` 隱含） |

---

## ② Video / Simple（`VideoMetadata`；本次未改）

含 Image 的所有「視覺 / 品質 / 主體 / 臉部」欄位（來源與 compressor 處置同上），外加影片專屬：

| 欄位 | 格式 | 內容 | 來源 | ContextCompressor |
|---|---|---|---|---|
| duration / fps | float | 時長 / 幀率 | DecodeVideo | 保留→`dur`/`fps` |
| creation_time / location_gps | str | 拍攝時間 / GPS | DecodeVideo（ffprobe 容器標籤，**非 EXIF**） | 保留→`time`/`geo` |
| has_speech | bool | 是否有人聲 | VAD(Silero) | 保留→`has_speech` |
| spoken_language | str | 語言代碼 | Whisper | 保留→`lang` |
| audio_transcript | `{text, language, chunks:[{text,timestamp:[s,e]}]}` | 逐字稿（含逐句時間戳） | Whisper(faster-whisper) | 保留→`audio.transcript`（**完整**，含 chunks） |
| environmental_sounds | list[`{label,score}`] | 環境音分類 | AudioEnv(PANNs CNN14) | 保留→`audio.env` |
| motion_intensity | str | static/moderate/dynamic | MotionIntensity(cv2) | 保留→`motion` |
| scene_cuts | list[float] | 場景切點(秒) | SceneCut(PySceneDetect) | 保留→`cuts` |
| 語意群 caption/cinematic_critique/... | — | 同 Image | SemanticVideo(**Qwen** 全局) | 同 Image |

---

## ③ Complex Video（`ComplexVideoMetadata`；**WS2 改：音訊欄位換來源**）

無 caption / subject_bbox / faces / motion_intensity（改以事件索引為主）。

| 欄位 | 格式 | 內容 | 來源 | ContextCompressor |
|---|---|---|---|---|
| width.../duration/fps/creation_time/gps | — | 基本 metadata | DecodeVideo | 保留（`res`/`dur`/`fps`/`time`/`geo`） |
| has_speech | bool | 是否有人聲 | **Gemini**(旗標開) / VAD(旗標關) | 保留→`has_speech` |
| spoken_language | str | 語言代碼 | **Gemini** / Whisper | 保留→`lang` |
| audio_transcript | `{text,language,chunks:[{text,timestamp:[s,e]}]}` | 逐字稿 | **Gemini** / Whisper | 保留→`audio.transcript`（完整） |
| environmental_sounds | list[`{label,score}`] | 環境音 | **Gemini** / AudioEnv | 保留→`audio.env` |
| cinematic_critique | str | 全局攝影評論 | Gemini(TIMECODED) | 保留→`critique` |
| mood/scene_tags/camera_angle/action_tags/time_of_day | — | 全局語意 | Gemini | `mood`/`scene_tags`/`cam`/`actions`/`tod` 保留 |
| technical_score / aesthetic_score | float | 代表幀畫質 / 美學 | MUSIQ / LAION | `tech`/`aes` 保留 |
| brightness/color_temperature/dominant_colors | — | 視覺特徵 | CVFeatures | `bright`/`color_temp`/`colors` 保留 |
| is_dense_indexed | bool=True | 是否密集索引 | assembly | 保留→`is_complex` |
| scene_cuts | list[float] | 場景切點 | SceneCut | 保留→`cuts` |
| multimodal_event_index | list[`{start_time,end_time,visual_layer,audio_layer,key_timestamp,subject_bbox,subject_candidates,mood,action_tags}`] | 逐段視聽事件 | Gemini | 保留→`events`（整包） |

> 旗標開時，Gemini 產出的音訊欄位由 `SemanticVideoStage._apply_gemini_audio` 寫回 `VideoWork`，`AssemblyVideoStage` 來源透明、不需改。

---

## ④ Template（`TemplateVideoMetadata` → `template_dna`；**WS3 新增；不經 compressor**）

走 `VideoStrategy.TEMPLATE` 精簡 DAG（decode + scene + Gemini 範本語意），砍掉音訊鏈與品質/臉部評分。
最終 `template_dna` 由兩段拼成：

**(a) Gemini `TEMPLATE_ANALYSIS` 產出（寫進 `TemplateVideoMetadata`）**

| 欄位 | 格式 | 內容 | 來源 |
|---|---|---|---|
| width/height/aspect_ratio/duration/fps/creation_time/location_gps | — | 基本 metadata | DecodeVideo |
| cinematic_critique / mood / scene_tags / action_tags | — | 全局風格語意 | Gemini(TEMPLATE_ANALYSIS) |
| audio_transcript | `{text,language,chunks:[...]}` | 逐字稿（推 `is_audio_essential`） | Gemini(TEMPLATE_ANALYSIS) |
| **music_analysis** | `{music_style, genre, mood, has_vocals, song_guess:{title,artist,confidence}}` | **範本配樂偵測**（曲風 / 歌名猜測） | Gemini(TEMPLATE_ANALYSIS) |
| scene_cuts | list[float] | 物理切點 | SceneCut(PySceneDetect) |
| multimodal_event_index | list[`{start_time,end_time,visual_layer,audio_layer,key_timestamp,mood,action_tags}`] | 逐段視聽事件 | Gemini(TEMPLATE_ANALYSIS) |

**(b) `BlueprintBuilder` 後處理補上（`template_dna` 額外鍵）**

| `template_dna` 鍵 | 格式 | 內容 | 來源 |
|---|---|---|---|
| template_info.music | str | **權威歌名**（IG/TikTok track） | MediaDownloader(yt-dlp) |
| template_info.source | str | 原始 URL | MediaDownloader |
| audio_beats | `{bpm,beats,onsets}` | 物理節奏 | AudioBeat(librosa) |
| local_assets | `{original_video,video_only,audio_only}` | 實體檔路徑 | downloader + ffmpeg |
| visual_cuts | list[float] | = `scene_cuts`（一鏡到底時退回語意切點） | BlueprintBuilder |
| is_audio_essential | bool | 逐字稿長度 > 5 字 | BlueprintBuilder 推得 |
| music_dna | dict | = `music_analysis` | BlueprintBuilder |

> **雙歌名**：`template_info.music`（yt-dlp，權威）與 `music_dna.song_guess`（Gemini 猜測，附 confidence）並存。導演 prompt **只吃 music_dna 當風格參考**、不吃歌名（不可行動）；歌名留給 UI / 未來「沿用範本歌曲」，消費端優先序「yt-dlp 有值優先、否則看 song_guess 且 confidence 過門檻」。實際 BGM 一律來自配樂 DNA（`bgm_track.track_id` 由 `audio_dna` 覆寫）。

---

## ⑤ Music（`audio_dna`；**WS1 改：歌詞只剩 Whisper；不經 compressor**）

| `audio_dna` 欄位 | 格式 | 內容 | 來源 |
|---|---|---|---|
| status / query / source | str | 狀態 / 搜尋詞 / 來源(yt/jamendo/user_upload) | routing |
| local_path | `{raw, standard}` | 原始 / 16kHz mono WAV | downloader + ffmpeg |
| analysis.bpm / beats / onsets | float / list | 物理節奏 | AudioBeat(librosa) |
| analysis.lyrics | list[`{text, timestamp}`] | 逐句歌詞（含時間戳） | **Whisper**（LRClib 已移除） |
| analysis.full_lyrics_text | str | 全文歌詞 | **Whisper** |
| analysis.lyrics_source | str | 歌詞來源 | 只剩 `whisper` / `vad_silent`（原 `lrclib_*` 已消失） |

> LRClib 移除原因：眾包同步歌詞對的是另一版本，時間戳與實際播放音檔系統性偏移；改為一律以 Whisper 轉錄實體音檔，時間戳與音訊天然對齊。純配樂 / 環境音由 VAD 把關，直接跳過聽寫（`vad_silent`）。
