from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.TaskMode import TaskMode

class PromptFactory:
    """純粹的路由工廠"""
    @staticmethod
    def create_prompt(mode: TaskMode, manager: BasePromptManager) -> str:
        prompt_map = {
            TaskMode.GLOBAL_ANALYSIS: manager.get_media_analysis_prompt,
            TaskMode.ACTION_INDEX: manager.get_action_index_prompt,
            TaskMode.STYLE_EXTRACTION: manager.get_cinematic_style_prompt,
            TaskMode.TIMECODED_ACTION_INDEX: manager.get_timecoded_action_index_prompt # 新增路由
        }
        generate_prompt_func = prompt_map.get(mode, manager.get_media_analysis_prompt)
        return generate_prompt_func()