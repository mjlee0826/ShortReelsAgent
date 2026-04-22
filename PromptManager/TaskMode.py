from enum import Enum

class TaskMode(Enum):
    """定義 Agent 系統中所有需要大語言模型處理的任務模式"""
    GLOBAL_ANALYSIS = "global_analysis"               # 靜態圖片與簡單短影片的全局分析
    TIMECODED_ACTION_INDEX = "timecoded_action_index" # 複雜影片與 Template 的多模態時間軸解析
    DIRECTOR_SCHEDULING = "director_scheduling"       # 【新增】導演大腦排程草稿生成