"""
應用程式執行期路徑集中管理 (Configuration Object Pattern)。

所有執行期可寫的熱資料目錄集中於此，預設指向本地 /data1/cache/mjlee/*，
避免 NFS 逐幀讀寫導致的 GIL 凍結（cv2.read() 在 NFS hard mount 下不可中斷阻塞）。
可透過環境變數覆寫，方便不同機器部署。
"""
import os

# 使用者素材根目錄：上傳、標準化、Pipeline 讀取皆從此路徑出發
ASSETS_DIR = os.environ.get("ASSETS_DIR", "/data1/cache/mjlee/assets")

# 全域音樂快取目錄：由 /cache 靜態路由對外服務
TEMP_TEMPLATES_DIR = os.environ.get("TEMP_TEMPLATES_DIR", "/data1/cache/mjlee/temp_templates")

# SSR 算圖暫存工作區：每次 render 建一個子目錄，render 完成後自動清除
TEMP_WORKSPACES_DIR = os.environ.get("TEMP_WORKSPACES_DIR", "/data1/cache/mjlee/temp_workspaces")
