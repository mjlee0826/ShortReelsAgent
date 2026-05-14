import os
import urllib.request
import torch
import torch.nn as nn
import gc
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    LAION_CLIP_MODEL_ID,
    LAION_MLP_INPUT_SIZE,
    LAION_SCORE_MIN,
    LAION_SCORE_MAX,
    LAION_WEIGHT_FILENAME,
    LAION_WEIGHT_URL,
    DEFAULT_FALLBACK_SCORE,
    SCORE_MIN,
    SCORE_MAX,
)


class LAIONAestheticMLP(nn.Module):
    """
    LAION 官方發布的 Aesthetic Predictor MLP 結構。
    完全由線性層組成，無卷積，計算開銷極低。
    """

    def __init__(self, input_size: int):
        """建立 MLP 各層結構。"""
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

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向傳播。"""
        return self.layers(x)


class LaionModelManager(BaseModelManager):
    """美學打分大腦 (LAION Aesthetic Predictor + CLIP)，評估畫面美感與構圖。"""

    def _initialize(self, device_id: int = 0):
        """初始化 CLIP 特徵提取器與 LAION MLP 評分器，必要時自動下載權重。"""
        self.device = self.get_device_str(device_id)

        self.processor = CLIPProcessor.from_pretrained(LAION_CLIP_MODEL_ID)
        self.clip_model = CLIPModel.from_pretrained(LAION_CLIP_MODEL_ID).to(self.device).eval()

        self.mlp = LAIONAestheticMLP(LAION_MLP_INPUT_SIZE).to(self.device).eval()

        # 權重固定存放在 model/ 目錄旁，避免 cwd 差異
        weight_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LAION_WEIGHT_FILENAME)
        if not os.path.exists(weight_path):
            print("正在下載 LAION Aesthetic 權重...")
            urllib.request.urlretrieve(LAION_WEIGHT_URL, weight_path)

        # weights_only=True 防止反序列化任意程式碼（PyTorch >= 2.0 安全要求）
        self.mlp.load_state_dict(torch.load(weight_path, map_location=self.device, weights_only=True))

    def _normalize_score(self, raw_score: float) -> float:
        """將 LAION 1~10 分制轉換為系統統一的 0~100 分制。"""
        clamped = max(LAION_SCORE_MIN, min(LAION_SCORE_MAX, raw_score))
        return (clamped - LAION_SCORE_MIN) / (LAION_SCORE_MAX - LAION_SCORE_MIN) * 100.0

    @synchronized_inference
    def get_aesthetic_score(self, pil_image: Image.Image) -> float:
        """輸入 PIL 圖片，回傳 0~100 的美學分數。"""
        try:
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            inputs = self.processor(images=pil_image, return_tensors="pt").to(self.device)

            with torch.no_grad():
                image_features = self.clip_model.get_image_features(**inputs)

                # 因應不同版本的 transformers，確保取出來的一定是純 Tensor
                if not isinstance(image_features, torch.Tensor):
                    if hasattr(image_features, "image_embeds"):
                        image_features = image_features.image_embeds
                    elif hasattr(image_features, "pooler_output"):
                        image_features = image_features.pooler_output
                    else:
                        image_features = image_features[0]

                # LAION 模型的硬性要求：L2 正規化
                image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                raw_score = self.mlp(image_features).item()

            return max(SCORE_MIN, min(SCORE_MAX, self._normalize_score(raw_score)))

        except Exception as e:
            print(f"[Aesthetic Scorer Error] 美學評估失敗: {e}")
            return DEFAULT_FALLBACK_SCORE
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
