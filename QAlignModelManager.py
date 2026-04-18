import torch
from PIL import Image
from transformers import AutoModelForCausalLM

class QAlignModelManager:
    """
    單例模式 (Singleton): 美學與畫質評分大腦 (大腦 A)。
    載入 Q-Align 模型，專門負責視覺素材的「硬指標打分」(技術畫質與美感)。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(QAlignModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "q-future/one-align"

        # ✅ 官方推薦：直接用 AutoModel + trust_remote_code
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16,
            device_map="auto"
        )

        self.model.eval()

        # 保留你的 mapping（雖然新 API 不太需要）
        self.score_mapping = {
            "excellent": 100.0,
            "good": 80.0,
            "fair": 60.0,
            "poor": 40.0,
            "bad": 20.0
        }

    def _get_score_from_level(self, level_str: str) -> float:
        level = level_str.strip().lower()
        return self.score_mapping.get(level, 60.0)

    def score_media(self, pil_image: Image.Image) -> dict:
        """
        對圖片進行技術與美學雙重評分。
        """
        try:
            images = [pil_image]

            # ✅ 官方 API：直接 score
            tech_score = self.model.score(
                images,
                task_="quality",
                input_="image"
            )[0]

            aes_score = self.model.score(
                images,
                task_="aesthetics",
                input_="image"
            )[0]

            return {
                "technical_score": float(tech_score),
                "aesthetic_score": float(aes_score)
            }

        except Exception as e:
            print(f"[Q-Align Error] 評分失敗: {e}")
            return {"technical_score": 60.0, "aesthetic_score": 60.0}