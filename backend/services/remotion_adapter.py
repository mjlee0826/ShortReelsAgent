"""
RemotionAdapter：把 Node.js/Remotion CLI 封裝為 Python 介面 (Adapter Pattern)。

只負責「跨語言呼叫」，不處理任何商業邏輯。

常駐 bundle 快取
----------------
``npx remotion render <entry>`` 每次呼叫都會重跑 webpack bundle（典型 20–60s），但 blueprint 只是
props、前端程式碼並沒有變 —— 這是輸出 MP4 最大的固定等待。改為兩段式：

1. :meth:`_ensure_bundle`：以 ``npx remotion bundle`` 把前端打包落地到 ``REMOTION_BUNDLE_DIR``，
   成功後寫入 marker 檔記錄打包時刻。
2. :meth:`render_video`：直接把 bundle 目錄當 serve URL 餵給 ``npx remotion render``，跳過重複打包。

失效判準：掃 ``frontend/src`` 與 package.json / remotion.config.* 的最新 mtime，比 marker 新即重建
（開發改前端後下一次 render 自動重打包，不需重啟後端）。打包失敗或設
``REMOTION_DISABLE_BUNDLE_CACHE=1`` 時，回退舊的「每次從 entry bundle」路徑，功能不中斷。
"""
import os
import subprocess
import threading

from config.app_config import (
    REMOTION_BUNDLE_DIR,
    REMOTION_CONCURRENCY,
    REMOTION_DISABLE_BUNDLE_CACHE,
    REMOTION_RENDER_TIMEOUT_SEC,
)
import logging

logger = logging.getLogger(__name__)

# bundle 完成 marker 檔名：存在且 mtime ≥ 前端原始碼最新 mtime ⇒ bundle 仍新鮮
_BUNDLE_MARKER_FILENAME = ".bundle_complete"
# 失效掃描要納入的前端頂層檔案（依賴 / 打包設定變動也應觸發重建）
_STALENESS_TOP_FILES = ("package.json", "package-lock.json", "remotion.config.ts", "remotion.config.js")


class RemotionAdapter:
    """封裝 Remotion CLI 的 bundle / render 兩段式呼叫；bundle 常駐快取、失效自動重建。"""

    def __init__(self):
        # 精確定位到 frontend 資料夾，這是執行 npx 指令的必須條件 (CWD)
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.frontend_dir = os.path.join(self.project_root, "frontend")
        # Remotion 註冊點（composition 註冊於 remotion.index.jsx）
        self.entry_file = "src/remotion.index.jsx"
        self.bundle_dir = REMOTION_BUNDLE_DIR
        # bundle 重建互斥：多個 render 請求同時偵測到過期時，只讓一個真正重打包
        self._bundle_lock = threading.Lock()

    # ── 對外介面 ─────────────────────────────────────────────────────────────

    def render_video(self, composition_id: str, props_path: str, output_path: str):
        """
        啟動無頭瀏覽器逐格算圖。優先吃常駐 bundle（省每次 20–60s 的重複打包）；
        bundle 不可用（打包失敗 / 逃生閥停用）時回退從 entry 直接 render 的舊路徑。
        """
        source = self.entry_file
        if not REMOTION_DISABLE_BUNDLE_CACHE and self._ensure_bundle():
            source = self.bundle_dir

        cmd = [
            "npx", "remotion", "render",
            source,                 # bundle 目錄（serve URL）或 entry 檔（回退路徑）
            composition_id,         # 畫布 ID
            output_path,            # 輸出 MP4 路徑
            f"--props={props_path}",  # 注入的 JSON 藍圖
        ]
        # 並行度（Chromium 分頁數）：未設定則交給 Remotion 依 CPU 自動決定
        if REMOTION_CONCURRENCY:
            cmd.append(f"--concurrency={REMOTION_CONCURRENCY}")

        logger.info(f"[RemotionAdapter] 啟動背景算圖指令: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=self.frontend_dir,
                capture_output=True,
                text=True,
                timeout=REMOTION_RENDER_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Remotion 算圖超時（{REMOTION_RENDER_TIMEOUT_SEC}s）："
                "請檢查 Node.js 環境或縮短影片長度。"
            )

        if result.returncode != 0:
            logger.error(f"❌ [RemotionAdapter] 算圖崩潰，Node.js 報錯:\n{result.stderr}")
            raise RuntimeError(f"Remotion 算圖失敗: {result.stderr}")

        return True

    # ── 常駐 bundle ──────────────────────────────────────────────────────────

    def _ensure_bundle(self) -> bool:
        """
        確保常駐 bundle 存在且新鮮；需要時（不存在 / 前端原始碼較新）重打包。

        回傳 bundle 是否可用：打包失敗回 False（best-effort，呼叫端回退 entry 路徑，
        render 功能不因 bundle 問題中斷）。雙重檢查鎖：並發 render 同時偵測過期時只重建一次。
        """
        if self._bundle_is_fresh():
            return True
        with self._bundle_lock:
            if self._bundle_is_fresh():  # 等鎖期間可能已被別的請求重建完
                return True
            return self._build_bundle()

    def _bundle_is_fresh(self) -> bool:
        """marker 存在且其 mtime ≥ 前端原始碼最新 mtime ⇒ bundle 新鮮可用。"""
        marker = os.path.join(self.bundle_dir, _BUNDLE_MARKER_FILENAME)
        try:
            marker_mtime = os.path.getmtime(marker)
        except OSError:
            return False  # 從未打包（或 marker 被清）
        return self._frontend_latest_mtime() <= marker_mtime

    def _frontend_latest_mtime(self) -> float:
        """掃 frontend/src 與依賴 / 打包設定檔的最新 mtime（決定 bundle 是否過期）。"""
        latest = 0.0
        src_dir = os.path.join(self.frontend_dir, "src")
        for dirpath, _dirnames, filenames in os.walk(src_dir):
            for name in filenames:
                try:
                    latest = max(latest, os.path.getmtime(os.path.join(dirpath, name)))
                except OSError:
                    continue  # 掃描期間被刪的檔案：略過
        for name in _STALENESS_TOP_FILES:
            try:
                latest = max(latest, os.path.getmtime(os.path.join(self.frontend_dir, name)))
            except OSError:
                continue  # 選配檔（remotion.config.*）不存在屬正常
        return latest

    def _build_bundle(self) -> bool:
        """執行 ``npx remotion bundle`` 落地常駐 bundle；成功寫 marker 回 True，失敗回 False。"""
        cmd = ["npx", "remotion", "bundle", self.entry_file, f"--out-dir={self.bundle_dir}"]
        logger.info(f"[RemotionAdapter] 重建常駐 bundle: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=self.frontend_dir,
                capture_output=True,
                text=True,
                timeout=REMOTION_RENDER_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"⚠️ [RemotionAdapter] bundle 逾時（{REMOTION_RENDER_TIMEOUT_SEC}s），回退 entry 直接 render")
            return False
        if result.returncode != 0:
            logger.warning(f"⚠️ [RemotionAdapter] bundle 失敗（回退 entry 直接 render）:\n{result.stderr}")
            return False

        # marker 的 mtime 即「打包時刻」；寫在成功之後，半途失敗不會留下新鮮假象
        marker = os.path.join(self.bundle_dir, _BUNDLE_MARKER_FILENAME)
        with open(marker, "w", encoding="utf-8") as f:
            f.write("ok")
        logger.info(f"[RemotionAdapter] 常駐 bundle 就緒: {self.bundle_dir}")
        return True
