"""
Layer 0 雲端攝取層常數集中管理 (Configuration Object Pattern)。

ingestion_engine/ 底下所有模組從此處 import Drive API 設定、輪詢週期與媒體副檔名等設定，
避免 magic number 散落各檔。攝取改走「公開資料夾 + 一把全站共用 Drive API key」模式：
資料夾設為「知道連結的人可檢視」、貼資料夾 URL，後端以 API key 定期列檔／下載，零 rclone、
零 OAuth、零 per-user token。數值皆可由環境變數覆寫，方便不同機器部署與實機調校。
"""
import os

from config.media_formats import MEDIA_EXTENSIONS


def _read_int_env(env_name: str, default: int) -> int:
    """讀取 env var 並轉為 int；未設定或格式錯誤時回傳 default（不讓壞值炸掉啟動）。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        # 壞字串視為未設定，回退預設值以保證啟動穩定
        return default


def _read_bool_env(env_name: str, default: bool) -> bool:
    """讀取 env var 並轉為 bool，接受 true/1/yes/on 等常見字串。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


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
