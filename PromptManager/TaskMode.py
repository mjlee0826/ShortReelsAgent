from enum import Enum

class TaskMode(Enum):
    """定義 Agent 系統中所有需要大語言模型處理的任務模式"""
    GLOBAL_ANALYSIS = "global_analysis"  # 舊版：短影片全局打分
    ACTION_INDEX = "action_index"        # 舊版：物理切片動作描述
    STYLE_EXTRACTION = "style_extraction" # Phase 2: Reels 範本逆向工程
    TIMECODED_ACTION_INDEX = "timecoded_action_index" # 【全新】視覺時間碼動作索引