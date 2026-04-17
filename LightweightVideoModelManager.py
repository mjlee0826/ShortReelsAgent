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
        例如：傳入 8 張連續跳舞的畫面，回傳 "a group of people are dancing to the music"
        """
        if not frames:
            return "No valid frames provided."

        # 將 PIL 圖片陣列轉換為模型可接受的影片張量
        inputs = self.processor(images=frames, return_tensors="pt").to(self.device)
        
        # 模型生成文字描述的 token
        generated_ids = self.model.generate(pixel_values=inputs.pixel_values, max_length=50)
        
        # 將 token 解碼為字串
        caption = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return caption