"""
WhisperModelManager：Whisper 語音辨識器（含幻覺防跳針過濾）。

Week 1 變動
-----------
新增 :meth:`transcribe_batch` 介面：HF pipeline 原生支援 list[audio_path] 一次推論。
單張介面 :meth:`transcribe` 維持不變。

設計模式
--------
- **Post-processing Filter**：``_filter_hallucination`` 對單筆結果做後處理，
  單張與批次共用，避免重複實作。
- **Null Object**：失敗時整批回填 ``{"text": "", "error": str(...)}``，下游契約一致。
"""
import torch
from transformers import pipeline
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    WHISPER_MODEL_ID,
    WHISPER_CHUNK_LENGTH_SEC,
    WHISPER_HALLUCINATION_THRESHOLD,
)


# Whisper generate 的共用參數，單張與批次共用
_GENERATE_KWARGS = {
    "task": "transcribe",
    "condition_on_prev_tokens": False,
}


class WhisperModelManager(BaseModelManager):
    """Whisper 語音辨識大腦（含幻覺防跳針過濾器）。"""

    def _initialize(self, device_id: int = 0):
        """載入 Whisper pipeline，使用 FP16 加速並啟用時間戳記。"""
        self.device = self.get_device_str(device_id)
        self.transcriber = pipeline(
            "automatic-speech-recognition",
            model=WHISPER_MODEL_ID,
            device=self.device,
            chunk_length_s=WHISPER_CHUNK_LENGTH_SEC,
            return_timestamps=True,
            dtype=torch.float16
        )

    def _filter_hallucination(self, raw_result: dict) -> dict:
        """
        後處理過濾器 (Post-processing Filter)：
        偵測連續重複的 Chunk，一旦發生死迴圈，直接切斷並丟棄幻覺雜音。
        """
        raw_chunks = raw_result.get("chunks", [])
        cleaned_chunks = []
        consecutive_count = 1
        last_text = ""

        for chunk in raw_chunks:
            current_text = chunk["text"].strip().lower()
            if not current_text:
                continue

            if current_text == last_text:
                consecutive_count += 1
            else:
                consecutive_count = 1
                last_text = current_text

            if consecutive_count >= WHISPER_HALLUCINATION_THRESHOLD:
                # 把前面已收錄的幻覺開頭也一併刪除
                trim_count = WHISPER_HALLUCINATION_THRESHOLD - 1
                if len(cleaned_chunks) >= trim_count:
                    cleaned_chunks = cleaned_chunks[:-trim_count]
                # 模型一旦進入迴圈，後面輸出通常也全是垃圾，終止解析
                break
            else:
                cleaned_chunks.append(chunk)

        final_text = " ".join([c["text"].strip() for c in cleaned_chunks])
        return {"text": final_text, "chunks": cleaned_chunks}

    @synchronized_inference
    def transcribe(self, audio_path: str) -> dict:
        """輸入音檔路徑，回傳乾淨且無幻覺的逐字稿。"""
        try:
            raw_result = self.transcriber(audio_path, generate_kwargs=_GENERATE_KWARGS)
            return self._filter_hallucination(raw_result)
        except Exception as e:
            return {"text": "", "error": str(e)}

    @synchronized_inference
    def transcribe_batch(self, audio_paths: list[str]) -> list[dict]:
        """
        對多個音檔一次推論，回傳結果列表（與輸入順序一致）。

        HF Whisper pipeline 直接接受 ``list[str]``，內部會自動 batch；
        每個結果套用 :meth:`_filter_hallucination` 後輸出。
        整批失敗時回填 ``{"text": "", "error": ...}``，與單張契約一致。
        """
        if not audio_paths:
            # 早退：空輸入直接回空列表，避免下游零長度迭代誤判
            return []

        try:
            # HF pipeline 對 list 輸入回 list，順序與輸入一致
            raw_results = self.transcriber(audio_paths, generate_kwargs=_GENERATE_KWARGS)
            # transcriber 對單一 dict 與 list[dict] 都可能出現，統一包成 list 後處理
            normalized = raw_results if isinstance(raw_results, list) else [raw_results]
            return [self._filter_hallucination(r) for r in normalized]

        except Exception as e:
            # 整批失敗仍須回傳等長 list，下游 zip 對齊不會錯位
            return [{"text": "", "error": str(e)} for _ in audio_paths]
