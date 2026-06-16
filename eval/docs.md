# 任務:建立 ShortReels 評測 Dataset 的建置工具

## 背景
我在做一個 AI 短影音剪輯 agent，需要建立一個「黃金測試輸入」dataset 來評測我的產品 vs 競品。
這個 dataset 由多組「素材組」構成，每組是一批圍繞同一主題（如一趟旅遊）、但順序打亂、品質參差的直式影片素材，搭配多個 user prompt。
素材來源是 Pexels 和 Pixabay 的免費 API（皆可商用）。

## 技術需求
- 使用 Pexels API 與 Pixabay API（請從環境變數讀 API key：PEXELS_API_KEY、PIXABAY_API_KEY，不要 hardcode）
- 所有設定（要幾組、各組主題與關鍵字、每組片段數、prompt 數）放在一個 config 檔（YAML 或 JSON），不要寫死在程式裡
- 程式要 modular、有清楚的 log、可重複執行（已下載的不重複抓）
- 程式碼要refactor符合design pattern

## 要實作的流程

### 階段 0：讀取 spec
- 從 config 檔讀取 dataset 規格。config 範例結構：
  - dataset_version, output_dir
  - groups: 每組含 group_id、theme、keywords[]、target_clip_count、prompt_count
- 請附一份範例 config，內含至少 5 組不同主題（如：海邊一日遊、咖啡廳、城市散步、美食、寵物），方便我直接試跑

### 階段 1：抓素材（API）
- 對每組的每個 keyword 呼叫 Pexels / Pixabay 影片搜尋 API
- **只保留直式影片**（height > width，盡量接近 9:16）
- 篩選條件：時長 3–20 秒、解析度合理（至少 720 寬）
- 每組抓「目標數量的 2 倍」當候選池（例如目標 12 段就抓約 24 段），多抓的留給階段 2 篩選
- 下載影片檔到本機
- **同時為每段記錄 metadata**：來源平台、原始 URL、作者名、授權說明、video id、解析度、時長
- 處理 API 額度限制：加上 rate limiting 與 retry，遇到 429 要退避重試
- 已抓過的不要重複下載（用 video id 做快取判斷）

### 階段 2：策展成「事件組」（半自動）
- 純素材庫無法保證「同一事件」，所以這一步是「協助人工策展」，不要全自動亂選
- 程式做的事：
  - 把每組候選素材的縮圖 / 基本資訊整理成一份方便人工檢視的清單（例如產生一個簡單的 HTML 預覽頁或 contact sheet，列出每段的縮圖、時長、解析度、來源）
  - 提供一個機制讓我標記「這組要保留哪幾段」（例如讀一個 selection.txt 或在清單裡打勾的欄位）
  - 根據我的選擇，把選中的片段複製到該組的正式素材資料夾，並**用亂序命名**（clip_01, clip_02… 的順序不對應任何理想排序）
- 若我沒做人工選擇，提供一個 fallback：自動選畫質較好的前 N 段，但 log 要明確標示「這是自動 fallback，非人工策展」

### 階段 4：生成 prompt（每組一個 EditDuet 風格指令）
- 對每組生成「一個」完整的 user prompt（不再是多個變異）：一段連貫的 EditDuet 風格剪輯指令——
  開場鏡頭 → 中段內容 → 結尾收束，含明確目標秒數、風格、配樂、剔除壞片，並依字幕要求接子句。
- 生成方式：template-based、決定性（以 group_id 為種子）、不呼叫任何 LLM API。
- prompt 要貼合該組主題（旅遊組的 prompt 要講旅遊），並依 scope（focused/broad）切換敘事。
- 為對齊 EditDuet 指標，prompt 句中必含明確目標秒數，並把該秒數存成 prompts.json 的
  `target_duration_sec`（評測算 Time-Constraint-Satisfaction / Coverage 用）；字幕要求存
  `caption_requirement`（required/forbidden/unspecified）。

### 階段 5：打包與凍結
- 產出版本化的唯讀 dataset，目錄結構如下：