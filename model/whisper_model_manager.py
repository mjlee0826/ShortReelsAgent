"""
WhisperModelManager：Whisper 語音辨識器（faster-whisper / CTranslate2 後端 + 幻覺防跳針過濾）。

後端切換
--------
自 large-v3（HF ``transformers`` pipeline）改為 **faster-whisper（CTranslate2）跑 large-v3-turbo**：
- turbo decoder 僅 4 層（large-v3 為 32 層），多語保留、速度數倍。
- CTranslate2 以量化 kernel（CUDA float16 / CPU int8）再加速並降 VRAM。
- ``info.language`` 直接提供偵測語言 —— 舊 HF pipeline 路徑未提供此欄位（``spoken_language`` 一直為空），
  本版於回傳補上 ``"language"``，下游 ``WhisperStage`` 的 ``spoken_language`` 自此真正生效。

批次說明
--------
faster-whisper 原生不支援「多檔一次 forward」（其 ``BatchedInferencePipeline`` 是單檔分段批次，軸不同）。
:meth:`transcribe_batch` 改以單一借出實例**循序**轉錄多檔，維持 ``BatchCollector`` 的 list→list 等長契約；
短音訊本就少受跨檔合批之益，turbo + CT2 的單次速度足以覆蓋。

設計模式
--------
- **Adapter**：把 faster-whisper 的 ``(segments, info)`` 串流封裝成與舊 HF 路徑一致的
  ``{"text", "chunks":[{"text","timestamp"}], "language"}`` dict，下游零改動。
- **Post-processing Filter**：``_filter_hallucination`` 對單筆結果做後處理，單張與批次共用。
- **Null Object**：失敗時回填 ``{"text": "", "chunks": [], "language": "", "error": ...}``，下游契約一致。
"""
import numpy as np
from faster_whisper import WhisperModel
from model.base_model_manager import (
    BaseModelManager,
    synchronized_inference,
    oom_resilient,
    is_cuda_oom,
)
from config.media_processor_config import WHISPER_TRANSIENT_VRAM_GB
from config.model_config import (
    WHISPER_MODEL_ID,
    WHISPER_CUDA_COMPUTE_TYPE,
    WHISPER_CPU_COMPUTE_TYPE,
    WHISPER_BEAM_SIZE,
    WHISPER_VAD_FILTER,
    WHISPER_HALLUCINATION_THRESHOLD,
    MODEL_WEIGHTS_DIR,
)


# CTranslate2 的 device 名（self.device 為 'cuda:N' / 'cpu'，CT2 則把 device 與 device_index 拆開收）
_CT2_DEVICE_CUDA = "cuda"
_CT2_DEVICE_CPU = "cpu"
# transcribe 共用參數：condition_on_previous_text=False 抑制跨段幻覺（對齊舊 condition_on_prev_tokens=False）
_TRANSCRIBE_KWARGS = {
    "task": "transcribe",
    "beam_size": WHISPER_BEAM_SIZE,
    "condition_on_previous_text": False,
    "vad_filter": WHISPER_VAD_FILTER,
}
# warmup 用的靜音樣本長度（秒）與取樣率：單執行緒先觸發 CT2 kernel 編譯 / 原生庫載入
_WARMUP_SILENCE_SEC = 1
_WARMUP_SAMPLE_RATE = 16000
# 偵測語言為 None 時的後備值（下游 spoken_language 期望 str）
_DEFAULT_LANGUAGE = ""


class WhisperModelManager(BaseModelManager):
    """Whisper 語音辨識大腦（faster-whisper / CTranslate2，含幻覺防跳針過濾器）。"""

    # 單次轉錄暫態峰值 → BudgetGate 記帳（INFERENCE_PRIORITY 維持預設 0）
    INFERENCE_VRAM_COST_GB = WHISPER_TRANSIENT_VRAM_GB

    def _initialize(self, device_id: int = 0):
        """
        載入 faster-whisper 模型；CUDA 用 float16、CPU 用 int8，權重下載到本地熱資料目錄。

        ``self.device`` 維持 ``'cuda:N'`` / ``'cpu'`` 字串供 BaseModelManager 的 ``_uses_gpu`` /
        L2 BudgetGate 判斷；CTranslate2 另需把它拆成 ``device`` 與 ``device_index`` 兩個參數。
        """
        self.device = self.get_device_str(device_id)
        if self.device.startswith(_CT2_DEVICE_CUDA):
            ct2_device, ct2_index, compute_type = _CT2_DEVICE_CUDA, device_id, WHISPER_CUDA_COMPUTE_TYPE
        else:
            # 無 CUDA：CT2 走 CPU、強制 int8（CPU 不支援 float16 推論）
            ct2_device, ct2_index, compute_type = _CT2_DEVICE_CPU, 0, WHISPER_CPU_COMPUTE_TYPE

        with self._log_load("Whisper"):
            self._model = WhisperModel(
                WHISPER_MODEL_ID,
                device=ct2_device,
                device_index=ct2_index,
                compute_type=compute_type,
                download_root=MODEL_WEIGHTS_DIR,
            )

    def warmup(self) -> None:
        """
        單執行緒餵 1 秒靜音跑一次，提前觸發 CT2 的 CUDA kernel 編譯與原生庫載入（覆寫 base ``warmup``）。

        與 VAD / AudioEnv 的 warmup 同理：把「首次推論才發生的原生初始化」收斂到啟動期單執行緒完成，
        避免執行期多條 worker thread 首呼叫與其他原生 dlopen 撞動態連結器鎖。``vad_filter`` 在此強制關閉，
        確保 decoder 真的在靜音上跑一遍（開啟時 VAD 會把全靜音整段濾掉而 warm 不到 decoder）。
        合約：best-effort、不得拋例外。
        """
        try:
            silence = np.zeros(_WARMUP_SILENCE_SEC * _WARMUP_SAMPLE_RATE, dtype=np.float32)
            segments, _info = self._model.transcribe(
                silence, task="transcribe", beam_size=WHISPER_BEAM_SIZE, vad_filter=False
            )
            # segments 為惰性產生器，需迭代才真正觸發推論
            for _ in segments:
                pass
        except Exception as exc:
            # best-effort：預熱失敗不擋啟動，執行期首呼叫仍會自行初始化
            print(f"[Whisper] warmup 預熱略過：{exc}")

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

    def _transcribe_one(self, audio_path: str) -> dict:
        """
        單檔核心轉錄（**無鎖**，供 :meth:`transcribe` 與 :meth:`transcribe_batch` 共用）。

        刻意不掛 ``@synchronized_inference``：L3 ``_inference_lock`` 為非重入鎖，若批次方法已持鎖
        又呼叫帶鎖的單檔方法會自我死結。鎖序統一由外層兩個公開方法持有。
        """
        segments, info = self._model.transcribe(audio_path, **_TRANSCRIBE_KWARGS)
        # CT2 segments 為惰性產生器；迭代即觸發推論，轉成與舊 HF pipeline 一致的 chunk 格式
        chunks = [
            {"text": seg.text, "timestamp": (seg.start, seg.end)}
            for seg in segments
        ]
        cleaned = self._filter_hallucination({"chunks": chunks})
        # info.language 為偵測語言（舊 HF 路徑未提供，下游 spoken_language 自此生效）；None 後備為空字串
        cleaned["language"] = info.language or _DEFAULT_LANGUAGE
        return cleaned

    @oom_resilient
    @synchronized_inference
    def transcribe(self, audio_path: str) -> dict:
        """輸入音檔路徑，回傳乾淨且無幻覺的逐字稿（含偵測語言）。"""
        try:
            return self._transcribe_one(audio_path)
        except Exception as e:
            # CUDA OOM 往上拋給 @oom_resilient 重試；其餘吞成 Null Object（先印出）
            if is_cuda_oom(e):
                raise
            print(f"[Whisper Error] 轉錄失敗: {e}")
            return {"text": "", "chunks": [], "language": _DEFAULT_LANGUAGE, "error": str(e)}

    @oom_resilient
    @synchronized_inference
    def transcribe_batch(self, audio_paths: list[str]) -> list[dict]:
        """
        對多個音檔以單一借出實例**循序**轉錄，回傳結果列表（與輸入順序一致）。

        faster-whisper 無「多檔一次 forward」介面，故以迴圈逐檔呼叫 :meth:`_transcribe_one`；
        維持 ``BatchCollector`` 的 list→list 等長契約。單檔失敗回 Null Object 不連坐整批；
        但 CUDA OOM 往上拋給 ``@oom_resilient`` 重試整批（與單張一致）。空輸入回 ``[]``。
        """
        if not audio_paths:
            # 早退：空輸入直接回空列表，避免下游零長度迭代誤判
            return []

        results: list[dict] = []
        for path in audio_paths:
            try:
                results.append(self._transcribe_one(path))
            except Exception as e:
                # OOM 往上拋觸發整批重試；其餘單檔回等長 Null Object（下游 zip 不錯位）
                if is_cuda_oom(e):
                    raise
                print(f"[Whisper Batch Error] 轉錄失敗（{path}）: {e}")
                results.append({"text": "", "chunks": [], "language": _DEFAULT_LANGUAGE, "error": str(e)})
        return results
