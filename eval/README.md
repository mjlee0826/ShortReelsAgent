# ShortReels 評測 Dataset 建置工具

建立「黃金測試輸入」dataset：多組圍繞同一主題、**順序打亂**、品質參差的**直式**短影片，
搭配多個繁體中文 user prompt，用來評測自家短影音剪輯 agent vs 競品。素材取自
**Pexels / Pixabay** 免費 API（皆可商用）。

工具完全自成一體（程式碼只在 `eval/` 底下），流程拆成可單獨重跑的階段：
讀 spec → 抓素材 → 半自動策展 → 生 prompt → 打包凍結。

> 設計與假設詳見 `eval/docs.md`。注意 `docs.md` 原稿在階段 5 截斷、且無階段 3；本工具實際
> 流程為階段 0/1/2/4/5，並自訂了階段 5 的輸出目錄結構（見下方）。

## 安裝

依賴用 Poetry 管理（`pyyaml`、`requests` 已加入專案 `pyproject.toml`）：

```bash
poetry install          # 或 poetry add pyyaml requests（已執行過）
```

## 金鑰設定（抓素材才需要）

兩種方式擇一（CLI 啟動時會自動載入 `.env`）：

- **`.env`（建議）**：把 `eval/.env.example` 複製成 `eval/.env` 填入金鑰即可。
  ```bash
  cp eval/.env.example eval/.env   # 然後編輯 eval/.env
  ```
  會自動載入 `eval/.env` 與專案根的 `.env`；`eval/.env` 已被 gitignore，不會進版控。
- **export**：
  ```bash
  export PEXELS_API_KEY=你的_pexels_key
  export PIXABAY_API_KEY=你的_pixabay_key
  ```

> 已 export 的環境變數優先於 `.env`。`prompts` 與 `package` 階段**不需網路/金鑰**。

## 設定檔

複製 `eval/dataset_spec.example.yaml` 來改。重點欄位：

| 欄位 | 說明 |
| --- | --- |
| `dataset_version` | 版本字串，作為凍結輸出的目錄名 |
| `output_dir` | 所有產物根目錄（範例為 `eval/_build`） |
| `sources` | 啟用平台：`pexels` / `pixabay` |
| `default_target_total_seconds` | 各組未指定時的秒數預算（秒） |
| `candidate_multiplier` | 候選池目標 = 秒數預算 × 此倍數 |
| `default_image_ratio` | 圖片佔秒數預算的預設比例（0~1，其餘為影片） |
| `image_nominal_seconds` | 一張圖片計入秒數預算的名目秒數 |
| `groups[].theme` | 中文主題，用於 prompt 生成 |
| `groups[].scope` | 聚焦度：`focused`（單一主體）/`broad`（多場景）（選填） |
| `groups[].keywords` | API 搜尋關鍵字（建議英文） |
| `groups[].image_ratio` | 該組圖片佔比（選填，覆寫 `default_image_ratio`） |
| `groups[].target_total_seconds` | 該組秒數預算（選填，否則繼承預設） |
| `groups[].prompt_count` | 要生成幾個 user prompt |
| `groups[].target_clip_count` | 片段數上限/提示（選填） |

## 使用方式

```bash
# 一次跑完（策展走自動 fallback，適合快速 dry-run）
python -m eval -c eval/dataset_spec.example.yaml all

# 或分階段（建議的半自動人工策展流程）
python -m eval -c eval/dataset_spec.example.yaml fetch     # 1) 抓素材到秒數預算
python -m eval -c eval/dataset_spec.example.yaml curate    # 2) 產 preview.html 與 selection 範本
#    → 人工檢視 _build/work/<group>/preview.html，編輯 _build/work/selections/<group>.txt
python -m eval -c eval/dataset_spec.example.yaml curate    # 2b) 再跑一次套用人工選取
python -m eval -c eval/dataset_spec.example.yaml prompts   # 4) 生成繁中 prompt（離線、可重現）
python -m eval -c eval/dataset_spec.example.yaml package   # 5) 打包成版本化唯讀 dataset
```

`-v/--verbose` 開 DEBUG log；`curate --fallback` 在無人工選取時自動依品質挑選。

### 人工策展：selection 檔

`curate` 會在 `_build/work/selections/<group_id>.txt` 產生範本，列出全部候選（預設整行註解掉），
每行附時長/累計秒數/解析度/來源/品質分。**把要保留那行最前面的 `# ` 刪掉**即可；可保留任意段數。
編輯後再跑一次 `curate` 套用。若不編輯而用 `--fallback`／`all`，會自動依品質挑到覆蓋秒數預算，
並在 log 明確標示「⚠️ 自動 fallback（非人工策展）」。

## 產出目錄結構

```
<output_dir>/
├── work/                       # 中間產物（可重複執行；已下載不重抓）
│   ├── selections/<group>.txt  # 人工選取檔
│   └── <group>/
│       ├── candidates/         # 下載的候選影片
│       ├── thumbnails/         # 縮圖
│       ├── candidates.json     # 候選 metadata
│       ├── preview.html        # contact sheet 預覽
│       ├── curated/            # 策展後（亂序命名）片段 + metadata.json
│       └── prompts.json        # 該組 prompt
└── <dataset_version>/          # 凍結後的唯讀 dataset（階段 5）
    ├── manifest.json
    ├── ATTRIBUTION.md          # 逐段出處/作者/URL/授權
    └── groups/<group>/
        ├── clips/clip_01.mp4 / clip_02.jpg … # 影片+圖片混合、亂序命名（順序不對應任何理想排序）
        ├── prompts.json
        └── metadata.json       # 逐段 metadata（含 clip ↔ 原始 video_id 對應）
```

## 設計重點

- **不需 ffmpeg/ffprobe**：篩選與品質評分全靠 Pexels/Pixabay API 回傳的寬/高/時長；縮圖直接用 API 提供的 URL。
- **秒數預算驅動**：抓取與策展都以「該組需要多少秒素材」為目標，而非固定片段數。
- **影片＋圖片**：同時抓兩家平台的影片與照片；圖片以名目秒數計入同一預算，`image_ratio` 控佔比。
- **兩家平台公平取用**：每個秒數預算池先讓各來源各自湊到約 `1/來源數`，再用全部來源補滿；因此 Pexels 與 Pixabay 都會混入（不會被先查到的 Pexels 一次塞滿、Pixabay 永遠輪不到）。某來源素材不足時由另一家補齊，預算仍會湊滿。
- **scope 維度**：每組標 `focused`（單一主體）或 `broad`（多場景），prompt 也會依 scope 調整；評測時可切片比較產品在兩種素材上的表現。
- **preview 可播放**：`preview.html` 內嵌 `<video>`，人工策展時可直接看影片再決定保留哪些。
- **可重複執行**：已下載者用 `video_id` 快取判斷不重抓；prompt 以 `group_id` 為種子決定性生成（重跑結果一致）。
- **prompt 不呼叫任何 API**：由手寫的繁中範本 + 各主題詞庫（`eval/prompts/lexicon.py`）決定性組合，
  涵蓋詳細度（從「幫我剪一下」到指定時長/風格/濾鏡）、語氣、情境三軸。
- **design pattern**：Pipeline（階段串接）、Adapter（Pexels/Pixabay）、Strategy（來源/篩選/品質/選取/prompt）、
  Factory（來源、prompt 生成器）、Composite（篩選條件）。

## 授權

素材皆為可商用的 Pexels / Pixabay 授權，逐段出處與作者列於每份 dataset 的 `ATTRIBUTION.md`。
