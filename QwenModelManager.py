import torch
import re
import json
from PIL import Image
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info

class QwenModelManager:
    """
    單例模式 (Singleton): 統一的視覺與影片大腦。
    載入 Qwen2-VL-7B-Instruct，具備強大的圖像與影片理解能力，
    並直接負責品質過濾 (模糊/手震判斷)。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            # 1. 先分配記憶體空間給實例
            cls._instance = super(QwenModelManager, cls).__new__(cls)
            try:
                # 2. 嘗試進行初始化
                cls._instance._initialize()
            except Exception as e:
                # 3. 【防呆重構】如果初始化過程發生錯誤 (例如缺少套件)，
                # 必須把 _instance 重置為 None，避免留下「沒有 processor 屬性」的半殘物件。
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "Qwen/Qwen2-VL-7B-Instruct"
        
        # 【重構】移除 device_map="auto" 以避免強制依賴 accelerate 套件，
        # 改為載入至記憶體後，再手動 .to(self.device) 推入 GPU。
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=torch.bfloat16
        ).to(self.device)
        
        self.processor = AutoProcessor.from_pretrained(self.model_id)

    def _parse_json_output(self, text: str) -> dict:
        """
        內部方法：從 LLM 的回覆中安全地萃取出 JSON 結構。
        """
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        # Fallback 防呆機制
        return {"caption": text, "is_blurry": False}

    def analyze_media(self, media_input, media_type="image") -> dict:
        """
        統一的媒體分析介面。
        media_input: 若為照片，傳入 PIL Image 物件；若為影片，傳入檔案路徑字串。
        media_type: "image" 或 "video"
        """
        prompt_text = (
            "請詳細描述這份素材(圖片或影片)的主要內容與動作。"
            "同時，請以專業攝影師的角度判斷，這個畫面是否有嚴重的失焦、模糊或是劇烈手震？"
            "請以嚴格的 JSON 格式回傳，必須包含兩個 key: "
            "'caption' (字串，繁體中文描述), 'is_blurry' (布林值，true代表嚴重模糊/手震廢片，false代表畫質可接受)。"
        )

        if media_type == "image":
            content = [
                {"type": "image", "image": media_input},
                {"type": "text", "text": prompt_text}
            ]
        else:
            content = [
                {
                    "type": "video",
                    "video": media_input, 
                    "max_pixels": 100352, # 限制解析度以避免 VRAM 爆掉
                    "fps": 1.0,           # 每秒抽 1 幀
                },
                {"type": "text", "text": prompt_text}
            ]

        messages = [{"role": "user", "content": content}]

        try:
            # 使用官方推薦的 qwen_vl_utils 來解析格式
            text_prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            image_inputs, video_inputs = process_vision_info(messages)
            
            inputs = self.processor(
                text=[text_prompt],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt"
            ).to(self.device)

            # 產生推理結果
            generated_ids = self.model.generate(**inputs, max_new_tokens=256)
            # 濾除 prompt，只保留回覆
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self.processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]

            return self._parse_json_output(output_text)
            
        except Exception as e:
            print(f"[Qwen VLM Error] 推理失敗: {str(e)}")
            return {"caption": "Failed to analyze.", "is_blurry": False}