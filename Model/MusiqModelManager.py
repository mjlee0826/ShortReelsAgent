import torch
import gc
from PIL import Image
import torchvision.transforms as transforms
import pyiqa

class MusiqModelManager:
    """
    單例模式 (Singleton): 技術畫質評估大腦。
    【核心升級】將 MANIQA 替換為 MUSIQ (Multi-scale Image Quality Transformer)。
    原因：解決傳統 IQA 模型將「攝影景深 (Bokeh)」誤判為「模糊」的致命缺陷。
    MUSIQ 基於真實世界照片訓練，能精準放行唯美景深，並攔截真正的手震與失焦廢片。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MusiqModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # 【修改 1】改載入 musiq 模型。PyIQA 會自動下載 MUSIQ 權重
        self.metric_network = pyiqa.create_metric('musiq', device=self.device)
        self.transform = transforms.ToTensor()

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
                # 【修改 2】MUSIQ 在 KonIQ-10k 資料集上的輸出本來就是 0~100 分制
                # 分數越高代表畫質越好、越清晰，完全不需要額外的數學正規化轉換
                raw_score = self.metric_network(img_tensor).item()
            
            # 確保分數不超出常理邊界
            final_score = max(0.0, min(100.0, float(raw_score)))
            return final_score
            
        except Exception as e:
            print(f"[Technical Scorer Error] 畫質評估失敗: {e}")
            return 60.0 # 失敗時給予預設及格分，避免誤砍素材
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()