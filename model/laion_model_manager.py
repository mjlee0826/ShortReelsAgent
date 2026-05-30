"""
LaionModelManager：LAION Aesthetic Predictor + CLIP 美學評分器。

Week 1 變動
-----------
新增 :meth:`score_batch` 一次處理多張，由 ``CLIPProcessor`` 直接吃 ``list[PIL.Image]``。
單張介面 :meth:`get_aesthetic_score` 維持不變。

設計模式
--------
- **Template Method**：``_extract_features`` 內部封裝 CLIP 特徵提取 + L2 normalize，
  單張與批次共用。
- **Null Object**：失敗時整批回填 ``DEFAULT_FALLBACK_SCORE``。
"""
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
            normalized_image = self._ensure_rgb(pil_image)

            with torch.no_grad():
                features = self._extract_features([normalized_image])  # [1, D]
                raw_score = self.mlp(features).item()

            return self._final_score(raw_score)

        except Exception as e:
            print(f"[Aesthetic Scorer Error] 美學評估失敗: {e}")
            return DEFAULT_FALLBACK_SCORE
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    @synchronized_inference
    def score_batch(self, pil_images: list[Image.Image]) -> list[float]:
        """
        對多張 PIL 圖片一次 forward，回傳 0~100 分數列表（與輸入順序一致）。

        ``CLIPProcessor`` 原生支援 list 輸入，內部會自動 padding / stack；
        MLP 為線性層可直接吃 ``[N, D]`` 形狀，無需特殊處理。
        失敗時整批回填 ``DEFAULT_FALLBACK_SCORE``。
        """
        if not pil_images:
            # 早退：空輸入直接回空列表，避免 CLIPProcessor 拋出例外
            return []

        try:
            normalized_images = [self._ensure_rgb(img) for img in pil_images]

            with torch.no_grad():
                features = self._extract_features(normalized_images)  # [N, D]
                # MLP 輸出形狀 [N, 1]，攤平為 [N] 後逐項標準化
                raw_scores = self.mlp(features).flatten().tolist()

            return [self._final_score(s) for s in raw_scores]

        except Exception as e:
            print(f"[Aesthetic Scorer Batch Error] 美學批次評估失敗: {e}")
            return [DEFAULT_FALLBACK_SCORE] * len(pil_images)
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def _extract_features(self, pil_images: list[Image.Image]) -> torch.Tensor:
        """
        使用 CLIP 取得 ``[N, D]`` 影像特徵並做 L2 normalize（單張與批次共用）。

        相容於不同 transformers 版本的回傳型態（Tensor 或 ModelOutput）。
        """
        inputs = self.processor(images=pil_images, return_tensors="pt").to(self.device)
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
        return image_features / image_features.norm(p=2, dim=-1, keepdim=True)

    @staticmethod
    def _ensure_rgb(pil_image: Image.Image) -> Image.Image:
        """確保影像為 RGB 模式，避免 CLIPProcessor 對 RGBA / L 模式行為不一致。"""
        if pil_image.mode != "RGB":
            return pil_image.convert("RGB")
        return pil_image

    def _final_score(self, raw_score: float) -> float:
        """將 LAION 原始分數轉成 0~100 分制並裁切到合法範圍。"""
        return max(SCORE_MIN, min(SCORE_MAX, self._normalize_score(raw_score)))
