import numpy as np
from PIL import Image
from rembg import new_session, remove

class SaliencyModelManager:
    """
    單例模式 (Singleton): 顯著性偵測大腦。
    使用 U²-Net 快速產生畫面主體的黑白遮罩 (Mask)，
    用於計算「主體重心座標」與「精準模糊度」。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SaliencyModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        # 載入 U2-Net 輕量級模型 session
        self.session = new_session("u2net")

    def get_saliency_mask(self, pil_image: Image.Image) -> np.ndarray:
        """
        輸入 PIL 圖片，回傳 2D numpy 陣列的遮罩 (0~255)。
        白色 (255) 代表主體，黑色 (0) 代表背景。
        """
        try:
            # 取得透明底圖，提取 Alpha 通道作為 Mask
            result_img = remove(pil_image, session=self.session, only_mask=True)
            mask = np.array(result_img)
            return mask
        except Exception as e:
            print(f"[Saliency Error] 遮罩生成失敗: {e}")
            # 若失敗，回傳全白遮罩 (退回傳統全局計算)
            return np.ones((pil_image.height, pil_image.width), dtype=np.uint8) * 255