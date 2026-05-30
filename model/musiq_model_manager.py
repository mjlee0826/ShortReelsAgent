"""
MusiqModelManager：MUSIQ 技術畫質評分器（手震 / 噪點 / 失焦偵測）。

Week 1 變動
-----------
新增 :meth:`score_batch` 介面，多張圖片一次 forward。
單張介面 :meth:`get_technical_score` 維持不變，呼叫端零侵入。
Batch 介面預計於 Week 3a ``BatchCollector`` 接入，本週只提供方法。

設計模式
--------
- **Template Method**：與單張共用 ``_preprocess`` 與 ``_clamp_score``，避免重複。
- **Null Object**：失敗時整批回填 ``DEFAULT_FALLBACK_SCORE``，下游無需特例處理。
"""
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


# Batch 模式統一邊長：短邊縮放後再 center-crop 至正方形，便於 stack
_BATCH_SQUARE_SIDE = MUSIQ_MAX_SHORT_SIDE


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
            preprocessed = self._preprocess_single(pil_image)

            # 轉換為 PyIQA 預期的 Tensor 格式 [1, C, H, W]
            img_tensor = self.transform(preprocessed).unsqueeze(0).to(self.device)

            with torch.no_grad():
                # MUSIQ 在 KonIQ-10k 資料集上的輸出本來就是 0~100 分制
                raw_score = self.metric_network(img_tensor).item()

            return self._clamp_score(float(raw_score))

        except Exception as e:
            print(f"[Technical Scorer Error] 畫質評估失敗: {e}")
            return DEFAULT_FALLBACK_SCORE
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    @synchronized_inference
    def score_batch(self, pil_images: list[Image.Image]) -> list[float]:
        """
        對多張 PIL 圖片一次 forward，回傳 0~100 分數列表（與輸入順序一致）。

        為了在 GPU 上 stack 成單一 batch tensor，所有圖片統一 resize 至
        ``MUSIQ_MAX_SHORT_SIDE × MUSIQ_MAX_SHORT_SIDE`` 正方形（短邊縮放 + 長邊 center-crop）。
        失敗時整批回填 ``DEFAULT_FALLBACK_SCORE``，呼叫端無需特例處理。
        """
        if not pil_images:
            # 早退：空輸入直接回空列表，避免後續 torch.stack 拋空 tensor
            return []

        try:
            # 所有圖片統一裁切到相同邊長後再 stack
            tensors = [
                self.transform(self._preprocess_for_batch(img)).to(self.device)
                for img in pil_images
            ]
            # [N, C, H, W]
            batch_tensor = torch.stack(tensors, dim=0)

            with torch.no_grad():
                # PyIQA metric_network 接受 batch tensor，回傳 [N] 形狀的分數
                raw_scores = self.metric_network(batch_tensor)

            # 攤平為 list，逐項裁切到 [SCORE_MIN, SCORE_MAX]
            return [self._clamp_score(float(s)) for s in raw_scores.flatten().tolist()]

        except Exception as e:
            print(f"[Technical Scorer Batch Error] 畫質批次評估失敗: {e}")
            # 失敗整批回填預設分數，保持「不阻擋下游」的契約
            return [DEFAULT_FALLBACK_SCORE] * len(pil_images)
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    @staticmethod
    def _preprocess_single(pil_image: Image.Image) -> Image.Image:
        """單張路徑前處理：保比例縮放，短邊不超過 ``MUSIQ_MAX_SHORT_SIDE``。"""
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        width, height = pil_image.size
        if min(width, height) > MUSIQ_MAX_SHORT_SIDE:
            # 保持比例縮放，讓短邊等於 MUSIQ_MAX_SHORT_SIDE
            scale = MUSIQ_MAX_SHORT_SIDE / min(width, height)
            new_size = (int(width * scale), int(height * scale))
            pil_image = pil_image.resize(new_size, Image.Resampling.BILINEAR)
        return pil_image

    @staticmethod
    def _preprocess_for_batch(pil_image: Image.Image) -> Image.Image:
        """
        Batch 路徑前處理：短邊縮至 ``_BATCH_SQUARE_SIDE``，長邊 center-crop 至同邊長。

        統一邊長以滿足 ``torch.stack`` 的形狀要求。
        若品質壓測發現偏差過大，Week 3a 可改為 dynamic padding 取代裁切。
        """
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        width, height = pil_image.size
        # Step 1：等比縮放，使短邊等於 _BATCH_SQUARE_SIDE
        scale = _BATCH_SQUARE_SIDE / min(width, height)
        new_size = (int(round(width * scale)), int(round(height * scale)))
        scaled = pil_image.resize(new_size, Image.Resampling.BILINEAR)

        # Step 2：對長邊 center-crop 至 _BATCH_SQUARE_SIDE，得正方形輸入
        new_w, new_h = scaled.size
        left = (new_w - _BATCH_SQUARE_SIDE) // 2
        top  = (new_h - _BATCH_SQUARE_SIDE) // 2
        return scaled.crop((left, top, left + _BATCH_SQUARE_SIDE, top + _BATCH_SQUARE_SIDE))

    @staticmethod
    def _clamp_score(raw_score: float) -> float:
        """將原始分數裁切到 [SCORE_MIN, SCORE_MAX] 範圍。"""
        return max(SCORE_MIN, min(SCORE_MAX, raw_score))
