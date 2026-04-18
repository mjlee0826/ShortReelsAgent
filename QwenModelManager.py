import torch
import gc
import re
import json
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.DefaultPromptManager import DefaultPromptManager

class QwenModelManager:
    """單例模式 (Singleton): 統一的視覺與影片大腦。"""
    _instance = None

    def __new__(cls, prompt_manager: BasePromptManager = None):
        if cls._instance is None:
            cls._instance = super(QwenModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize(prompt_manager)
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self, prompt_manager: BasePromptManager):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "Qwen/Qwen2-VL-7B-Instruct"
        self.prompt_manager = prompt_manager if prompt_manager else DefaultPromptManager()
        
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=torch.bfloat16
        ).to(self.device)
        self.processor = AutoProcessor.from_pretrained(self.model_id)

    def _parse_json_output(self, text: str) -> dict:
        """重構：僅解析 Caption"""
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"caption": text}

    def analyze_media(self, media_input, media_type="image") -> dict:
        prompt_text = self.prompt_manager.get_media_analysis_prompt()

        if media_type == "image":
            content = [
                {"type": "image", "image": media_input, "max_pixels": 1048576},
                {"type": "text", "text": prompt_text}
            ]
        else:
            content = [
                {"type": "video", "video": media_input, "max_pixels": 100352, "fps": 1.0},
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

            generated_ids = self.model.generate(**inputs, max_new_tokens=256)
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]

            return self._parse_json_output(output_text)
            
        except Exception as e:
            print(f"[Qwen VLM Error] 推理失敗: {str(e)}")
            return {"caption": "Failed to analyze."}
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()