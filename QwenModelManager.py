import torch
import gc  # 新增：用於強制回收記憶體
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
            cls._instance = super(QwenModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "Qwen/Qwen2-VL-7B-Instruct"
        
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=torch.bfloat16
        ).to(self.device)
        
        self.processor = AutoProcessor.from_pretrained(self.model_id)

    def _parse_json_output(self, text: str) -> dict:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"caption": text, "is_blurry": False}

    def analyze_media(self, media_input, media_type="image") -> dict:
        prompt_text = (
            "請詳細描述這份素材(圖片或影片)的主要內容與動作。"
            "同時，請以專業攝影師的角度判斷，這個畫面是否有嚴重的失焦、模糊或是劇烈手震？"
            "請以嚴格的 JSON 格式回傳，必須包含兩個 key: "
            "'caption' (字串，繁體中文描述), 'is_blurry' (布林值，true代表嚴重模糊/手震廢片，false代表畫質可接受)。"
        )

        if media_type == "image":
            content = [
                {
                    "type": "image", 
                    "image": media_input,
                    # 【核心修復 1】限制單張照片的最大像素量 (約 100 萬畫素，相當於 1000x1000)
                    # 這樣既能保留足夠的語意細節，又絕對不會讓 24GB 的 VRAM 爆炸
                    "max_pixels": 1048576 
                },
                {"type": "text", "text": prompt_text}
            ]
        else:
            content = [
                {
                    "type": "video",
                    "video": media_input, 
                    "max_pixels": 100352, # 影片因為有多幀，單幀像素限制得比照片更小
                    "fps": 1.0,           
                },
                {"type": "text", "text": prompt_text}
            ]

        messages = [{"role": "user", "content": content}]

        try:
            text_prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            image_inputs, video_inputs = process_vision_info(messages)
            
            inputs = self.processor(
                text=[text_prompt],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt"
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
            return {"caption": "Failed to analyze.", "is_blurry": False}
        finally:
            # 【核心修復 2】手動垃圾回收機制
            # 每次推論結束後，強制釋放沒有在使用的 GPU 記憶體區塊，避免碎片化導致後續檔案 OOM
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()