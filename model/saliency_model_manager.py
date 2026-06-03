import numpy as np
from PIL import Image
from rembg import new_session, remove
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import SALIENCY_MODEL_NAME
from config.media_processor_config import SALIENCY_TRANSIENT_VRAM_GB


class SaliencyModelManager(BaseModelManager):
    """顯著性偵測大腦 (U²-Net)，計算主體重心座標與精準模糊度。"""

    # 單次推論暫態 VRAM（GB）：設了 self.device=cuda 後，forward 會經 L2 BudgetGate 以此記帳，
    # 避免 onnxruntime 在共用卡上不受控搶 VRAM 造成 OOM/hang（實機共用 GPU hang 的根因之一）。
    INFERENCE_VRAM_COST_GB: float = SALIENCY_TRANSIENT_VRAM_GB

    def _initialize(self, device_id: int = 0):
        """
        載入 U2-Net session，並**綁定到指定 GPU**。

        原本 rembg/onnxruntime 會自挑預設卡（常是 cuda:0），共用工作站上容易撞別人的 VRAM 而 hang；
        改由呼叫端（stage）傳入「最空的卡」device_id，這裡用 onnxruntime ``CUDAExecutionProvider``
        的 ``device_id`` 綁定該卡，並設 ``self.device`` 讓 forward 走 L2 BudgetGate（納入 VRAM 記帳）。
        無 CUDA 或舊版 rembg 不支援 providers 時，安全退回 CPU / 預設 session（至少不會 hang GPU）。
        """
        with self._log_load("Saliency"):
            self.device = self.get_device_str(device_id)
            self.session = self._build_session(device_id)

    def _build_session(self, device_id: int):
        """建立 rembg session：CUDA 可用時用 onnxruntime 綁定該卡，否則（或舊版不支援）退回預設。"""
        if not str(self.device).lower().startswith("cuda"):
            return new_session(SALIENCY_MODEL_NAME)
        providers = [
            ("CUDAExecutionProvider", {"device_id": device_id}),
            "CPUExecutionProvider",
        ]
        try:
            return new_session(SALIENCY_MODEL_NAME, providers=providers)
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
