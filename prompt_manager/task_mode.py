from enum import Enum

class TaskMode(Enum):
    """定義 Agent 系統中所有需要大語言模型處理的任務模式"""
    GLOBAL_ANALYSIS = "global_analysis"               # 靜態圖片與簡單短影片的全局分析（Qwen 本地）
    COMPLEX_IMAGE_ANALYSIS = "complex_image_analysis" # 靜態圖片的深度語意分析（Gemini 雲端，付費方案）
    TIMECODED_ACTION_INDEX = "timecoded_action_index" # 複雜影片與 Template 的多模態時間軸解析
    DIRECTOR_SCHEDULING = "director_scheduling"       # 導演大腦排程草稿生成
    INTENT_TRANSLATION = "intent_translation"         # 將使用者需求轉譯為音樂搜尋關鍵字