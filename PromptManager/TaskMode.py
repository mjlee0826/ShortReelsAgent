from enum import Enum

class TaskMode(Enum):
    """定義 Agent 系統中所有需要大語言模型處理的任務模式"""
    GLOBAL_ANALYSIS = "global_analysis"  # Phase 1: 短影片全局美學打分
    ACTION_INDEX = "action_index"        # Phase 1: 長影片 2-3 秒動作切片
    STYLE_EXTRACTION = "style_extraction" # Phase 2: Reels 範本逆向工程