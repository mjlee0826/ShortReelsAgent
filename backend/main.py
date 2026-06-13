import sys
import os
import asyncio
from contextlib import asynccontextmanager
# 【新增】引入 dotenv 套件來讀取 .env 檔案
from dotenv import load_dotenv

# --- 將專案根目錄加入系統路徑 ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# 【關鍵修正】在讀取任何環境變數之前，必須先載入 .env 檔案
load_dotenv()

from config.app_config import ASSETS_DIR, TEMP_TEMPLATES_DIR
from config.ingestion_config import ENABLE_INGESTION_POLLER
from config.pipeline_config import EAGER_MODELS
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.api.director import router as director_router
from backend.api.projects import router as projects_router
from backend.api.assets import router as assets_router
from backend.api.progress import router as progress_router
from backend.api.settings import router as settings_router
from backend.services.director_service import director_service
from backend.services.ingestion_provider import ingestion_poller
from backend.services.jobs.progress_hub import progress_hub


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期：捕捉 event loop 供背景 worker thread 排程進度事件，啟動雲端攝取背景 poller，關閉時優雅停止。"""
    # 在 event loop 執行緒先捕捉 loop:讓「雲端同步在 worker thread 跑的 tracked Phase 1」所發的 WS
    # 進度事件,能即時經 call_soon_threadsafe 排回本 loop(否則首同步早於任何 WS / 手動 job 觸發時,
    # _loop 尚未捕捉,事件只進 replay buffer 失去即時性)。冪等,與後續 attach / launch 同一 loop。
    progress_hub.ensure_loop()
    # 模型 warmup 從 import 期解耦到此(fork 之後、每 worker 各一次):便宜建構 + 兩階段啟動(見 docs §6)。
    # 丟 thread 不阻塞 event loop,startup 期間 readiness 探針 / WS 仍可回應;warmup 事件經已捕捉的 loop 即時廣播。
    if EAGER_MODELS:
        await asyncio.to_thread(director_service.pipeline_runner.warm_up)
    if ENABLE_INGESTION_POLLER:
        await ingestion_poller.start()
    try:
        yield
    finally:
        if ENABLE_INGESTION_POLLER:
            await ingestion_poller.stop()


app = FastAPI(title="Short Reels Agent API", lifespan=lifespan)

# CORS 放行全部來源時使用的萬用字元(具名常數,避免 magic string)
CORS_WILDCARD_ORIGIN = "*"

# 讀取允許連線的前端網址 (若未設定則預設為 localhost:5173;填 "*" 代表放行全部)
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
allow_all_origins = frontend_url.strip() == CORS_WILDCARD_ORIGIN

# 規範限制:Access-Control-Allow-Origin "*" 不可與 allow_credentials=True 並存,瀏覽器會拒絕。
# 本服務以 Authorization(Bearer token)header 認證、不使用 cookie,故放行全部時關閉 credentials 即可。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_WILDCARD_ORIGIN] if allow_all_origins else [frontend_url],
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [1] 影片素材區：掛載使用者的專案資料夾（指向本地 /data1，避免 NFS hang）
if not os.path.exists(ASSETS_DIR):
    os.makedirs(ASSETS_DIR)
app.mount("/static", StaticFiles(directory=ASSETS_DIR), name="static")

# [2] 全域系統快取區：掛載 temp_templates（指向本地 /data1，避免 NFS hang）
if not os.path.exists(TEMP_TEMPLATES_DIR):
    os.makedirs(TEMP_TEMPLATES_DIR)
app.mount("/cache", StaticFiles(directory=TEMP_TEMPLATES_DIR), name="cache")

app.include_router(director_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(assets_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
# 進度推播為 WebSocket 端點,路徑固定為 /ws/progress/{job_id},不掛 /api 前綴
app.include_router(progress_router)

if __name__ == "__main__":
    import uvicorn
    
    # 【修改】從環境變數讀取 Host 與 Port，讓啟動配置完全動態化
    # 若 .env 中沒有設定，則退回預設的 0.0.0.0 與 5174
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5174))
    
    print(f"🚀 [系統啟動] FastAPI 伺服器運行於 http://{host}:{port}")
    print(f"🔒 [CORS 設定] 允許的前端連線來源: {frontend_url}")
    
    uvicorn.run(app, host=host, port=port)