"""
應用程式執行期路徑集中管理 (Configuration Object Pattern)。

所有執行期可寫的熱資料目錄集中於此，預設指向本地 /data1/cache/mjlee/*，
避免 NFS 逐幀讀寫導致的 GIL 凍結（cv2.read() 在 NFS hard mount 下不可中斷阻塞）。
可透過環境變數覆寫，方便不同機器部署。
"""
import os

# 使用者素材根目錄：上傳、標準化、Pipeline 讀取皆從此路徑出發
ASSETS_DIR = os.environ.get("ASSETS_DIR", "/data1/cache/mjlee/assets")

# --- 專案內素材分層子目錄（B 方案：素材身分 = 相對 project root 的 relpath）---
# 每個專案資料夾底下分兩層：raw/ 放所有原始下載 + 上傳（含自訂音訊）、standardized/ 放
# media_standardizer 產出的 _std 衍生檔；各階段 JSON（phase1~4 / project_meta）一律留在 project 根目錄。
# 之所以放在 config（而非 asset_discovery）：ingestion_engine 受「不得 import backend」的反循環
# 依賴約束，下載目標需用到 RAW_SUBDIR，唯有放在最底層的 config 才能讓 backend 與 ingestion 共用同一常數。
RAW_SUBDIR = "raw"
STANDARDIZED_SUBDIR = "standardized"

# 全域音樂快取目錄：由 /cache 靜態路由對外服務
TEMP_TEMPLATES_DIR = os.environ.get("TEMP_TEMPLATES_DIR", "/data1/cache/mjlee/temp_templates")

# SSR 算圖暫存工作區：每次 render 建一個子目錄，render 完成後自動清除
TEMP_WORKSPACES_DIR = os.environ.get("TEMP_WORKSPACES_DIR", "/data1/cache/mjlee/temp_workspaces")

# --- 進度推播 / 背景生成 job 的執行期常數 ---

# 每個 job 的進度事件 replay buffer 上限：WS 晚連時可補播開頭事件，避免漏掉。
# 取值需覆蓋單批所有 asset × stage 的事件量（含 resource_wait），預設留足裕度。
PROGRESS_BUFFER_MAXLEN = int(os.environ.get("PROGRESS_BUFFER_MAXLEN", "2000"))

# job 結果與其 replay buffer 完成後的保留秒數：讓 WS 重連 / GET 仍能補取，逾時即清除。
PROGRESS_JOB_RETENTION_SEC = int(os.environ.get("PROGRESS_JOB_RETENTION_SEC", "1800"))

# --- 素材縮圖（前端 Asset Management 網格用）---

# 縮圖快取子目錄：位於 TEMP_TEMPLATES_DIR 之下，沿用既有 /cache 靜態路由對外服務。
THUMBNAIL_SUBDIR = "thumbnails"
# 縮圖統一輸出為 JPEG。
THUMBNAIL_EXT = ".jpg"
# 縮圖長邊像素上限：網格只需小圖，過大徒增產生與傳輸成本。
THUMBNAIL_MAX_PX = int(os.environ.get("THUMBNAIL_MAX_PX", "320"))
# 縮圖 JPEG 壓縮品質（1–95）。
THUMBNAIL_JPEG_QUALITY = int(os.environ.get("THUMBNAIL_JPEG_QUALITY", "80"))

# --- 專案總覽封面縮圖（卡片較大，需較高解析度）---

# 封面縮圖獨立快取子目錄：與 320px 的素材網格縮圖分開存放，避免同檔名互相覆蓋。
COVER_THUMBNAIL_SUBDIR = "thumbnails_cover"
# 封面縮圖長邊像素上限：總覽卡片約 354px 寬，Retina 需 ~700px，故預設 640px（可調 768 更銳利）。
COVER_THUMBNAIL_MAX_PX = int(os.environ.get("COVER_THUMBNAIL_MAX_PX", "640"))
