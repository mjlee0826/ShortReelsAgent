"""
MusiqModelManager：MUSIQ 技術畫質評分器（手震 / 噪點 / 失焦偵測）。

Week 1 / Week 3a 變動
---------------------
Week 1 新增 :meth:`score_batch`(多張一次 forward),單張 :meth:`get_technical_score` 維持不變。
Week 3a 由 ``BatchCollector`` 接入,並把批次前處理從「center-crop 成正方形」改為
「每張走與單張完全相同的 :meth:`_preprocess_single` 保比例縮放 + 對批內最大 H/W zero-padding」再 stack
—— 內容區與單張逐像素一致,差異僅來自 padding 區,最大化與單張分數的一致性。

設計模式
--------
- **Template Method**：批次直接複用單張的 :meth:`_preprocess_single` 與 :meth:`_clamp_score`，
  保證內容前處理一致、避免重複。
- **Null Object**：失敗時整批回填 ``DEFAULT_FALLBACK_SCORE``，下游無需特例處理。
"""
import torch
import torch.nn.functional as F
import gc
from PIL import Image
import torchvision.transforms as transforms
import pyiqa
from model.base_model_manager import (
    BaseModelManager,
    synchronized_inference,
    oom_resilient,
    is_cuda_oom,
)
from config.media_processor_config import MUSIQ_TRANSIENT_VRAM_GB
from config.model_config import (
    MUSIQ_METRIC_NAME,
    MUSIQ_MAX_SHORT_SIDE,
    DEFAULT_FALLBACK_SCORE,
    SCORE_MIN,
    SCORE_MAX,
)


class MusiqModelManager(BaseModelManager):
    """技術畫質評估大腦 (MUSIQ)，精準辨別手震廢片與唯美景深。"""

    # Week 3b：單次 forward 暫態峰值 → BudgetGate 記帳（INFERENCE_PRIORITY 維持預設 0）
    INFERENCE_VRAM_COST_GB = MUSIQ_TRANSIENT_VRAM_GB

    def _initialize(self, device_id: int = 0):
        """透過 PyIQA 載入 MUSIQ 模型，權重自動下載。"""
        self.device = torch.device(self.get_device_str(device_id))
        with self._log_load("MUSIQ"):
            self.metric_network = pyiqa.create_metric(MUSIQ_METRIC_NAME, device=self.device)
            self.transform = transforms.ToTensor()

    @oom_resilient
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
            # CUDA OOM 往上拋給 @oom_resilient 重試；其餘維持 Null Object（保底分數）
            if is_cuda_oom(e):
                raise
            print(f"[Technical Scorer Error] 畫質評估失敗: {e}")
            return DEFAULT_FALLBACK_SCORE
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    @oom_resilient
    @synchronized_inference
    def score_batch(self, pil_images: list[Image.Image]) -> list[float]:
        """
        對多張 PIL 圖片一次 forward，回傳 0~100 分數列表（與輸入順序一致）。

        每張先走與單張完全相同的 :meth:`_preprocess_single`（保比例縮放，短邊 ≤ MUSIQ_MAX_SHORT_SIDE），
        轉 tensor 後對批內最大 (H, W) 做右下 zero-padding，再 stack 成 ``[N, C, maxH, maxW]`` 一次 forward。
        如此每張的內容前處理與單張逐像素一致，分數差異僅來自 padding 區（不裁切、不丟內容）。
        失敗時整批回填 ``DEFAULT_FALLBACK_SCORE``，呼叫端無需特例處理。
        """
        if not pil_images:
            # 早退：空輸入直接回空列表，避免後續 torch.stack 拋空 tensor
            return []

        try:
            # 與單張同一條前處理 → 各張尺寸可不同（保比例，不裁切）
            tensors = [
                self.transform(self._preprocess_single(img)).to(self.device)
                for img in pil_images
            ]
            # 對批內最大高/寬做右下 padding（內容靠左上、補 0=黑），使形狀一致可 stack
            max_h = max(t.shape[1] for t in tensors)
            max_w = max(t.shape[2] for t in tensors)
            # F.pad 參數順序為 (左, 右, 上, 下)：只補右與下，保持內容區與單張對齊
            padded = [
                F.pad(t, (0, max_w - t.shape[2], 0, max_h - t.shape[1]))
                for t in tensors
            ]
            batch_tensor = torch.stack(padded, dim=0)  # [N, C, maxH, maxW]

            with torch.no_grad():
                # PyIQA metric_network 接受 batch tensor，回傳 [N] 形狀的分數
                raw_scores = self.metric_network(batch_tensor)

            # 攤平為 list，逐項裁切到 [SCORE_MIN, SCORE_MAX]
            return [self._clamp_score(float(s)) for s in raw_scores.flatten().tolist()]

        except Exception as e:
            # CUDA OOM 往上拋給 @oom_resilient 重試；其餘整批回保底分數（不阻擋下游）
            if is_cuda_oom(e):
                raise
            print(f"[Technical Scorer Batch Error] 畫質批次評估失敗: {e}")
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
    def _clamp_score(raw_score: float) -> float:
        """將原始分數裁切到 [SCORE_MIN, SCORE_MAX] 範圍。"""
        return max(SCORE_MIN, min(SCORE_MAX, raw_score))
