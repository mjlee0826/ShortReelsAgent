import torch
from transformers import pipeline
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    WHISPER_MODEL_ID,
    WHISPER_CHUNK_LENGTH_SEC,
    WHISPER_HALLUCINATION_THRESHOLD,
)


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
            raw_result = self.transcriber(
                audio_path,
                generate_kwargs={
                    "task": "transcribe",
                    "condition_on_prev_tokens": False
                }
            )
            return self._filter_hallucination(raw_result)
        except Exception as e:
            return {"text": "", "error": str(e)}
