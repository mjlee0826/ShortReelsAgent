import torch
import gc
from PIL import Image
import torchvision.transforms as transforms
import pyiqa

class ManiqaModelManager:
    """
    單例模式 (Singleton): 技術畫質評估大腦。
    使用 PyIQA 庫載入 MANIQA 模型，專職偵測畫面是否失焦、模糊、存在噪點。
    無套件衝突，推論穩定且精確度極高。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ManiqaModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # 載入 MANIQA (No-Reference 畫質評估模型)
        # pyiqa 會自動處理權重的下載與快取
        self.metric_network = pyiqa.create_metric('maniqa', device=self.device)
        self.transform = transforms.ToTensor()

    def _normalize_score(self, raw_score: float) -> float:
        """
        【已修復 Bug】
        PyIQA 框架下的 MANIQA 模型預設會將分數正規化到 0.0 ~ 1.0 之間 (越高代表畫質越好)。
        我們直接將其按比例放大為系統統一的 0~100 分制。
        """
        # 防止意外的極端值超出邊界
        clamped_score = max(0.0, min(1.0, raw_score))
        return clamped_score * 100.0

    def get_technical_score(self, pil_image: Image.Image) -> float:
        """
        輸入 PIL 圖片，回傳 0~100 的技術畫質分數。
        """
        try:
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
            
            # 將 PIL Image 轉換為 PyIQA 預期的 Tensor 格式 [1, C, H, W]
            img_tensor = self.transform(pil_image).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                # 取得預測分數 (預期範圍 0.0 ~ 1.0)
                raw_score = self.metric_network(img_tensor).item()
            
            return self._normalize_score(raw_score)
            
        except Exception as e:
            print(f"[Technical Scorer Error] 畫質評估失敗: {e}")
            return 60.0 # 失敗時給予預設及格分，避免誤砍素材
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()