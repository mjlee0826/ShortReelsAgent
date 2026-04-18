from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.TaskMode import TaskMode

class PromptFactory:
    """
    純粹的路由工廠：
    根據傳入的 TaskMode，動態呼叫傳入的 manager (不管是 Default 還是 Custom) 
    對應的方法。
    """
    @staticmethod
    def create_prompt(mode: TaskMode, manager: BasePromptManager) -> str:
        # 將對應的方法 mapping 起來 (注意這裡不加括號，只是 function reference)
        prompt_map = {
            TaskMode.GLOBAL_ANALYSIS: manager.get_media_analysis_prompt,
            TaskMode.ACTION_INDEX: manager.get_action_index_prompt,
            TaskMode.STYLE_EXTRACTION: manager.get_cinematic_style_prompt
        }

        # 取得對應的方法，若無則 fallback 到全局分析
        generate_prompt_func = prompt_map.get(mode, manager.get_media_analysis_prompt)
        
        # 執行並回傳 Prompt 字串
        return generate_prompt_func()