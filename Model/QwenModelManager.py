import torch
import gc
import re
import json
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.DefaultPromptManager import DefaultPromptManager
from PromptManager.TaskMode import TaskMode
from PromptManager.PromptFactory import PromptFactory
from Model.BaseModelManager import BaseModelManager

class QwenModelManager(BaseModelManager):
    """統一的本地視覺大腦 (Qwen3-VL)。"""

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # 【核心修正】修正為官方正確的最新穩定版 Model ID
        self.model_id = "Qwen/Qwen3-VL-8B-Instruct"
        self.prompt_manager = DefaultPromptManager()
        
        quantization_config = BitsAndBytesConfig(load_in_8bit=True)
        
        # 【核心修正】使用新一代的 Model Class 來載入權重
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            self.model_id, 
            quantization_config=quantization_config,
            device_map="auto",
            torch_dtype=torch.float16
        )
        self.processor = AutoProcessor.from_pretrained(self.model_id)

    def set_prompt_manager(self, prompt_manager: BasePromptManager):
        self.prompt_manager = prompt_manager

    def analyze_media(self, media_input, media_type="image", mode: TaskMode = TaskMode.GLOBAL_ANALYSIS) -> dict:
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)

        if media_type == "image":
            content = [
                {"type": "image", "image": media_input},
                {"type": "text", "text": prompt_text}
            ]
        else:
            target_fps = 2.0 if mode == TaskMode.TIMECODED_ACTION_INDEX else 1.0
            
            content = [
                {"type": "video", "video": media_input, "max_pixels": 100352, "fps": target_fps},
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

            generated_ids = self.model.generate(**inputs, max_new_tokens=512)
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

    def _parse_json_output(self, text: str) -> dict:
        try:
            cleaned_text = text.strip()
            if "```json" in cleaned_text:
                cleaned_text = cleaned_text.split("```json")[-1].split("```")[0].strip()
            elif "```" in cleaned_text:
                cleaned_text = cleaned_text.split("```")[-1].split("```")[0].strip()
            
            match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            
            return {"caption": cleaned_text.strip()}
        except Exception as e:
            print(f"[JSON Parse Error] 解析失敗，錯誤: {e}")
            return {"caption": "Unknown action"}