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
    QWEN_MAX_NEW_TOKENS,
    QWEN_MAX_PIXELS,
    QWEN_FPS_TIMECODED,
    QWEN_FPS_DEFAULT,
)


class QwenModelManager(BaseModelManager):
    """統一的本地視覺大腦 (Qwen3-VL)。"""

    def _initialize(self, device_id: int = 0):
        """
        以 8-bit 量化載入 Qwen3-VL。
        device_map="auto" 讓 transformers 自動跨 GPU 分配權重；
        若需強制鎖定特定 GPU，可改為 device_map={"": f"cuda:{device_id}"}。
        """
        self.device = self.get_device_str(device_id)
        self.prompt_manager = DefaultPromptManager()

        quantization_config = BitsAndBytesConfig(load_in_8bit=True)

        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            QWEN_MODEL_ID,
            quantization_config=quantization_config,
            device_map="auto",
            torch_dtype=torch.float16
        )
        self.processor = AutoProcessor.from_pretrained(QWEN_MODEL_ID)

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
            image_inputs, video_inputs = process_vision_info(messages)

            inputs = self.processor(
                text=[text_prompt], images=image_inputs, videos=video_inputs,
                padding=True, return_tensors="pt"
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
