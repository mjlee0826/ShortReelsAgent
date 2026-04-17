import torch
import numpy as np
from transformers import VideoLlavaProcessor, VideoLlavaForConditionalGeneration
from PIL import Image

class MainstreamVideoManager:
    """
    單例模式 (Singleton): 載入重量級的 Video-LLaVA 模型。
    注意：此模型需佔用大量顯示卡記憶體 (VRAM)，建議在具備高階 GPU 的環境下使用。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MainstreamVideoManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "llava-hf/video-llava-7b-hf"
        
        self.processor = VideoLlavaProcessor.from_pretrained(self.model_id)
        # 使用 float16 來降低一半的記憶體消耗
        self.model = VideoLlavaForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=torch.float16
        ).to(self.device)

    def generate_caption(self, frames: list[Image.Image], prompt: str = "USER: <video>\nPlease describe the main action and atmosphere in this video.\nASSISTANT:") -> str:
        """
        輸入連續影格與 Prompt，交由 LLM 進行多模態推理。
        """
        if not frames:
            return "No valid frames provided."

        # 將 PIL 影像轉為 numpy 陣列的影片格式 (需符合 Video-LLaVA 預期輸入格式)
        # 轉換形狀: (num_frames, height, width, channels)
        video_tensor = np.stack([np.array(img) for img in frames])

        inputs = self.processor(text=prompt, videos=video_tensor, return_tensors="pt").to(self.device)
        
        out = self.model.generate(**inputs, max_new_tokens=100)
        
        # 解碼回傳結果
        caption = self.processor.batch_decode(out, skip_special_tokens=True)[0]
        # 過濾掉 Prompt 本身，只保留回答
        response = caption.split("ASSISTANT:")[-1].strip()
        return response