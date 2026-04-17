import torch
from transformers import BlipProcessor, BlipForConditionalGeneration
from PIL import Image

class BlipModelManager:
    """
    單例模式 (Singleton): 確保 BLIP 視覺模型在多執行緒環境下，
    只會被實例化一次，避免記憶體溢出與重複載入的耗時。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BlipModelManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # 判斷是否支援 GPU 加速
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "Salesforce/blip-image-captioning-base"
        
        # 載入 BLIP 處理器與模型 (無需 candidate labels)
        self.processor = BlipProcessor.from_pretrained(self.model_id)
        self.model = BlipForConditionalGeneration.from_pretrained(self.model_id).to(self.device)

    def generate_caption(self, image: Image.Image) -> str:
        """
        輸入 PIL 圖片，回傳 AI 生成的圖片描述 (Caption)
        範例輸出: "a group of people sitting around a table with food"
        """
        # 將圖片轉換為模型可接受的張量格式
        inputs = self.processor(image, return_tensors="pt").to(self.device)
        
        # 模型生成文字描述的 token
        out = self.model.generate(**inputs)
        
        # 將 token 解碼為人類可讀的字串
        caption = self.processor.decode(out[0], skip_special_tokens=True)
        return caption