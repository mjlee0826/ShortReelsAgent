"""
QwenModelManager：本地視覺大腦 (Qwen3-VL)，提供圖片與影片的 caption / mood / scene_tags 等推論。

Week 1 變動
-----------
- 新增 4-bit **AWQ** 載入路徑（主路徑，預設啟用）：模型 id ``Qwen3-VL-8B-Instruct-AWQ``。
- 新增 **Flash Attention 2** 啟用 + sdpa fallback（Strategy + try/except 隔離）。
- 舊版 8-bit 量化路徑透過 env var ``QWEN_USE_AWQ=false`` 保留，供品質回歸 A/B。

設計模式
--------
- **Strategy**：``_LoadStrategy`` 內部介面，依 ``QWEN_USE_AWQ`` 切兩條載入路徑。
- **Chain of Responsibility (簡化版)**：Attention 實作優先序 FA2 → sdpa，遇錯自動 fallback。
"""
import torch
import gc
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.task_mode import TaskMode
from prompt_manager.prompt_factory import PromptFactory
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    QWEN_MODEL_ID,
    QWEN_PROCESSOR_ID,
    QWEN_AWQ_MODEL_ID,
    QWEN_LEGACY_MODEL_ID,
    QWEN_USE_AWQ,
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
    """統一的本地視覺大腦 (Qwen3-VL)，AWQ 為主路徑、legacy 8-bit 為回歸路徑。"""

    def _initialize(self, device_id: int = 0):
        """
        依 ``QWEN_USE_AWQ`` 旗標選擇模型載入路徑，並嘗試啟用 Flash Attention 2。

        Flash Attn 安裝失敗或硬體不支援時，自動 fallback 到 sdpa 而不中斷流程。
        """
        self.device = self.get_device_str(device_id)
        self.prompt_manager = DefaultPromptManager()

        # 依旗標決定走哪條載入策略（Strategy Pattern）
        self.model = self._load_model_with_attention_fallback()
        # Processor 永遠從官方 base model 載入，避免社群 AWQ repo 缺 processor 設定
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
        - AWQ 模型自帶 4-bit 量化權重，**不可** 再傳 ``BitsAndBytesConfig``；
          AWQ 內部不同層使用不同精度（I32 / BF16），用 ``dtype="auto"`` 讓 loader
          依模型自帶的 quantization_config 自動決定。
        - Legacy 路徑沿用 8-bit BitsAndBytes 量化以維持品質回歸路徑與原行為一致。
        """
        # device_map={"": self.device} 將整個模型固定在指定 GPU，
        # 不做跨卡切分，符合 BaseModelManager 以 device_id 區分實例的設計
        load_kwargs: dict = {"device_map": {"": self.device}}
        if QWEN_USE_AWQ:
            # AWQ 路徑：dtype="auto" 對應 cyankiwi 模型卡建議寫法
            load_kwargs["dtype"] = "auto"
        else:
            # Legacy 路徑：補上 8-bit 量化設定，行為與 Week 1 之前一致
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
            text_prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            # 必須用 return_video_kwargs 取回影片 metadata（fps / 總幀數）並轉交 processor，
            # 否則新版 transformers 因缺 metadata 會把影片採樣 fallback 成 fps=24，
            # 抽幀數暴增 → video tokens 暴增 → Qwen VRAM 爆掉（單支影片可膨脹逾 20GB）。
            # 圖片情境下 video_kwargs 為空 dict，展開後不影響 processor。
            image_inputs, video_inputs, video_kwargs = process_vision_info(
                messages, return_video_kwargs=True
            )

            inputs = self.processor(
                text=[text_prompt], images=image_inputs, videos=video_inputs,
                padding=True, return_tensors="pt",
                **video_kwargs,
            ).to(self.device)

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
