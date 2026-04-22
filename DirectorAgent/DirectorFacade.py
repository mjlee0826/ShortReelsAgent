from DirectorAgent.ContextCompressor import ContextCompressor
from DirectorAgent.States.IntentState import IntentState

class DirectorFacade:
    """
    Facade Pattern: Phase 4 總指揮。
    已升級：支援 Template DNA 導入與對話式微調 (Iterative Refinement)。
    """
    def __init__(self):
        self.compressor = ContextCompressor()

    def generate_timeline(self, user_prompt: str, raw_assets: list, template_dna: dict = None, previous_timeline: list = None) -> dict:
        """
        一鍵生成或微調時間軸。
        :param user_prompt: 使用者指令
        :param raw_assets: Phase 1 產出的原始素材清單
        :param template_dna: (選填) Phase 2 產出的範本 DNA
        :param previous_timeline: (選填) 若使用者要求修改，傳入上一版的藍圖
        """
        print("\n🎬 [Director Agent] 導演大腦啟動...")
        
        # 1. 預處理：資料降維 (排除 technical_score < 40 的素材)
        compressed_assets = self.compressor.compress(raw_assets)
        
        # 2. 初始化 context，納入所有參考資訊
        context = {
            "user_prompt": user_prompt,
            "assets": compressed_assets,
            "template_dna": template_dna,        # 範本資訊
            "previous_timeline": previous_timeline, # 歷史藍圖
            "audio_dna": None,
            "timeline_draft": None,
            "final_timeline": None
        }

        # 3. 狀態機啟動
        state = IntentState()
        while state is not None:
            state = state.run(context)
            
        print("✅ [Director Agent] 藍圖規劃完成！")
        return context["final_timeline"]