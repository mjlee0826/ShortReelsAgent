# Phase 1 Metadata 增補:為 Phase 4 導演強化感知 ⬜ 未開始

> 本文件記錄三項「擴充素材 metadata 以提升 Phase 4 導演決策品質」的設計,供日後實作參考。
> 上游為 `media_processor`(Phase 1 感知 pipeline),下游消費者為 `director_agent`(Phase 4 導演大腦)。
> 與 `integrated_acceleration_plan.md` 互補:後者談「跑得快」,本文件談「看得準」。
> 狀態:已討論定案、**尚未實作**,無排程。

---

## 0. 背景與共通原則

### 0.1 核心洞察

目前 Phase 1 各 Stage 把「時間序列 / 空間分佈 / 高維向量」**壓成單一純量或標籤**才交給導演:
一個 `motion_intensity` 標籤、一個 `aesthetic_score`、一個 `subject_bbox`、一段攤平的 `audio.vocal`。
但導演要做的決策(在哪剪、變速對拍、9:16 追主體、字幕擺位)幾乎都是 **clip 內、逐時刻、逐素材間** 的。
資訊在進導演前就被降維掉,導演只能瞎猜。

### 0.2 SIMPLE / COMPLEX 的真相(界定本文件邊界)

`VideoStrategy` / `ImageStrategy` 的 SIMPLE/COMPLEX **不是依素材內容判定的**,而是「用哪顆語意引擎 / 哪個成本檔位」:
- SIMPLE → 本地 Qwen(快 / 免費),COMPLEX → Gemini API(慢 / 付費,需燒時間碼)。
- 決定點在 `director_service.py` 把前端「影片品質選項」轉成 enum,**整批一個值、處理前就定**;圖片一律 SIMPLE。

**未來規劃**:改為「使用者可逐素材選 Complex」。好消息是 `AssetContext` 本來就逐素材帶 `video_strategy`(`context.py:78`),
runner 只是現在把同一個 batch 值填給每個 context;改成查 `{檔名: 策略}` map 即可,plumbing 很小。

→ 因此「把純量拆成時間序列」那批(`motion_curve` / `bbox_track` / `highlight_t` / 逐段品質曲線)**刻意不在本文件範圍**:
那是 Complex 的職責,靠上述逐素材選 Complex 來涵蓋,不在 Simple 裡重蓋一個小 Complex。

### 0.3 三條貫穿全部三項的原則

1. **每項幾乎都動同樣的接點**(符合現有分層):
   `models.py` 加 pydantic 欄位 → 某個 **Stage** 產出(多半擴既有 stage,非新模型)→ **`ContextCompressor`** 決定壓縮形狀
   → `default_prompt_manager` 導演 schema 告知 LLM 新欄位 → 偶爾加 `critic` 驗證。
2. **真瓶頸是 token 預算,不是算力。** 所有 asset 最後被 `json.dumps(assets)` 塞進**同一個** prompt
   (`DefaultPromptManager.get_director_prompt`)。每項的設計重點是「**壓縮後用什麼形狀進 prompt**」,
   `ContextCompressor` 是守門員(其 docstring 即「特徵降維與防禦性過濾」)。
3. **per-asset vs cross-asset 是分水嶺。** 項目一、三是「單一素材的事實」,貼合現有 per-asset DAG;
   **項目二的本質是跨素材比較**,現有「一 asset 一 Pipeline」沒有它的家 → 需新增 library 級彙整步驟。

### 0.4 實作守則(對齊 `CLAUDE.md`)

- 新資料結構用 pydantic / dataclass(沿用 `models.py` Value Object 風格)。
- 禁止 magic number:所有閾值(去重門檻、黑邊 luma、安全區比例…)必須是 `config/` 內的命名常數。
- 每個 class / function 要有 docstring,邏輯註解用繁中。
- 一律套用對應 design pattern(既有 Stage = Strategy、Compressor = Strategy、Factory…)。

---

## 1. 項目一:撿回被 `ContextCompressor` 丟掉的資訊

### 1.1 現況

這三個信號 **Phase 1 早已算出並存進 metadata**,卻在 `ContextCompressor.compress` 被丟棄或攤平。
因此本項**不動 pipeline**,主要改 `ContextCompressor` + 同步導演 schema。

| 信號 | 現在丟在哪 | 壓縮後形狀(進 prompt) | 解鎖的導演決策 |
|---|---|---|---|
| Whisper 逐句時間碼 | compressor 只取 `audio_transcript["text"]`,丟掉 `chunks`(`whisper_stage` 其實已寫入完整 transcript) | 句級 `[{t:[起,迄], txt}]`,**非** word 級,設句數上限 | 在句界選 `source_start/end`(不切半句)、只在人聲窗 `clip_volume=1.0` |
| `cinematic_critique` | compressor `base_info` 根本沒帶(只帶 `caption`) | 帶、但**截斷長度** | 轉場 / 濾鏡 / 運鏡風格判斷 |
| `faces.largest_face_ratio` | compressor 只帶 `face_count` | 純量,直接加 | 特寫判定、9:16 留頭部空間、要不要 zoom |

### 1.2 取捨與陷阱

- **Whisper chunks 的價值有一半卡在 schema**:現在 `overlay_text` 是「一 clip 一字串」、`clip_volume` 是「一 clip 一純量」,
  **無法表達「第 2~4 秒才有字幕 / 才壓 BGM」**。逐句字幕與逐句 ducking 需先做 §4 的 `overlay` schema 升級。
  在 schema 升級前,chunks 只先用於「選剪點 / ducking 判斷」,不做逐句字幕。
- **`cinematic_critique` 是判斷題**:它是最豐富的質性描述(`mood`/`cam` 是它降維出的有損 enum),
  對 LLM 導演常比 enum 有用;但整段散文 × 每個 asset 很吃 token。建議帶但截斷,並列為日後 token-vs-品質 A/B 的首選欄位。
- **`largest_face_ratio` 無腦加**:純量、零成本、無下游風險。

### 1.3 接點

`director_agent/context_compressor.py`(主)、`prompt_manager/default_prompt_manager.py`(schema 說明)。
若壓縮策略變複雜(逐欄上限 / 截斷),可考慮把「投影規則」抽成小物件,但勿過度設計。

### 1.4 不做

- 不在此引入 word 級時間碼(導演不逐字剪,純 token 浪費)。
- 不在此升級 `overlay` schema(見 §4,跨項目一起做)。

---

## 2. 項目二:CLIP + pHash 近重複去重(Library 級)

### 2.1 關鍵前提:CLIP 已經在算,只是把 embedding 丟了

`LaionModelManager`(美學評分)載入的就是 **CLIP**(`CLIPModel` + `CLIPProcessor`,LAION ViT-L/14)。
其 `_extract_features`(L158–177)做 `clip_model.get_image_features(...)` 後 **L2 normalize** —— 這就是一條 CLIP 影像 embedding,
而且 L2 normalized 正好是 cosine 要的形狀;接著 `mlp(features)` 壓成一個美學 float,**embedding 就被丟掉**。

→ 對本專案,「加 CLIP」其實是「**別丟掉已在算的 CLIP embedding**」:
VRAM / forward / 合批 / 多卡 pool 全都已付(`aes_score_stage` 已 GPU 合批),邊際成本 ≈ 暴露那條 tensor。
文字塔(`get_text_features`)在同一顆模型上,prompt / 歌詞匹配亦近乎免費。**不需要新增 SigLIP。**

### 2.2 為什麼是 CLIP + pHash 雙閘(不是單靠 CLIP)

CLIP 是 image-text 對比學習 → 重語意、被訓練成對 instance / 低階細節**不變**。後果:

| 關係 | CLIP 影像 cosine(粗略,**須校準**) | 含意 |
|---|---|---|
| 連拍真重複 | 0.95+ | CLIP **很會抓** → recall 好 |
| 同場景不同角度 | 0.88–0.95 | CLIP 抓得到、pHash 抓不到 |
| **同概念不同實例**(兩個不同日落海灘) | **0.80–0.90 ← 與上列重疊** | 單一 CLIP 門檻會**誤併** |

兩個失效模式:
- **Q1 群內挑不出「哪張較好」、且會漏掉小而關鍵的差異**(眨眼、出現小物件)→ 語意不變性的副作用。
- **Q2 同 caption / 同概念但不同畫面 → 誤併風險**;若改用「caption 文字向量」去重,此誤殺**最嚴重**(文字是有損摘要)。

**解法 = AND 雙閘**:`CLIP 影像相似度高` **且** `pHash / 顏色直方圖也高` → 才算真重複。
兩者互補在對方弱點上:CLIP 補 pHash 抓不到的「同物換角度」;pHash / 顏色擋掉 CLIP 會誤併的「同概念不同實例」。

### 2.3 三條鐵律

1. **向量永遠不進 prompt。** 768 維向量只活在 library 層;進導演 prompt 的只有**衍生結果**
   (去重群組、與 prompt 的相似度排序),token 成本才是 0。
2. **群內挑最佳用別的訊號**(`aes_score` / 銳利度 / `largest_face_ratio`),**不是** embedding 距離。
3. **只「分群 + 推薦」,絕不做不可逆的 hard filter。** 素材全留給導演 / 使用者,誤併代價為零;一旦刪檔,假陽性永久損失素材。
   → 使用者問的「會不會意外 filter」,最強的保險是**架構上不做不可逆 filter**,而非把 embedding 弄得更準。
4. **門檻在自己素材上校準成命名常數**(CLIP 影像向量有 anisotropy / 高基線,不相關也可能 0.4 而非 0,動態範圍被壓縮),嚴禁 magic number。

### 2.4 架構:cross-asset `LibraryAnalyzer` 的家

per-asset 部分:`LaionModelManager` 多一個回傳 embedding 的路徑(複用 `_extract_features`,不重算)→
`FrameAnalysis → metadata` 帶下去。pHash 由一個極輕 CPU stage 算。

cross-asset 部分:新增 `LibraryAnalyzer`(**純 numpy cosine,無模型**),吃 `director_service` dump 出的整個
`raw_assets_metadata` list,產出「去重群組 / 排序 / 與 prompt 相似度」標註。它坐在 **phase1 dump 之後、導演之前**。

**向量儲存**:別 inline 進 phase1 的 JSON dump(會脹),放 sidecar(npy / parquet)。

### 2.5 未來升級階梯(備案,非現在做)

| 方案 | 去重表現 | 成本 |
|---|---|---|
| caption 文字向量 | 最差(Q2 誤殺最嚴重) | 最省 → **不要用來去重** |
| **CLIP 影像 + pHash 雙閘(本項)** | recall 好、precision 中等 | ≈0(CLIP 已在跑) |
| DINOv2 / SSCD(實例 / 拷貝偵測模型) | instance 區分最強 | 要加一顆模型 → 只在實測誤併率不可接受時才上 |

### 2.6 接點

`model/laion_model_manager.py`(暴露 embedding)、新 pHash stage、新 `LibraryAnalyzer`、
`director_agent/context_compressor.py`(注入去重 / 排序標註)、`prompt_manager`(告知導演「近重複群、建議留 X」)。

### 2.7 不做

- 不把向量塞進 prompt。
- 不做 hard delete / 自動 filter。
- 不為了精度提前上 SigLIP / DINOv2(等實測證明需要)。

---

## 3. 項目三:空間 / 框架事實

多為便宜的幾何 / 容器事實,**非新模型**,且數個直接重用既有訊號。新增小欄位到 `ImageMetadata` / `VideoMetadata`。

| 事實 | 來源 / 重用 | 解鎖的導演決策 |
|---|---|---|
| 原生方向 / rotation 旗標 | 圖片:EXIF Orientation(`MediaStrategy._extract_exif_metadata` 現只讀 datetime/gps,**沒讀 Orientation**);影片:ffprobe display matrix | 防止 `crop_feasibility` / `object_position` 因「橫向尺寸+旋轉旗標」算錯而側裁 |
| 黑邊內框 `content_box`(letterbox / pillarbox) | cv2 看邊緣 luma 近零(命名閾值) | 9:16 裁切相對於**有內容的內框**,不裁進黑邊 |
| 字幕安全區 / negative space | **取既有 U²-Net saliency mask 的反區**(幾乎免費):九宮格各格給「空白分數」 | `overlay_text` / `pip_video` 放空白區,不擋主體(現在導演對「放哪」一無所知) |
| 主體覆蓋比 / 邊緣偏置 | bbox 面積(配 `largest_face_ratio`)、bbox 中心 | 決定 `scale` / zoom、`object_position` 是否要硬推 |

### 3.1 取捨與陷阱

- **方向是基礎事實**:`aspect_ratio` 單看會說謊(側拍影片),必須有真實朝向才能信任後續所有框構欄位。
- **安全區幾乎免費**:saliency mask 已存在,只是多吐一個反區摘要;但其價值同樣卡在 §4 的 `overlay` 需有「位置」欄位。
- **多主體**(同框兩個 bbox 塞不進 9:16)較重(要動偵測 / saliency),**本項先不做**,留待需要時。

### 3.2 接點

`media_strategy.py`(EXIF 多讀 Orientation)、`exif_stage` / 新輕量 `LetterboxStage`、saliency stage(多吐安全區摘要)、
`models.py`(新欄位)、`context_compressor.py`、`prompt_manager`。純 CPU、DAG 自動並行、風險低。

### 3.3 不做

- 不做多主體追蹤 / 各自 bbox(留待)。
- 不在此升級 `overlay` schema(見 §4)。

---

## 4. 跨項目收斂:`overlay_text` schema 升級(單一最大槓桿)

§1 的 Whisper 時間碼(字幕「內容」+「何時」)與 §3 的安全區(字幕「放哪」)**撞到同一面牆**:
現在 `overlay_text` 只是裸字串,`pip_video` 才有 `position`。把它升級成結構物件(概念):

```
overlay: [ { txt, t:[起,迄], pos: "top" | "bottom" | 安全區 } ]
```

這**一個** schema 動作,同時讓 §1 的逐句時間碼與 §3 的安全區真正發揮(也需 **Remotion 端**配合渲染計時字幕)。
其餘 metadata 是「餵料」,這個是「讓料有地方用」。

**前置條件**:Remotion 是否吃得下計時字幕。若前端短期無法配合 → §1 的 chunks 先只當「選剪點 / ducking 判斷」,
schema 維持現狀,等 Remotion ready 再升級。

---

## 5. 建議落地順序

1. **§1 的 (a) Whisper 時間碼用於選剪點 + (c) face ratio + §3 的安全區**:全是「改 Compressor / 重用既有訊號」,零新模型,先落地。
2. **敲定 §4 `overlay` schema(含 Remotion 確認)**:它決定 §1(a) 與 §3 的天花板。
3. **§2 起手**:從 LAION stage 暴露 embedding → sidecar → `LibraryAnalyzer` 產去重 / 排序標註 → 注入 Compressor;
   相似度先當**標註**不當**過濾**;CLIP+pHash 雙閘,門檻校準。

相依關係:§4 是 §1(a) 與 §3 完整發揮的前提;§2 完全獨立,可平行進行。

---

## 6. 明確不在本文件範圍

- 時間序列拆解(`motion_curve` / `bbox_track` / `highlight_t` / 逐段品質曲線)→ 屬 Complex,靠「逐素材選 Complex」涵蓋。
- 內容感知自動路由(以便宜信號自動升級 Complex)→ 已由「使用者逐素材選 Complex」取代。
- Phase 4 RAG:現規模(數十 clip)導演須看全部素材,**不做 RAG**(會傷全局規劃);
  待素材庫變大,再用 §2 的 embedding 當 top-K 入圍器。更值得的 RAG 方向是檢索「剪輯知識 / 範本」而非素材。
- 多主體追蹤、DINOv2/SSCD、SigLIP:未來備案,實測證明需要才上。
