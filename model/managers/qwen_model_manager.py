"""
QwenModelManager：本地視覺大腦 (Qwen3-VL)，提供圖片與影片的 caption / mood / scene_tags 等推論。

量化策略（``QWEN_QUANT_MODE``，三選一）
--------------------------------------
- **bf16 主路徑（預設）**：不量化，bf16 權重。單次 forward 最快——bnb 量化在 transformers 推理時
  每個 matmul 都即時反量化、沒有真正的低位元 kernel（真 4-bit kernel 僅 vLLM 有），慢 2~4 倍；
  本專案 Qwen 為主瓶頸且 VRAM 充裕（4B bf16 僅 ~8.5GB），故預設 bf16 換取速度。
- **nf4 後備路徑**：bitsandbytes 4-bit NF4，最省 VRAM（VRAM 吃緊時用）。
- **int8 後備路徑**：bitsandbytes 8-bit，供品質回歸 A/B。
- **Flash Attention 2** 啟用 + sdpa fallback（Strategy + try/except 隔離）。

設計模式
--------
- **Strategy**：依 ``QWEN_QUANT_MODE`` 在 ``_build_base_load_kwargs`` 以分派表切 bf16 / nf4 / int8 載入路徑。
- **Chain of Responsibility (簡化版)**：Attention 實作優先序 FA2 → sdpa，遇錯自動 fallback。
"""
import torch
import gc
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.task_mode import TaskMode
from prompt_manager.prompt_factory import PromptFactory
from model.infra.base_model_manager import (
    BaseModelManager,
    synchronized_inference,
    oom_resilient,
    is_cuda_oom,
)
from config.media_processor_config import QWEN_TRANSIENT_VRAM_GB, QWEN_INFERENCE_PRIORITY
from config.model_config import (
    QWEN_MODEL_ID,
    QWEN_PROCESSOR_ID,
    QWEN_QUANT_MODE,
    QWEN_QUANT_MODE_NF4,
    QWEN_QUANT_MODE_INT8,
    QWEN_QUANT_MODE_BF16,
    QWEN_USE_FLASH_ATTN,
    QWEN_MAX_NEW_TOKENS,
    QWEN_MAX_PIXELS,
    QWEN_FPS_TIMECODED,
    QWEN_FPS_DEFAULT,
)


# Attention 實作優先序：FA2 為主，環境不允許時 fallback 到 sdpa（PyTorch 內建）
_ATTN_PRIMARY  = "flash_attention_2"
_ATTN_FALLBACK = "sdpa"


class QwenModelManager(BaseModelManager):
    """統一的本地視覺大腦 (Qwen3-VL)，bitsandbytes 4-bit 為主路徑、8-bit 為品質回歸路徑。"""

    # 單次 generate 暫態峰值 → BudgetGate 記帳;高優先 → 反餓死(Qwen 是主瓶頸)
    INFERENCE_VRAM_COST_GB = QWEN_TRANSIENT_VRAM_GB
    INFERENCE_PRIORITY = QWEN_INFERENCE_PRIORITY

    def _initialize(self, device_id: int = 0):
        """
        依 ``QWEN_QUANT_MODE`` 選擇模型載入路徑（bf16 / nf4 / int8），並嘗試啟用 Flash Attention 2。

        Flash Attn 安裝失敗或硬體不支援時，自動 fallback 到 sdpa 而不中斷流程。
        """
        self.device = self.get_device_str(device_id)
        self.prompt_manager = DefaultPromptManager()

        # 載入是最耗時的一次性操作（含 bnb 量化），記錄起訖與耗時供觀察
        with self._log_load("Qwen"):
            # 依旗標決定走哪條載入策略（Strategy Pattern）
            self.model = self._load_model_with_attention_fallback()
            # Processor 從官方 base model 載入（tokenizer + 影像/影片前處理）
            self.processor = AutoProcessor.from_pretrained(QWEN_PROCESSOR_ID)

        # 印出實際生效的 attention 實作與量化模式：方便確認 FA2 是否真的啟用、
        # 以及落在 bf16（預設）/ nf4 / int8 哪條載入路徑
        attn_impl = getattr(self.model.config, "_attn_implementation", "unknown")
        print(f"[Qwen] attn_implementation={attn_impl}, 量化={QWEN_QUANT_MODE}")

    def _load_model_with_attention_fallback(self) -> Qwen3VLForConditionalGeneration:
        """
        嘗試以 Flash Attention 2 載入，僅在 FA2「不可用」時 fallback 到 sdpa。

        fallback 條件刻意只限於 ``ImportError``（flash-attn 未安裝）與
        ``ValueError``（模型 / 環境不支援該 attn_implementation）。
        **CUDA OOM 等資源錯誤一律往上拋**，不被偽裝成「FA2 失敗」，
        以免在共用 GPU 環境誤導除錯方向（OOM 與 attention 實作無關）。
        """
        load_kwargs = self._build_base_load_kwargs()

        # 第一順位：使用者明示啟用 FA2 才嘗試，省去無謂 import 開銷
        if QWEN_USE_FLASH_ATTN:
            try:
                return Qwen3VLForConditionalGeneration.from_pretrained(
                    QWEN_MODEL_ID,
                    attn_implementation=_ATTN_PRIMARY,
                    **load_kwargs,
                )
            except (ImportError, ValueError) as exc:
                # ImportError：flash-attn 未安裝
                # ValueError：模型 / transformers 版本不支援該 attn_implementation
                # 這兩類才是「FA2 不可用」，OOM 等 RuntimeError 不在此列、會自然往上拋
                print(
                    f"[Qwen FA2 Warning] Flash Attention 2 不可用，"
                    f"fallback 至 {_ATTN_FALLBACK}：{exc}"
                )

        # 後備順位：sdpa 為 PyTorch 內建，幾乎所有環境皆可用
        return Qwen3VLForConditionalGeneration.from_pretrained(
            QWEN_MODEL_ID,
            attn_implementation=_ATTN_FALLBACK,
            **load_kwargs,
        )

    def _build_base_load_kwargs(self) -> dict:
        """
        建構 ``from_pretrained`` 的共用參數，並依 ``QWEN_QUANT_MODE`` 分派量化策略 (Strategy Pattern)。

        - **device_map 鎖定 self.device**：每個 Manager 實例對應一張指定 GPU
          （由 ``device_id`` 決定），避免 ``device_map="auto"`` 在共用 GPU 環境
          抓到別人佔用的卡，也讓多 GPU Pool 的「一卡一實例」成立。
        - **量化策略**：預設 bf16（不量化、最快）；nf4 / int8 走 bitsandbytes 即時量化官方 base model
          （VRAM 吃緊或品質回歸時用）。未知 mode 退回 bf16（最快、最穩，與 capacity profile 退回方向一致）。
        """
        # device_map={"": self.device} 將整個模型固定在指定 GPU，
        # 不做跨卡切分，符合 BaseModelManager 以 device_id 區分實例的設計
        load_kwargs: dict = {"device_map": {"": self.device}}
        # 量化策略分派表：mode → 套用對應 load kwargs 的方法（Strategy Pattern，免散落 if/elif）
        quant_strategies = {
            QWEN_QUANT_MODE_BF16: self._apply_bf16_kwargs,
            QWEN_QUANT_MODE_NF4: self._apply_nf4_kwargs,
            QWEN_QUANT_MODE_INT8: self._apply_int8_kwargs,
        }
        # 未知 mode 退回 bf16（最快、最穩）
        apply_strategy = quant_strategies.get(QWEN_QUANT_MODE, self._apply_bf16_kwargs)
        apply_strategy(load_kwargs)
        return load_kwargs

    @staticmethod
    def _apply_bf16_kwargs(load_kwargs: dict) -> None:
        """bf16 策略（預設）：不量化、bf16 權重。VRAM 最大但單次 forward 最快（無即時反量化開銷）。"""
        load_kwargs["torch_dtype"] = torch.bfloat16

    @staticmethod
    def _apply_nf4_kwargs(load_kwargs: dict) -> None:
        """
        nf4 策略：bitsandbytes 4-bit NF4，最省 VRAM。

        權重在 runtime 保持 4-bit（不解壓），4B 模型約 2.5-3GB；compute dtype 用 bf16、
        double quant 再壓 scale 記憶體。代價是每個 matmul 即時反量化，單次 forward 慢於 bf16。
        """
        load_kwargs["torch_dtype"] = torch.bfloat16
        load_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    @staticmethod
    def _apply_int8_kwargs(load_kwargs: dict) -> None:
        """int8 策略：bitsandbytes 8-bit，VRAM / 速度介於中間，供品質回歸 A/B。"""
        load_kwargs["torch_dtype"] = torch.float16
        load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)

    def set_prompt_manager(self, prompt_manager: BasePromptManager):
        """替換 Prompt Manager（Strategy Pattern）。"""
        self.prompt_manager = prompt_manager

    @oom_resilient
    @synchronized_inference
    def analyze_media(self, media_input, media_type: str = "image", mode: TaskMode = TaskMode.GLOBAL_ANALYSIS) -> dict:
        """輸入圖片或影片路徑，回傳模型推論的 JSON 結果。"""
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)

        if media_type == "image":
            content = [
                {"type": "image", "image": media_input},
                {"type": "text", "text": prompt_text}
            ]
        else:
            target_fps = QWEN_FPS_TIMECODED if mode == TaskMode.TIMECODED_ACTION_INDEX else QWEN_FPS_DEFAULT
            content = [
                {"type": "video", "video": media_input, "max_pixels": QWEN_MAX_PIXELS, "fps": target_fps},
                {"type": "text", "text": prompt_text}
            ]

        messages = [{"role": "user", "content": content}]

        try:
            # Qwen3-VL 以「文字時間戳」對齊影片，processor 必須自行讀檔取得 video_metadata
            # （原始 fps / 總幀數）才能正確抽幀；此版 qwen-vl-utils 預抽幀後不附 metadata，
            # 會害 processor fallback 成 fps=24、影片 token 暴增而 OOM。
            # 改走官方推薦的 apply_chat_template(tokenize=True)：由 processor 一手讀檔、
            # 取 metadata、依 content 指定的 fps 抽幀；圖片與影片共用同一路徑，
            # 亦免去舊路徑「圖片 fps=[] 型別錯誤」的問題。
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            ).to(self.device)
            # 部分 transformers 版本會多出 generate 不需要的 token_type_ids，移除以免報錯
            inputs.pop("token_type_ids", None)

            generated_ids = self.model.generate(**inputs, max_new_tokens=QWEN_MAX_NEW_TOKENS)
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]

            return self._parse_json_output(output_text)

        except Exception as e:
            # CUDA OOM 往上拋給 @oom_resilient 重試（耗盡才標 asset error）；其餘錯誤維持 null object
            if is_cuda_oom(e):
                raise
            print(f"[Qwen VLM Error] 推理失敗: {str(e)}")
            return {"error": "Analysis failed", "raw_output": str(e)}
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
