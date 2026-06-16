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
| `groups[].topic_difficulty` | 主題敘事難度：`easy`/`medium`/`hard`（選填，寫進 manifest 供切片） |
| `groups[].asset_difficulty` | 素材難度（關鍵字越廣/跨地/越雜越難）：`easy`/`medium`/`hard`（選填，寫進 manifest） |
| `groups[].keywords` | API 搜尋關鍵字（建議英文，盡量「具體」以提高素材多樣性） |
| `groups[].image_ratio` | 該組圖片佔比（選填，覆寫 `default_image_ratio`） |
| `groups[].target_total_seconds` | 該組秒數預算（選填，否則繼承預設） |
| `groups[].prompt_count` | （已棄用）每組固定生成 1 個 prompt；欄位僅為相容舊 spec |
| `groups[].target_clip_count` | 片段數上限/提示（選填） |

## 使用方式

```bash
# 一次跑完（策展走自動 fallback，適合快速 dry-run）
python -m eval -c eval/dataset_spec.example.yaml all

# 或分階段（建議的半自動人工策展流程）
python -m eval -c eval/dataset_spec.example.yaml fetch     # 1) 抓素材到秒數預算
python -m eval -c eval/dataset_spec.example.yaml serve     # 2) 起互動勾選頁，瀏覽器勾選即存
#    → 開瀏覽器到印出的 http://127.0.0.1:8000/，逐組勾選要保留的片段（勾選即寫回選取檔）
python -m eval -c eval/dataset_spec.example.yaml curate    # 2b) 套用人工選取（複製、亂序命名）
python -m eval -c eval/dataset_spec.example.yaml prompts   # 4) 生成繁中 prompt（離線、可重現）
python -m eval -c eval/dataset_spec.example.yaml package   # 5) 打包成版本化唯讀 dataset
```

`-v/--verbose` 開 DEBUG log；`curate --fallback` 在無人工選取時自動依品質挑選。

**懶人「全取」流程（跳過 serve/挑選，直接用全部已抓素材）**：用 `--take-all`，會取用該組全部候選（仍會亂序命名），不受秒數預算挑選。優先於人工選取與 `--fallback`。

```bash
python -m eval -c eval/dataset_spec.example.yaml fetch                 # 先抓
python -m eval -c eval/dataset_spec.example.yaml curate --take-all     # 全取（不挑）
python -m eval -c eval/dataset_spec.example.yaml prompts
python -m eval -c eval/dataset_spec.example.yaml package
# 或一行： all 也吃 --take-all（fetch → 全取策展 → prompts → package）
python -m eval -c eval/dataset_spec.example.yaml all --take-all
```

### 人工策展（建議）：`serve` 互動勾選頁

`serve` 會起一個**只綁本機（localhost）**的小型 server（純 stdlib、零新依賴）：

```bash
python -m eval -c eval/dataset_spec.example.yaml serve            # 預設 127.0.0.1:8000
python -m eval -c eval/dataset_spec.example.yaml serve --port 9000 # 換埠
```

開瀏覽器到印出的網址即見各組索引；進某組頁面可**直接播放影片**並用 checkbox 勾選；頂部工具列即時顯示
已選件數與累計秒數（vs 秒數預算），勾選變動會自動寫回 `_build/work/selections/<group_id>.txt`（debounce）。
頁面打開時 checkbox **依現有選取檔**預先勾起，方便微調。勾完直接 `Ctrl-C` 關 server，再跑 `curate` 套用。
（需先 `fetch` 把媒體下載到本機；`serve` 本身不需 API 金鑰。）

### 人工策展（替代）：手改 selection 檔

不想開瀏覽器也可以：`curate` 會在 `_build/work/selections/<group_id>.txt` 產生範本（也會產生唯讀的
`preview.html` 供檢視），列出全部候選（預設整行註解掉），每行附時長/解析度/來源/品質分。**把要保留那行
最前面的 `# ` 刪掉**即可；可保留任意段數。編輯後再跑一次 `curate` 套用。此格式與 `serve` 寫出的完全相同，
兩種方式可互換。若不編輯而用 `--fallback`／`all`，會自動依品質挑到覆蓋秒數預算，並在 log 明確標示
「⚠️ 自動 fallback（非人工策展）」。

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
- **組層難度 + 目標秒數**：每組標 `topic_difficulty`（主題敘事難度）與 `asset_difficulty`（素材雜亂/多樣程度），各為 `easy`/`medium`/`hard`，寫進 `manifest.json`；每組唯一 prompt 另含明確 `target_duration_sec`（EditDuet 的目標秒數 `d`），同時寫進 `prompts.json` 與 `manifest.json`。評測時可沿「主題 × 素材」難度與目標秒數切片。
- **關鍵字偏具體**：範例刻意用「壽司／東京鐵塔／拉花」等具體詞而非泛詞，讓候選素材池更多樣；`broad` 旅遊類主題（如「日本旅遊」）刻意放寬地理範圍以提高素材難度。
- **preview 可播放**：`preview.html` 內嵌 `<video>`，人工策展時可直接看影片再決定保留哪些。
- **可重複執行**：已下載者用 `video_id` 快取判斷不重抓；prompt 以 `group_id` 為種子決定性生成（重跑結果一致）。
- **每組一個 EditDuet 風格 prompt（不呼叫任何 API）**：由手寫的繁中範本 + 各主題詞庫（`eval/prompts/lexicon.py`）決定性組出
  **一段完整指令**——開場鏡頭 → 中段內容 → 結尾收束，含明確目標秒數、風格、配樂、剔除壞片，並依字幕要求接子句。
  `prompts.json` 同時存 `target_duration_sec` 與 `caption_requirement` 作為評測 ground truth。
- **design pattern**：Pipeline（階段串接）、Adapter（Pexels/Pixabay）、Strategy（來源/篩選/品質/選取/prompt）、
  Factory（來源、prompt 生成器）、Composite（篩選條件）。

## 評測指標（對齊 EditDuet）

dataset 把評測 ground truth 一併凍結，跑完各產品後即可算 [EditDuet](https://arxiv.org/abs/2509.10761)
的指標（`d`＝`prompts.json` 的 `target_duration_sec`，`d̂`＝產品輸出影片的實際秒數）：

| 指標 | 算法 | 需要的 ground truth |
| --- | --- | --- |
| **Time-Constraint Satisfaction** | `TC = min(d, d̂) / max(d, d̂)`（越接近 1 越好） | `target_duration_sec`（prompts.json / manifest.json） |
| **Coverage** | 輸出秒數逼近目標秒數的程度（同上彙總成百分比） | `target_duration_sec` |
| **Failure Rate** | 跑不出有效影片的比例（function/file hallucination、index 越界…） | 任務本身（每組單一直式短片、目標約 `d` 秒、用該組 clips） |
| **Repetitions** | 同一成片中重疊 ≥80% 的 sub-clip 配對數 | `metadata.json` 的 `clip_name ↔ original_video_id` 溯源 |

字幕行為另可用 `caption_requirement`（`required`/`forbidden`/`unspecified`）切片：該加時有沒有加、該不加時會不會亂加。

## 授權

素材皆為可商用的 Pexels / Pixabay 授權，逐段出處與作者列於每份 dataset 的 `ATTRIBUTION.md`。
