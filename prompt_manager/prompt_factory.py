from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.task_mode import TaskMode

class PromptFactory:
    """純粹的路由工廠：把 TaskMode 映射到 PromptManager 對應的提示詞方法。"""
    @staticmethod
    def create_prompt(mode: TaskMode, manager: BasePromptManager, **kwargs) -> str:
        # TaskMode → 對應的提示詞產生方法
        prompt_map = {
            TaskMode.BASIC_MEDIA_ANALYSIS: manager.get_basic_media_analysis_prompt,
            TaskMode.DEEP_IMAGE_ANALYSIS: manager.get_deep_image_analysis_prompt,  # 深度圖片分析（Gemini）
            TaskMode.VIDEO_EVENT_INDEX: manager.get_video_event_index_prompt,
            TaskMode.TEMPLATE_ANALYSIS: manager.get_template_analysis_prompt,      # 範本分析（含音樂偵測）
            TaskMode.DIRECTOR_BLUEPRINT: manager.get_director_blueprint_prompt,
            TaskMode.MUSIC_SEARCH_QUERY: manager.get_music_search_query_prompt,
        }

        # 未知 mode 退回基本媒體分析（最安全的全局描述）
        generate_prompt_func = prompt_map.get(mode, manager.get_basic_media_analysis_prompt)
        return generate_prompt_func(**kwargs)
