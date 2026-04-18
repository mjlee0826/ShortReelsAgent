import os
import urllib.request
import torch
import torch.nn as nn
import gc
from PIL import Image
from transformers import CLIPProcessor, CLIPModel

class LAIONAestheticMLP(nn.Module):
    """
    LAION 官方發布的 Aesthetic Predictor MLP 結構。
    完全由線性層組成，無卷積，計算開銷極低。
    """
    def __init__(self, input_size):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_size, 1024),
            nn.Dropout(0.2),
            nn.Linear(1024, 128),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1)
        )
    def forward(self, x):
        return self.layers(x)

class LaionModelManager:
    """
    單例模式 (Singleton): 美學打分大腦。
    結合 CLIP 特徵提取與 LAION Aesthetic Predictor，專職評估畫面的美感與構圖。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LaionModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 1. 初始化 CLIP (作為視覺特徵提取器)
        self.clip_id = "openai/clip-vit-large-patch14"
        self.processor = CLIPProcessor.from_pretrained(self.clip_id)
        self.clip_model = CLIPModel.from_pretrained(self.clip_id).to(self.device).eval()
        
        # 2. 初始化 LAION MLP
        self.mlp = LAIONAestheticMLP(768).to(self.device).eval()
        
        # 自動下載官方開源的評分器權重
        weight_path = "sac+logos+ava1-l14-linearMSE.pth"
        if not os.path.exists(weight_path):
            print("正在下載 LAION Aesthetic 權重...")
            url = "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac+logos+ava1-l14-linearMSE.pth"
            urllib.request.urlretrieve(url, weight_path)
            
        self.mlp.load_state_dict(torch.load(weight_path, map_location=self.device))

    def _normalize_score(self, raw_score: float) -> float:
        """
        LAION 分數通常為 1~10 分制，將其轉換為系統統一的 0~100 分制。
        """
        clamped_score = max(1.0, min(10.0, raw_score))
        return (clamped_score - 1.0) / 9.0 * 100.0

    def get_aesthetic_score(self, pil_image: Image.Image) -> float:
        """
        輸入 PIL 圖片，回傳 0~100 的美學分數。
        """
        try:
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
                
            inputs = self.processor(images=pil_image, return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                # 【修復 Bug】使用 get_image_features 只跑視覺通道，避免缺少 input_ids 的報錯
                image_features = self.clip_model.get_image_features(**inputs)
                
                # 【防呆機制】因應不同版本的 transformers，確保取出來的一定是純 Tensor
                if not isinstance(image_features, torch.Tensor):
                    if hasattr(image_features, "image_embeds"):
                        image_features = image_features.image_embeds
                    elif hasattr(image_features, "pooler_output"):
                        image_features = image_features.pooler_output
                    else:
                        image_features = image_features[0]

                # L2 正規化 (LAION 模型的硬性要求)
                image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                
                # 透過 MLP 預測分數
                prediction = self.mlp(image_features)
                raw_score = prediction.item()
            
            print(prediction)
            print(raw_score)
            return self._normalize_score(raw_score)
            
        except Exception as e:
            print(f"[Aesthetic Scorer Error] 美學評估失敗: {e}")
            return 60.0
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()