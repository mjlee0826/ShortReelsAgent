import torch
import gc
import re
import json
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.DefaultPromptManager import DefaultPromptManager

class QwenModelManager:
    """單例模式 (Singleton): 統一的視覺與影片大腦 (大腦 B)。專職輸出語意與攝影評論。"""
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
        
        quantization_config = BitsAndBytesConfig(load_in_8bit=True)
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_id, 
            quantization_config=quantization_config,
            device_map="auto" # 讓 accelerate 自動分配
        )
        self.processor = AutoProcessor.from_pretrained(self.model_id)

    def _parse_json_output(self, text: str) -> dict:
        try:
            # 使用正則表達式尋找最外層的 { }
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                json_str = match.group(0)
                return json.loads(json_str)
            else:
                raise ValueError("找不到 JSON 格式的內容")
        except Exception as e:
            print(f"[JSON Parse Error] 無法解析 Qwen 輸出: {e}")
            return {"caption": text, "cinematic_critique": "JSON 解析失敗"}

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
            return {"caption": "Failed to analyze.", "cinematic_critique": ""}
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()