import numpy as np
from PIL import Image
from rembg import new_session, remove
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import SALIENCY_MODEL_NAME


class SaliencyModelManager(BaseModelManager):
    """顯著性偵測大腦 (U²-Net)，計算主體重心座標與精準模糊度。"""

    def _initialize(self, device_id: int = 0):
        """
        載入 U2-Net 輕量級模型 session。
        rembg 內部自行管理 device，device_id 保留以維持簽名一致性。
        """
        self.session = new_session(SALIENCY_MODEL_NAME)

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
