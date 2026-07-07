"""
環境音分類引擎，使用 PANNs CNN14 對 AudioSet 527 類進行推論。

批次與單張介面
--------------
:meth:`classify_environment_batch` 對多檔一次 forward（變長音訊尾端 zero-pad 對齊），
由 ``BatchCollector`` 接入；:meth:`classify_environment` 處理單一音檔。
top-k 解析抽成共用 :meth:`_topk_labels`（Template Method），單張 / 批次共用；
失敗回空列表（Null Object）。
"""

import torch
import librosa
import numpy as np
import gc
from model.infra.base_model_manager import (
    BaseModelManager,
    synchronized_inference,
    oom_resilient,
    is_cuda_oom,
)
from config.media_processor_config import AUDIO_ENV_TRANSIENT_VRAM_GB
from config.model_config import AUDIO_ENV_TOP_K, AUDIO_SAMPLING_RATE, AUDIO_ENV_MIN_SCORE
import logging

logger = logging.getLogger(__name__)


# top-k 分數輸出的四捨五入小數位數（命名常數，避免 magic number；沿用單張歷史行為）
_SCORE_ROUND_DECIMALS = 4


class AudioEnvModelManager(BaseModelManager):
    """
    配接器模式 (Adapter Pattern)：封裝 PANNs CNN14 環境音分類器。
    PANNs（Pretrained Audio Neural Networks）以 AudioSet 527 類訓練，
    專為環境音設計，比 Whisper 架構更適合非語音聲音的分類任務。
    輸出 top-k 分類標籤與信心分數，結構化且易於下游 LLM 理解。
    """

    # PANNs CNN14 單次 forward 暫態峰值 → BudgetGate 記帳（INFERENCE_PRIORITY 維持預設 0）
    INFERENCE_VRAM_COST_GB = AUDIO_ENV_TRANSIENT_VRAM_GB

    def _initialize(self, device_id: int = 0):
        """載入 PANNs CNN14 模型（panns_inference 套件）。"""
        from panns_inference import AudioTagging
        self.device = self.get_device_str(device_id)
        with self._log_load("AudioEnv"):
            # AudioTagging 內部自動處理 GPU/CPU 分配
            self._tagger = AudioTagging(checkpoint_path=None, device=self.device)

    def warmup(self) -> None:
        """
        啟動單執行緒預載 librosa 解碼路徑（覆寫 base ``warmup``）。

        ``classify_environment*`` 首呼叫的 ``librosa.load`` 會延遲 import ``librosa.core.audio``
        （經 lazy_loader → ``inspect.stack``）並 dlopen libsndfile。提前在此單執行緒觸發，避免執行期
        多條 worker thread 首呼叫與其他原生 dlopen 撞動態連結器鎖造成死結。
        """
        try:
            import soundfile  # noqa: F401 — 觸發 libsndfile 的 dlopen（librosa 主要解碼後端）
        except Exception:
            # best-effort：後端缺失不擋啟動，librosa 執行期會自行 fallback 到其他解碼器
            pass
        # 存取屬性即經 lazy_loader.__getattr__ 載入 librosa.core.audio（含 inspect.stack 鏈）
        _ = librosa.load

    @oom_resilient
    @synchronized_inference
    def classify_environment(self, audio_path: str) -> list:
        """
        對音訊檔執行環境音分類，回傳 top-k 標籤與信心分數列表。
        輸出格式：[{"label": "crowd_cheering", "score": 0.82}, ...]
        失敗時靜默回傳空列表，不阻斷主流程。
        """
        try:
            audio_array, _ = librosa.load(audio_path, sr=AUDIO_SAMPLING_RATE, mono=True)
            # PANNs 期望輸入形狀為 (batch, samples)
            audio_tensor = audio_array[np.newaxis, :]

            with torch.no_grad():
                # panns_inference 的 inference() 回傳順序為 (clipwise_output, embedding)，
                # 第一個元素才是 527 類分數；舊寫法誤取第二個 embedding（CNN14 為 2048 維），
                # 使 argsort 出來的索引超出 labels 的 527 範圍，觸發 list index out of range。
                clipwise_output, _ = self._tagger.inference(audio_tensor)

            # clipwise_output shape: (1, 527)，取第一筆做 top-k 解析
            return self._topk_labels(clipwise_output[0])

        except Exception as e:
            # CUDA OOM 往上拋給 @oom_resilient 重試；其餘維持 Null Object（空列表）
            if is_cuda_oom(e):
                raise
            logger.error(f"[AudioEnv Error] 環境音分類失敗: {e}")
            return []
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    @oom_resilient
    @synchronized_inference
    def classify_environment_batch(self, audio_paths: list[str]) -> list[list]:
        """
        對多個音檔一次推論，回傳每檔的 top-k 標籤列表（與輸入順序一致）。

        變長音訊以尾端 zero-pad 補到批內最長後 stack 成 (N, samples) 一次 forward；
        padding 區為靜音，對真實內容的標籤影響極小（實機可比對單張確認 drift）。
        空輸入回 ``[]``；整批失敗回 ``[[] for _ in paths]``（Null Object，與單張契約一致）。
        """
        if not audio_paths:
            # 早退：空輸入直接回空列表，避免後續 np.stack 拋空陣列
            return []

        try:
            # 各檔長度不一，先全部載入再以尾端 zero-pad 對齊到批內最長
            arrays = [
                librosa.load(path, sr=AUDIO_SAMPLING_RATE, mono=True)[0]
                for path in audio_paths
            ]
            max_len = max(len(a) for a in arrays)
            batch = np.stack(
                [np.pad(a, (0, max_len - len(a))) for a in arrays], axis=0
            )  # (N, max_len)

            with torch.no_grad():
                # 與單張相同：取 (clipwise_output, embedding) 的第一個，shape (N, 527)
                clipwise_output, _ = self._tagger.inference(batch)

            return [self._topk_labels(clipwise_output[i]) for i in range(len(audio_paths))]

        except Exception as e:
            # CUDA OOM 往上拋給 @oom_resilient 重試；其餘整批回等長 Null Object（下游 zip 不錯位）
            if is_cuda_oom(e):
                raise
            logger.error(f"[AudioEnv Batch Error] 環境音批次分類失敗: {e}")
            return [[] for _ in audio_paths]
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def _topk_labels(self, scores) -> list:
        """
        從單筆 clipwise 輸出 (527,) 取信心最高的 top-k 標籤，過濾低於門檻者（單張 / 批次共用）。

        輸出格式：``[{"label": ..., "score": ...}, ...]``，分數四捨五入到 ``_SCORE_ROUND_DECIMALS`` 位。
        """
        # argsort 由小到大 → 反轉取前 K 高分；CNN14 clipwise 為 527 維，索引必落在 labels 範圍內
        top_indices = np.argsort(scores)[::-1][:AUDIO_ENV_TOP_K]
        labels = self._tagger.labels
        return [
            {"label": labels[idx], "score": round(float(scores[idx]), _SCORE_ROUND_DECIMALS)}
            for idx in top_indices
            if scores[idx] > AUDIO_ENV_MIN_SCORE
        ]
