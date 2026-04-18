from PromptManager.BasePromptManager import BasePromptManager

class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。
    """
    
    def get_media_analysis_prompt(self) -> str:
        return (
            "請詳細描述這份素材(圖片或影片)的主要內容與動作。"
            "接著，請找出畫面最核心的「視覺主體」（如：主要人物的人臉、食物特寫、動物等）。"
            "請估算該主體『中心點』在畫面中的相對座標 (X 為水平寬度，Y 為垂直高度，皆為 0~100 的整數)。"
            "【警告】請務必真實觀察並計算座標！例如主體在畫面左上方可能是 {'x': 20, 'y': 20}，在右下方可能是 {'x': 80, 'y': 90}。絕對不可以照抄範例！"
            "最後，請以專業攝影師的角度判斷，這個畫面是否有嚴重的失焦、模糊或是劇烈手震？"
            "請以嚴格的 JSON 格式回傳，絕對不能包含其他 markdown 標記，必須包含三個 key: "
            "'caption' (字串，繁體中文描述), "
            "'is_blurry' (布林值，true代表嚴重模糊/手震廢片，false代表畫質可接受), "
            "'subject_focus' (字典，包含 'x' 與 'y' 兩個「整數」，例如 {'x': 50, 'y': 50})。"
        )