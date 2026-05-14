import torch
import gc
from PIL import Image
import torchvision.transforms as transforms
import pyiqa
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    MUSIQ_METRIC_NAME,
    MUSIQ_MAX_SHORT_SIDE,
    DEFAULT_FALLBACK_SCORE,
    SCORE_MIN,
    SCORE_MAX,
)


class MusiqModelManager(BaseModelManager):
    """技術畫質評估大腦 (MUSIQ)，精準辨別手震廢片與唯美景深。"""

    def _initialize(self, device_id: int = 0):
        """透過 PyIQA 載入 MUSIQ 模型，權重自動下載。"""
        self.device = torch.device(self.get_device_str(device_id))
        self.metric_network = pyiqa.create_metric(MUSIQ_METRIC_NAME, device=self.device)
        self.transform = transforms.ToTensor()

    @synchronized_inference
    def get_technical_score(self, pil_image: Image.Image) -> float:
        """輸入 PIL 圖片，回傳 0~100 的技術畫質分數。"""
        try:
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            width, height = pil_image.size
            if min(width, height) > MUSIQ_MAX_SHORT_SIDE:
                # 保持比例縮放，讓短邊等於 MUSIQ_MAX_SHORT_SIDE
                scale = MUSIQ_MAX_SHORT_SIDE / min(width, height)
                new_size = (int(width * scale), int(height * scale))
                pil_image = pil_image.resize(new_size, Image.Resampling.BILINEAR)

            # 轉換為 PyIQA 預期的 Tensor 格式 [1, C, H, W]
            img_tensor = self.transform(pil_image).unsqueeze(0).to(self.device)

            with torch.no_grad():
                # MUSIQ 在 KonIQ-10k 資料集上的輸出本來就是 0~100 分制
                raw_score = self.metric_network(img_tensor).item()

            return max(SCORE_MIN, min(SCORE_MAX, float(raw_score)))

        except Exception as e:
            print(f"[Technical Scorer Error] 畫質評估失敗: {e}")
            return DEFAULT_FALLBACK_SCORE
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
