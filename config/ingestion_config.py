"""
Layer 0 雲端攝取層常數集中管理 (Configuration Object Pattern)。

ingestion_engine/ 底下所有模組從此處 import Drive API 設定、輪詢週期與媒體副檔名等設定，
避免 magic number 散落各檔。攝取改走「公開資料夾 + 一把全站共用 Drive API key」模式：
資料夾設為「知道連結的人可檢視」、貼資料夾 URL，後端以 API key 定期列檔／下載，零 rclone、
零 OAuth、零 per-user token。數值皆可由環境變數覆寫，方便不同機器部署與實機調校。
"""
import os

# env 讀取工具集中於 config.env_utils（DRY）；別名維持模組內既有呼叫寫法
from config.env_utils import (
    read_bool_env as _read_bool_env,
    read_float_env as _read_float_env,
    read_int_env as _read_int_env,
)
from config.media_formats import MEDIA_EXTENSIONS


# ── Google Drive API（公開資料夾 + 共用 API key）─────────────────────────────────
# 全站共用的 Drive API key（Cloud Console 建立、無同意畫面、非 per-user）；
# 只對「知道連結的人可檢視」的公開檔案有效。未設定時列檔／下載會得到授權錯誤。
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# Drive API v3 端點根 URL。
DRIVE_API_BASE_URL = os.environ.get("DRIVE_API_BASE_URL", "https://www.googleapis.com/drive/v3")

# 單次 files.list 的最大回傳筆數（Drive API 上限 1000）；過小會增加分頁次數。
DRIVE_API_PAGE_SIZE = _read_int_env("DRIVE_API_PAGE_SIZE", 1000)

# 單次 Drive API 請求逾時秒數，避免雲端卡死讓 poller 永久阻塞。
DRIVE_API_TIMEOUT_SEC = _read_int_env("DRIVE_API_TIMEOUT_SEC", 120)

# Drive 用來表示「資料夾」的 mimeType；列檔時以此判斷子資料夾 vs 檔案。
DRIVE_FOLDER_MIMETYPE = "application/vnd.google-apps.folder"

# ── Drive API 限流退避重試 ───────────────────────────────────────────────────────
# 「檔案多」的專案首同步會連發大量列檔／下載請求，易撞 Drive API 限流（常以 HTTP 403 +
# rateLimitExceeded 回應，而非真權限不足）。adapter 偵測到限流時就地指數退避重試，避免暫時性
# 限流被誤判成授權失效而把專案永久暫停。以下數值皆可由環境變數覆寫，方便實機調校。
# 單次請求遇限流時，在 adapter 內就地退避重試的最大次數（超過仍失敗才以暫時性錯誤上拋）。
DRIVE_API_MAX_RETRIES = _read_int_env("DRIVE_API_MAX_RETRIES", 5)

# 首次重試前的基礎等待秒數；其後每次乘以 BACKOFF_MULTIPLIER 形成指數退避。
DRIVE_API_RETRY_BASE_BACKOFF_SEC = _read_float_env("DRIVE_API_RETRY_BASE_BACKOFF_SEC", 1.0)

# 指數退避倍率：每次重試的等待時間乘以此值。
DRIVE_API_RETRY_BACKOFF_MULTIPLIER = _read_float_env("DRIVE_API_RETRY_BACKOFF_MULTIPLIER", 2.0)

# 單次退避等待的上限秒數，避免指數成長到不合理的長等待。
DRIVE_API_RETRY_MAX_BACKOFF_SEC = _read_float_env("DRIVE_API_RETRY_MAX_BACKOFF_SEC", 30.0)

# 退避等待的抖動比例（±此比例隨機擾動）：打散多專案同時退避造成的同步尖峰（thundering herd）。
DRIVE_API_RETRY_JITTER_RATIO = _read_float_env("DRIVE_API_RETRY_JITTER_RATIO", 0.2)

# ── 輪詢排程 ──────────────────────────────────────────────────────────────────
# 每個 project 兩次同步的最小間隔（秒），預設 5 分鐘。
INGESTION_POLL_INTERVAL_SEC = _read_int_env("INGESTION_POLL_INTERVAL_SEC", 300)

# poller 背景迴圈的醒來週期（秒）：每醒來一次挑出「已到期」的 project 才真的同步。
# 取值需 ≤ INGESTION_POLL_INTERVAL_SEC，否則到期判斷顆粒度過粗。
POLLER_TICK_SEC = _read_int_env("POLLER_TICK_SEC", 60)

# 是否在後端啟動時拉起背景 poller；sandbox／開發環境可設 false 關閉。
ENABLE_INGESTION_POLLER = _read_bool_env("ENABLE_INGESTION_POLLER", True)

# ── 素材過濾 ──────────────────────────────────────────────────────────────────
# 同步時只下載受支援的媒體副檔名（圖片 ∪ 影片 ∪ 音訊），列檔／下載時以此過濾，避免把雲端
# 雜檔（文件／壓縮檔）一起拉下來。白名單集中於 config.media_formats 單一來源，與 Pipeline /
# backend 共用同一組，避免散落 drift。
INGESTION_MEDIA_EXTENSIONS = MEDIA_EXTENSIONS
