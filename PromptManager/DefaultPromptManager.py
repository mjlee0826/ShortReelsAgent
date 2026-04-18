from PromptManager.BasePromptManager import BasePromptManager

class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。
    """
    
    def get_media_analysis_prompt(self) -> str:
        return (
            "請詳細描述這份素材(圖片或影片)的主要內容與動作。"
            "接著，請找出畫面的「視覺核心主體」（如：主要人物的人臉、食物、動物等），"
            "並給出該主體在畫面中的大約中心點比例位置 (X與Y，以百分比表示，例如 50%)。"
            "最後，請以專業攝影師的角度判斷，這個畫面是否有嚴重的失焦、模糊或是劇烈手震？"
            "請以嚴格的 JSON 格式回傳，絕對不能包含其他 markdown 標記，必須包含三個 key: "
            "'caption' (字串，繁體中文描述), "
            "'is_blurry' (布林值，true代表嚴重模糊/手震廢片，false代表畫質可接受), "
            "'subject_focus' (字典，包含 'x' 與 'y' 兩個字串，例如 {'x': '50%', 'y': '30%'})。"
        )