import torch
import gc
from PIL import Image
import torchvision.transforms as transforms
import pyiqa
from model.base_model_manager import BaseModelManager

class MusiqModelManager(BaseModelManager):
    """技術畫質評估大腦 (MUSIQ)，精準辨別手震廢片與唯美景深。"""

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
            
            
            max_size = 512
            width, height = pil_image.size
            if min(width, height) > max_size:
                # 保持比例縮放，讓短邊等於 max_size
                scale = max_size / min(width, height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                pil_image = pil_image.resize((new_width, new_height), Image.Resampling.BILINEAR)
                
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