"""
QwenModelManager：本地視覺大腦 (Qwen3-VL)，提供圖片與影片的 caption / mood / scene_tags 等推論。

量化策略
--------
- 4-bit 主路徑：**bitsandbytes NF4**（``QWEN_USE_4BIT=true``，預設）。原規劃的
  compressed-tensors AWQ（cyankiwi）在 transformers 推理時會整包解壓成 bf16、
  runtime 不省 VRAM（真正的 4-bit kernel 僅 vLLM 有），故改用 bnb 才能真正砍半。
- 8-bit 後備路徑：``QWEN_USE_4BIT=false``，供品質回歸 A/B。
- **Flash Attention 2** 啟用 + sdpa fallback（Strategy + try/except 隔離）。

設計模式
--------
- **Strategy**：依 ``QWEN_USE_4BIT`` 在 ``_build_base_load_kwargs`` 切 4-bit / 8-bit 兩條載入路徑。
- **Chain of Responsibility (簡化版)**：Attention 實作優先序 FA2 → sdpa，遇錯自動 fallback。
"""
import torch
import gc
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.task_mode import TaskMode
from prompt_manager.prompt_factory import PromptFactory
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    QWEN_MODEL_ID,
    QWEN_PROCESSOR_ID,
    QWEN_USE_4BIT,
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

    def _initialize(self, device_id: int = 0):
        """
        依 ``QWEN_USE_4BIT`` 旗標選擇模型載入路徑，並嘗試啟用 Flash Attention 2。

        Flash Attn 安裝失敗或硬體不支援時，自動 fallback 到 sdpa 而不中斷流程。
        """
        self.device = self.get_device_str(device_id)
        self.prompt_manager = DefaultPromptManager()

        # 依旗標決定走哪條載入策略（Strategy Pattern）
        self.model = self._load_model_with_attention_fallback()
        # Processor 從官方 base model 載入（tokenizer + 影像/影片前處理）
        self.processor = AutoProcessor.from_pretrained(QWEN_PROCESSOR_ID)

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
        建構 ``from_pretrained`` 的共用參數。

        - **device_map 鎖定 self.device**：每個 Manager 實例對應一張指定 GPU
          （由 ``device_id`` 決定），避免 ``device_map="auto"`` 在共用 GPU 環境
          抓到別人佔用的卡，也讓 Week 3b 多 GPU Pool 的「一卡一實例」成立。
        - 量化一律由 **bitsandbytes** 即時量化官方 base model：4-bit(NF4) 為主路徑、
          8-bit 為品質回歸後備。改採 bnb 是因 compressed-tensors AWQ 在 transformers
          推理時會整包解壓成 bf16、runtime 不省 VRAM（真正的 4-bit kernel 僅 vLLM 有）。
        """
        # device_map={"": self.device} 將整個模型固定在指定 GPU，
        # 不做跨卡切分，符合 BaseModelManager 以 device_id 區分實例的設計
        load_kwargs: dict = {"device_map": {"": self.device}}
        if QWEN_USE_4BIT:
            # 4-bit 主路徑：bitsandbytes NF4。權重在 runtime 保持 4-bit（不解壓），
            # 8B 模型約 5-6GB；compute dtype 用 bf16、double quant 再壓 scale 記憶體
            load_kwargs["torch_dtype"] = torch.bfloat16
            load_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
        else:
            # 8-bit 後備路徑：bitsandbytes 8-bit，供品質回歸 A/B
            load_kwargs["torch_dtype"] = torch.float16
            load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
        return load_kwargs

    def set_prompt_manager(self, prompt_manager: BasePromptManager):
        """替換 Prompt Manager（Strategy Pattern）。"""
        self.prompt_manager = prompt_manager

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
            print(f"[Qwen VLM Error] 推理失敗: {str(e)}")
            return {"error": "Analysis failed", "raw_output": str(e)}
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
