import torch
import gc
import re
import json
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.DefaultPromptManager import DefaultPromptManager
from PromptManager.TaskMode import TaskMode
from PromptManager.PromptFactory import PromptFactory

class QwenModelManager:
    """
    單例模式 (Singleton): 統一的視覺大腦 (Qwen2-VL-7B)。
    重構：支援多任務模式切換 (Analysis, ActionIndexing, StyleExtraction)。
    """
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
        self.model_id = "Qwen/Qwen3-VL-8B-Instruct"
        self.prompt_manager = prompt_manager if prompt_manager else DefaultPromptManager()
        
        # 8-bit 量化以節省 VRAM，適合與其它 Processor 同時運行
        quantization_config = BitsAndBytesConfig(load_in_8bit=True)
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_id, 
            quantization_config=quantization_config,
            device_map="auto", # 自動分配層級，避免與 Whisper 衝突
            dtype=torch.float16
        )
        self.processor = AutoProcessor.from_pretrained(self.model_id)

    def analyze_media(self, media_input, media_type="image", mode: TaskMode = TaskMode.GLOBAL_ANALYSIS) -> dict:
        """
        核心推論方法。
        :param media_input: PIL Image 或影片檔案路徑
        :param media_type: "image" 或 "video"
        :param mode: "analysis" (全局), "action" (動作切片), "style" (範本逆向)
        """
        # 根據 mode 動態選取 Prompt
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)

        # 封裝多模態內容
        if media_type == "image":
            content = [
                {"type": "image", "image": media_input},
                {"type": "text", "text": prompt_text}
            ]
        else:
            # 影片處理：fps 設為 1.0 以節省 Token 並維持語意理解
            target_fps = 4.0 if mode == TaskMode.ACTION_INDEX else 1.0
            
            content = [
                {"type": "video", "video": media_input, "max_pixels": 100352, "fps": target_fps},
                {"type": "text", "text": prompt_text}
            ]

        messages = [{"role": "user", "content": content}]

        try:
            # 準備輸入資料
            text_prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            image_inputs, video_inputs = process_vision_info(messages)
            
            inputs = self.processor(
                text=[text_prompt], images=image_inputs, videos=video_inputs,
                padding=True, return_tensors="pt"
            ).to(self.device)

            # 執行生成
            generated_ids = self.model.generate(**inputs, max_new_tokens=512)
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]

            # 解析強化的 JSON (使用 Regex 防摔)
            return self._parse_json_output(output_text)
            
        except Exception as e:
            print(f"[Qwen VLM Error] 推理失敗: {str(e)}")
            return {"error": "Analysis failed", "raw_output": str(e)}
        finally:
            # 定期清理 VRAM 避免記憶體碎片化
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def _parse_json_output(self, text: str) -> dict:
        """
        強化的 JSON 解析器，支援處理 Markdown 區塊與可能的換行符號。
        """
        try:
            # 1. 移除可能的 Markdown 標記
            cleaned_text = text.strip()
            if "```json" in cleaned_text:
                cleaned_text = cleaned_text.split("```json")[-1].split("```")[0].strip()
            elif "```" in cleaned_text:
                cleaned_text = cleaned_text.split("```")[-1].split("```")[0].strip()
            
            # 2. 使用 Regex 再次兜底尋找大括號
            match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            
            # 3. 如果連大括號都沒有，直接將整段文字包裝成 caption 回傳
            return {"caption": cleaned_text.strip()}
        except Exception as e:
            print(f"[JSON Parse Error] 解析失敗，內容: {text}, 錯誤: {e}")
            return {"caption": "Unknown action"}