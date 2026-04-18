import torch
from transformers import pipeline

class WhisperModelManager:
    """
    單例模式 (Singleton): 確保 Whisper 語音辨識模型只實例化一次。
    本次升級：加入針對 Transformer 自迴歸死迴圈的防跳針過濾器。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WhisperModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.model_id = "openai/whisper-large-v3"
        
        self.transcriber = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            device=self.device,
            chunk_length_s=30,
            return_timestamps=True 
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
            # 轉小寫並去除前後空白，避免因標點或空格導致誤判
            current_text = chunk["text"].strip().lower()
            
            if not current_text:
                continue

            if current_text == last_text:
                consecutive_count += 1
            else:
                consecutive_count = 1
                last_text = current_text

            # 如果同一個句子連續跨越了 3 個時間 Chunk，判定為 Attention 鎖死
            if consecutive_count >= 3:
                # 把前面已經收錄的兩次「幻覺開頭」也一併刪除，確保資料乾淨
                if len(cleaned_chunks) >= 2:
                    cleaned_chunks = cleaned_chunks[:-2]
                
                # 終止後續的解析，因為模型一旦進入迴圈，後面的輸出通常也全是垃圾
                break 
            else:
                cleaned_chunks.append(chunk)

        # 將過濾後的乾淨 Chunk 重新組合回完整的純文字
        final_text = " ".join([c["text"].strip() for c in cleaned_chunks])
        
        return {
            "text": final_text,
            "chunks": cleaned_chunks
        }

    def transcribe(self, audio_path: str) -> dict:
        """
        輸入音檔路徑，回傳乾淨且無幻覺的逐字稿。
        """
        try:
            # 1. 取得原始推論結果
            raw_result = self.transcriber(
                audio_path, 
                generate_kwargs={
                    "task": "transcribe",
                    "condition_on_prev_tokens": False
                }
            )
            
            # 2. 經過防跳針過濾器後回傳
            return self._filter_hallucination(raw_result)
            
        except Exception as e:
            return {"text": "", "error": str(e)}