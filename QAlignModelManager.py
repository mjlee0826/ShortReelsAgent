import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoProcessor

import builtins # 【新增】用於修改 Python 內建全域變數

# ==============================================================================
# 【全局依賴衝突修復：Monkey Patch (猴子補丁)】
# 必須放在所有 import 的最前面 (作為系統的 Entry Point)！
# 解決 Q-Align (依賴舊版) 與 Qwen2-VL (依賴新版) 在 transformers 套件上的連鎖衝突。
# ==============================================================================
import transformers.pytorch_utils

# 修復 1: 解決舊版函數被移除的問題 (find_pruneable_heads_and_indices)
if not hasattr(transformers.pytorch_utils, 'find_pruneable_heads_and_indices'):
    # 偽造一個空函數，回傳空集合與空陣列以滿足 Q-Align 遠端程式碼的預期
    transformers.pytorch_utils.find_pruneable_heads_and_indices = lambda *args, **kwargs: (set(), [])

# 修復 2: 解決 Q-Align 遠端程式碼 (modeling_llama2.py) 缺少 Cache 類別的 NameError
try:
    from transformers.cache_utils import Cache
    # 【關鍵駭客技巧】將 Cache 強制注入到 Python 內建全域變數中。
    # 這樣即使 Q-Align 的遠端腳本忘記 import，Python 直譯器也能在全域空間找到它，避免報錯。
    builtins.Cache = Cache
except ImportError:
    pass

class QAlignModelManager:
    """
    單例模式 (Singleton): 美學與畫質評分大腦 (大腦 A)。
    載入 Q-Align 模型，專門負責視覺素材的「硬指標打分」(技術畫質與美感)。
    取代傳統的 OpenCV 模糊偵測，提供對齊人類審美的高階評估。
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
        # 使用 Q-Align 官方推薦的模型權重
        self.model_id = "q-future/one-align"
        
        # 載入模型 (Q-Align 基於 mPLUG-Owl2，通常需要 trust_remote_code=True)
        self.processor = AutoProcessor.from_pretrained(self.model_id, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id, 
            torch_dtype=torch.bfloat16, 
            trust_remote_code=True
        ).to(self.device)
        self.model.eval()

        # Q-Align 回覆等級與分數的映射表
        self.score_mapping = {
            "excellent": 100.0,
            "good": 80.0,
            "fair": 60.0,
            "poor": 40.0,
            "bad": 20.0
        }

    def _get_score_from_level(self, level_str: str) -> float:
        """將模型的文字評價轉換為數值分數"""
        level = level_str.strip().lower()
        return self.score_mapping.get(level, 60.0) # 預設給予及格分

    def score_media(self, pil_image: Image.Image) -> dict:
        """
        對圖片進行技術與美學雙重評分。
        """
        try:
            # 1. 詢問技術畫質 (清晰度、噪點、曝光等)
            tech_prompt = "USER: <img><image></img>\nHow would you rate the quality of this image?\nASSISTANT:"
            
            # 2. 詢問美感品質 (構圖、色彩、意境等)
            aes_prompt = "USER: <img><image></img>\nHow would you rate the aesthetics of this image?\nASSISTANT:"

            # 處理影像與 Prompt
            inputs_tech = self.processor(text=[tech_prompt], images=[pil_image], return_tensors='pt').to(self.device)
            inputs_aes = self.processor(text=[aes_prompt], images=[pil_image], return_tensors='pt').to(self.device)

            with torch.no_grad():
                out_tech = self.model.generate(**inputs_tech, max_new_tokens=10)
                out_aes = self.model.generate(**inputs_aes, max_new_tokens=10)

            tech_result = self.processor.batch_decode(out_tech, skip_special_tokens=True)[0]
            aes_result = self.processor.batch_decode(out_aes, skip_special_tokens=True)[0]

            # 萃取 ASSISTANT: 後面的單字 (Excellent, Good, Fair, Poor, Bad)
            tech_level = tech_result.split("ASSISTANT:")[-1].strip()
            aes_level = aes_result.split("ASSISTANT:")[-1].strip()

            return {
                "technical_score": self._get_score_from_level(tech_level),
                "aesthetic_score": self._get_score_from_level(aes_level)
            }
        except Exception as e:
            print(f"[Q-Align Error] 評分失敗: {e}")
            return {"technical_score": 60.0, "aesthetic_score": 60.0}