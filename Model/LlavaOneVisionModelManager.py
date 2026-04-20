import torch
import gc
import re
import json
import cv2
import numpy as np
from PIL import Image
# Llava-OneVision 於最新版 transformers 支援
from transformers import LlavaOnevisionForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.DefaultPromptManager import DefaultPromptManager
from PromptManager.TaskMode import TaskMode
from PromptManager.PromptFactory import PromptFactory

class LlavaOneVisionModelManager:
    """
    單例模式 (Singleton): 統一的視覺大腦 (LLaVA-OneVision-7B)。
    LLaVA-OneVision 擅長於 AnyRes 視覺理解與時序動態捕捉。
    """
    _instance = None

    def __new__(cls, prompt_manager: BasePromptManager = None):
        if cls._instance is None:
            cls._instance = super(LlavaOneVisionModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize(prompt_manager)
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self, prompt_manager: BasePromptManager):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # 推薦使用 7B-ov 版本以兼顧 VRAM 與智商
        self.model_id = "llava-hf/llava-onevision-qwen2-7b-ov-hf"
        self.prompt_manager = prompt_manager if prompt_manager else DefaultPromptManager()
        
        # 8-bit 量化節省顯存
        quantization_config = BitsAndBytesConfig(load_in_8bit=True)
        
        print(f"[Model] 正在初始化 LLaVA-OneVision: {self.model_id}")
        self.model = LlavaOnevisionForConditionalGeneration.from_pretrained(
            self.model_id, 
            quantization_config=quantization_config,
            device_map="auto",
            torch_dtype=torch.float16
        )
        self.processor = AutoProcessor.from_pretrained(self.model_id)

    def _extract_frames(self, video_path: str, max_frames: int = 16) -> list:
        """
        從影片中均勻抽取固定數量的影格，供 LLaVA 推論。
        """
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return []
            
        indices = np.linspace(0, total_frames - 1, max_frames, dtype=int)
        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(Image.fromarray(frame_rgb))
        cap.release()
        return frames

    def analyze_media(self, media_input, media_type="image", mode: TaskMode = TaskMode.GLOBAL_ANALYSIS) -> dict:
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)
        
        # 依照 LLaVA 的 Prompt 格式構建
        # 影片格式需包含 <video> 標記
        prompt = f"<|im_start|>user\n"
        if media_type == "video":
            prompt += "<video>\n"
        else:
            prompt += "<image>\n"
        prompt += f"{prompt_text}<|im_end|>\n<|im_start|>assistant\n"

        try:
            if media_type == "video":
                # LLaVA-OneVision 處理影片本質是處理影格列表
                pixel_values_videos = self._extract_frames(media_input, max_frames=16)
                inputs = self.processor(text=prompt, videos=pixel_values_videos, return_tensors="pt").to(self.device)
            else:
                inputs = self.processor(text=prompt, images=media_input, return_tensors="pt").to(self.device)

            # 設定半精度推論
            inputs = {k: v.to(torch.float16) if v.is_floating_point() else v for k, v in inputs.items()}

            generated_ids = self.model.generate(**inputs, max_new_tokens=512, do_sample=False)
            output_text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            # 移除 Prompt 部分，只保留 Assistant 的回答
            clean_answer = output_text.split("assistant\n")[-1] if "assistant\n" in output_text else output_text

            return self._parse_json_output(clean_answer)
            
        except Exception as e:
            print(f"[LLaVA Error] 推理失敗: {str(e)}")
            return {"error": "Analysis failed", "raw_output": str(e)}
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def _parse_json_output(self, text: str) -> dict:
        """強健的 JSON 解析器"""
        try:
            cleaned_text = text.strip()
            # 處理 Markdown 標籤
            if "```json" in cleaned_text:
                cleaned_text = cleaned_text.split("```json")[-1].split("```")[0].strip()
            elif "```" in cleaned_text:
                cleaned_text = cleaned_text.split("```")[-1].split("```")[0].strip()
            
            match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            
            return {"caption": cleaned_text.strip()}
        except Exception as e:
            print(f"[JSON Parse Error] 解析失敗: {e}")
            return {"caption": "Unknown action"}