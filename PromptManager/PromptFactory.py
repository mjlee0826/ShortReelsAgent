from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.TaskMode import TaskMode

class PromptFactory:
    """純粹的路由工廠：統一管理全系統的 Prompt 產出"""
    @staticmethod
    def create_prompt(mode: TaskMode, manager: BasePromptManager, **kwargs) -> str:
        # 將 TaskMode 映射到對應的 Manager 方法
        prompt_map = {
            TaskMode.GLOBAL_ANALYSIS: manager.get_media_analysis_prompt,
            TaskMode.TIMECODED_ACTION_INDEX: manager.get_timecoded_action_index_prompt,
            TaskMode.DIRECTOR_SCHEDULING: manager.get_director_prompt,
            TaskMode.INTENT_TRANSLATION: manager.get_intent_translation_prompt # 【新增】路由至意圖轉譯 Prompt
        }
        
        generate_prompt_func = prompt_map.get(mode, manager.get_media_analysis_prompt)
        return generate_prompt_func(**kwargs)