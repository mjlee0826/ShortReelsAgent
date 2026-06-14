"""集中管理所有命名常數（依 CLAUDE.md：禁止 magic number）。

凡是篩選門檻、HTTP 行為、品質權重、目錄/檔名、環境變數名稱等，一律在此命名後供其他模組 import，
不在邏輯程式碼裡散落字面值。
"""
from __future__ import annotations

# ──────────────────────────── 平台與環境變數 ────────────────────────────
PLATFORM_PEXELS: str = "pexels"
PLATFORM_PIXABAY: str = "pixabay"

ENV_PEXELS_API_KEY: str = "PEXELS_API_KEY"
ENV_PIXABAY_API_KEY: str = "PIXABAY_API_KEY"

# 兩家平台的授權字串（皆可商用；Pexels/Pixabay 官方授權名稱）
PEXELS_LICENSE: str = "Pexels License"
PIXABAY_LICENSE: str = "Pixabay Content License"

# ──────────────────────────── API 端點與分頁 ────────────────────────────
PEXELS_SEARCH_URL: str = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_SEARCH_URL: str = "https://api.pexels.com/v1/search"
PIXABAY_SEARCH_URL: str = "https://pixabay.com/api/videos/"
PIXABAY_IMAGE_SEARCH_URL: str = "https://pixabay.com/api/"

# Pexels 取直式（影片/圖片皆適用）的官方參數值（orientation=portrait）
PEXELS_PORTRAIT_ORIENTATION: str = "portrait"
# Pixabay 圖片搜尋只取照片（排除向量圖/插畫）
PIXABAY_IMAGE_TYPE_PHOTO: str = "photo"

# 各平台單頁筆數上限（官方限制）
PEXELS_MAX_PER_PAGE: int = 80
PIXABAY_MAX_PER_PAGE: int = 200
# 實際每次搜尋要求的單頁筆數（會被各 adapter clamp 到平台上限）
SEARCH_PAGE_SIZE: int = 80
# 單一 keyword 最多翻幾頁（避免秒數預算湊不滿時無限翻頁）
MAX_SEARCH_PAGES_PER_KEYWORD: int = 6

# ──────────────────────────── 素材篩選門檻（階段 1）────────────────────────────
MIN_CLIP_DURATION_SEC: float = 3.0   # 時長下限（秒）
MAX_CLIP_DURATION_SEC: float = 20.0  # 時長上限（秒）
MIN_CLIP_WIDTH: int = 720            # 解析度合理門檻：寬至少 720

# 目標長寬比 9:16（width / height）。直式硬條件只要求 height > width，
# 「接近 9:16」屬偏好，交由 QualityScorer 評分，不在硬篩階段剔除。
TARGET_ASPECT_RATIO: float = 9.0 / 16.0

# ──────────────────────────── 秒數預算（抓取/策展）────────────────────────────
# 各組未指定 target_total_seconds 時的 dataset 層級預設值（秒）
DEFAULT_TARGET_TOTAL_SECONDS: float = 90.0
# 候選池要抓到「秒數預算 × 此倍數」才停（多抓留給策展挑選）
DEFAULT_CANDIDATE_MULTIPLIER: float = 2.5

# 圖片以「名目秒數」計入同一個秒數預算（一張照片在 reel 裡定格播放約幾秒）
DEFAULT_IMAGE_NOMINAL_SECONDS: float = 3.0
# 圖片佔秒數預算的預設比例（其餘為影片）；各組可用 image_ratio 覆寫
DEFAULT_IMAGE_RATIO: float = 0.3

# 素材組「聚焦度」維度：focused=單一主體、broad=多場景
SCOPE_FOCUSED: str = "focused"
SCOPE_BROAD: str = "broad"

# ──────────────────────────── 難度分級（評測切片用）────────────────────────────
# 三級刻度，供三軸共用：主題難度（topic）、素材難度（asset）、Prompt 難度（prompt）。
# 寫進 manifest.json（group 層的 topic/asset）與 prompts.json（每個 prompt 的 difficulty），
# 評測時可據此比較不同產品在不同難度的主題／素材／Prompt 下的表現。
DIFFICULTY_EASY: str = "easy"
DIFFICULTY_MEDIUM: str = "medium"
DIFFICULTY_HARD: str = "hard"

# ──────────────────────────── 品質評分權重（階段 2）────────────────────────────
# 三項權重相加須為 1.0
QUALITY_WEIGHT_RESOLUTION: float = 0.4  # 解析度
QUALITY_WEIGHT_ASPECT: float = 0.35     # 與 9:16 的接近度
QUALITY_WEIGHT_DURATION: float = 0.25   # 時長落在甜蜜區的程度
# 解析度正規化參考高度（達 1080p 視為滿分）
QUALITY_REFERENCE_HEIGHT: int = 1920
# 時長甜蜜區（以高斯型衰減計分）
QUALITY_IDEAL_DURATION_SEC: float = 10.0
QUALITY_DURATION_SPREAD_SEC: float = 6.0

# ──────────────────────────── HTTP 行為 ────────────────────────────
HTTP_TIMEOUT_SEC: float = 15.0       # 一般 API 查詢逾時
DOWNLOAD_TIMEOUT_SEC: float = 60.0   # 影片/縮圖下載逾時
DOWNLOAD_CHUNK_SIZE: int = 8192      # streaming 下載分塊大小（bytes）

MAX_RETRY_ATTEMPTS: int = 4          # 含首次共嘗試幾次
RETRY_BACKOFF_BASE_SEC: float = 1.0  # 指數退避基數
RETRY_BACKOFF_MAX_SEC: float = 30.0  # 單次退避上限
RETRY_JITTER_SEC: float = 0.5        # 退避抖動上限（避免同步重試）
INTER_REQUEST_DELAY_SEC: float = 0.34  # 相鄰請求最小間隔（粗略 rate limiting）

HTTP_STATUS_TOO_MANY_REQUESTS: int = 429
# 視為可重試的 HTTP 狀態碼（429 + 常見伺服器端暫時性錯誤）
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})
RETRY_AFTER_HEADER: str = "Retry-After"

# ──────────────────────────── 目錄與檔名 ────────────────────────────
WORK_DIRNAME: str = "work"                 # 中間產物根目錄（在 output_dir 底下）
SELECTIONS_DIRNAME: str = "selections"     # 人工選取檔目錄
CANDIDATES_DIRNAME: str = "candidates"     # 候選影片下載目錄
THUMBNAILS_DIRNAME: str = "thumbnails"     # 縮圖目錄
CURATED_DIRNAME: str = "curated"           # 策展後（亂序命名）片段目錄
GROUPS_DIRNAME: str = "groups"             # 最終 dataset 內各組目錄
CLIPS_DIRNAME: str = "clips"               # 最終 dataset 內片段目錄

CANDIDATES_JSON: str = "candidates.json"   # 候選 metadata 清單
FETCH_INDEX_JSON: str = "_fetch_index.json"  # 已下載快取索引
PREVIEW_HTML: str = "preview.html"         # contact sheet 預覽頁
METADATA_JSON: str = "metadata.json"       # 逐段 metadata（策展後 / dataset）
CURATION_SUMMARY_JSON: str = "curation_summary.json"  # 該組策展摘要（模式/秒數/數量）
PROMPTS_JSON: str = "prompts.json"         # 該組 user prompts
MANIFEST_JSON: str = "manifest.json"       # dataset 層級 manifest
ATTRIBUTION_MD: str = "ATTRIBUTION.md"     # 逐段出處/授權彙整

SELECTION_FILE_SUFFIX: str = ".txt"        # selections/<group_id>.txt
SELECTION_COMMENT_PREFIX: str = "#"        # 選取檔的註解符號

# ──────────────────────────── 檔案與命名 ────────────────────────────
DEFAULT_VIDEO_EXT: str = ".mp4"
DEFAULT_IMAGE_EXT: str = ".jpg"
DEFAULT_THUMBNAIL_EXT: str = ".jpg"
PARTIAL_SUFFIX: str = ".part"              # 下載中暫存檔尾碼（原子寫）
CLIP_NAME_PREFIX: str = "clip_"            # 策展後片段命名前綴
CLIP_NAME_PAD_WIDTH: int = 2               # clip_01、clip_02 …

# 凍結（唯讀）權限
READONLY_FILE_MODE: int = 0o444
READONLY_DIR_MODE: int = 0o555
WRITABLE_DIR_MODE: int = 0o755             # 解除凍結重建時暫時用

# ──────────────────────────── Prompt 生成（階段 4）────────────────────────────
PROMPT_GENERATOR_TEMPLATE: str = "template"  # 目前唯一實作的策略名稱
# 組合 prompt 時為避免重複，最多重抽幾次
PROMPT_COMPOSE_MAX_ATTEMPTS: int = 8

# 字幕（字卡／畫面文字）軸的標記值；素材為無對白 stock 片，故指畫面上的文字而非語音轉字幕
CAPTION_NONE: str = "none"           # prompt 未提到字幕
CAPTION_ADD: str = "add"             # 要求加字幕／字卡／標題
CAPTION_NO: str = "no_subtitle"      # 明確要求不要字幕（負面控制組）
# 達此 prompt_count 才額外保證一個「不要字幕」負面 prompt（低於此只保證一個正面字幕 prompt）
CAPTION_NEGATIVE_MIN_PROMPTS: int = 4

# ──────────────────────────── 互動策展 server（serve 子指令）────────────────────────────
# 只綁本機回送位址（localhost），不對外開放
DEFAULT_SERVE_HOST: str = "127.0.0.1"
DEFAULT_SERVE_PORT: int = 8000

# 路由前綴：靜態媒體、單組互動頁、存檔端點
SERVER_WORK_ROUTE: str = "/work"      # GET 串流 work_dir 底下的媒體檔
SERVER_GROUP_ROUTE: str = "/group"    # GET 單組互動勾選頁（/group/<group_id>）
SERVER_SAVE_ROUTE: str = "/save"      # POST 寫回選取（/save/<group_id>）

# 互動頁前端：checkbox 變動後延遲幾毫秒才自動存檔（debounce，避免每次勾選都打 POST）
SELECTION_AUTOSAVE_DEBOUNCE_MS: int = 400

# ──────────────────────────── Logging ────────────────────────────
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFMT: str = "%H:%M:%S"
