from enum import Enum

class TaskMode(Enum):
    """各種需要大語言模型處理的任務模式；名稱對應 PromptManager 的提示詞方法，1:1 易於對照。"""
    BASIC_MEDIA_ANALYSIS = "basic_media_analysis"   # 圖片 / 簡單短影片的全局描述與語意標籤（Qwen 本地）
    DEEP_IMAGE_ANALYSIS = "deep_image_analysis"     # 靜態圖片的深度語意分析（Gemini 雲端，付費方案）
    VIDEO_EVENT_INDEX = "video_event_index"         # 複雜影片的逐時間段多模態事件 + 音訊轉錄（Gemini）
    DIRECTOR_BLUEPRINT = "director_blueprint"       # 導演剪輯藍圖（Remotion 可渲染 JSON；成本歸 Phase 4）
    MUSIC_SEARCH_QUERY = "music_search_query"       # 把使用者需求轉成配樂搜尋關鍵字
