"""
SaliencyModelManager：顯著性偵測管理器，使用 U²-Net (rembg) 計算主體遮罩。

設計模式
--------
- **Template Method**：繼承 ``BaseModelManager``，只實作 ``_initialize`` 與業務方法，
  鎖序、Singleton 等機制由基底類別提供。
- **Adapter Pattern**：將 rembg/onnxruntime 的 session API 封裝為統一 ``get_saliency_mask`` 介面，
  上層 processor 無須感知底層 onnxruntime session 細節。
- **Null Object**：遮罩生成失敗時回傳全白陣列（退回傳統全局計算），下游無需特例處理。

GPU 策略
--------
強制使用 ``CPUExecutionProvider``，完全脫離 GPU 資源爭用（詳見 ``_initialize``）。
``self.device = "cpu"`` 使 ``_uses_gpu()`` 為 False，forward 自動跳過 L2 GpuGate 與
ModelPool 即時 VRAM 重檢。
"""
import numpy as np
from PIL import Image
from rembg import new_session, remove
from model.infra.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import SALIENCY_MODEL_NAME
from config.media_processor_config import SALIENCY_TRANSIENT_VRAM_GB

# rembg/onnxruntime 執行提供者：強制只用 CPU，徹底脫離 GPU（見 SaliencyModelManager._initialize）
_CPU_EXECUTION_PROVIDER = "CPUExecutionProvider"
# self.device 的 CPU 字串：與 BaseModelManager.get_device_str 的 'cpu' 回傳一致，
# 使 _uses_gpu() 為 False → forward 跳過 L2 GpuGate、pool 借出也跳過即時 VRAM 重檢
_CPU_DEVICE = "cpu"


class SaliencyModelManager(BaseModelManager):
    """顯著性偵測大腦 (U²-Net)，計算主體重心座標與精準模糊度。"""

    # 此值僅在「走 GPU、forward 經 L2 BudgetGate」時才會被讀取；本管理器已固定 CPU 執行
    # （見 _initialize），forward 時 _uses_gpu() 為 False 會跳過 L2，故目前不生效。
    # 保留宣告供未來若改回 GPU 時參考，並維持 SALIENCY_TRANSIENT_VRAM_GB 匯入有被使用。
    INFERENCE_VRAM_COST_GB: float = SALIENCY_TRANSIENT_VRAM_GB

    def _initialize(self, device_id: int = 0):
        """
        載入 U2-Net session，**固定綁定 CPU**（完全不使用 GPU）。

        為何不走 GPU：原本用 onnxruntime ``CUDAExecutionProvider`` 與 PyTorch 共用同一張卡，
        兩者各自的記憶體 allocator / CUDA context 互不知道彼此，在共用工作站上會出兩類故障——
        (1) **載入期**：onnxruntime arena 配不到 VRAM 直接 OOM，且因 warm_up 未隔離而連帶打掛啟動；
        (2) **推論期**：在持有 GIL 的狀態下卡死，凍結整個直譯器（StallWatchdog C 層 dump 的根因）。
        改跑 CPU 後 onnxruntime 不再碰 GPU，且 CPU EP 推論會釋放 GIL，根除上述兩類故障。

        ``device_id`` 仍由 pool 傳入作為 ``(device_id, slot_id)`` singleton key（保留同時多份
        instance 的 CPU 併發），但**不再用於 GPU 綁定**。``self.device`` 固定為 ``"cpu"`` →
        forward 經 ``inference_guard`` 時 ``_uses_gpu()`` 為 False，自動跳過 L2 GpuGate；
        ModelPool 借出前的即時 VRAM 重檢也因 device 非 cuda 直接放行（不再空等 GPU VRAM）。
        """
        # 先設好 device 再進載入日誌：固定 CPU 是移出 GPU 的關鍵，且讓啟動日誌直接顯示 device=cpu 便於確認
        self.device = _CPU_DEVICE
        with self._log_load("Saliency"):
            self.session = self._build_session()

    def _build_session(self):
        """建立 rembg session，明確只給 ``CPUExecutionProvider``（絕不落到 GPU）。"""
        try:
            # 必須顯式指定 CPU provider：rembg 預設用 ort.get_available_providers()，
            # 在裝了 onnxruntime-gpu 的機器上會自動帶入 CUDAExecutionProvider，故不可省略。
            return new_session(SALIENCY_MODEL_NAME, providers=[_CPU_EXECUTION_PROVIDER])
        except TypeError:
            # 舊版 rembg new_session 不收 providers → 退回預設 session（不擋啟動）
            return new_session(SALIENCY_MODEL_NAME)

    @synchronized_inference
    def get_saliency_mask(self, pil_image: Image.Image) -> np.ndarray:
        """
        輸入 PIL 圖片，回傳 2D numpy 陣列的遮罩 (0~255)。
        白色 (255) 代表主體，黑色 (0) 代表背景。
        """
        try:
            result_img = remove(pil_image, session=self.session, only_mask=True)
            return np.array(result_img)
        except Exception as e:
            print(f"[Saliency Error] 遮罩生成失敗: {e}")
            # 若失敗，回傳全白遮罩 (退回傳統全局計算)
            return np.ones((pil_image.height, pil_image.width), dtype=np.uint8) * 255
