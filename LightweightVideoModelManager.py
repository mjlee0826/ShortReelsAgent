import torch
from transformers import AutoProcessor, AutoModelForCausalLM
from PIL import Image

class LightweightVideoModelManager:
    """
    單例模式 (Singleton): 確保輕量級影片描述模型只實例化一次。
    使用微軟的 git-base-vatex 模型，專門吃入多張連續影格，輸出連續動作描述。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LightweightVideoModelManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "microsoft/git-base-vatex"
        
        # 載入輕量級 GIT 影片處理器與模型
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_id).to(self.device)

    def generate_caption(self, frames: list[Image.Image]) -> str:
        """
        輸入連續的 PIL 圖片陣列 (代表影片的時間序列)，回傳綜合描述。
        例如：傳入 6 張連續跳舞的畫面，回傳 "a group of people are dancing to the music"
        """
        if not frames:
            return "No valid frames provided."

        try:
            # 1. 這裡輸出的 inputs.pixel_values 形狀是 4D: (6, 3, 224, 224)
            inputs = self.processor(images=frames, return_tensors="pt").to(self.device)
            
            # 2. 【關鍵修復】GIT 影片模型需要 5D 張量 (batch_size, num_frames, channels, height, width)
            # 所以我們在第 0 維度增加一個 batch_size (值為 1)
            # 形狀變成: (1, 6, 3, 224, 224)
            pixel_values = inputs.pixel_values.unsqueeze(0)
            
            # 3. 模型生成文字描述的 token
            generated_ids = self.model.generate(pixel_values=pixel_values, max_length=50)
            
            # 4. 將 token 解碼為字串
            caption = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return caption
            
        except Exception as e:
            # 捕捉可能發生的錯誤，避免讓整個程式崩潰
            print(f"[Model Error] GIT Caption 生成失敗: {str(e)}")
            return "Failed to generate caption."