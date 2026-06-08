from director_agent.states.base_state import BaseState
from director_agent.music_director import MusicDirector, MUSIC_STRATEGY_SEARCH_COPYRIGHT


class IntentState(BaseState):
    """
    State Pattern：Phase 3 配樂節點（薄轉接層）。

    實際的配樂決策（萃取關鍵字 / 搜尋 / 分析）已抽至獨立模組 ``MusicDirector``，
    與狀態機解耦、可被「只換音樂」等流程重用；本 State 只負責讀 context、委派、寫回 audio_dna。
    """

    def run(self, context: dict):
        print("\n[Agent State] 進入 IntentState：決定配樂策略...")

        # 純對話微調（regenerate_music=False）：不重抓配樂，跳過搜尋 / 下載。
        # 最終 bgm_track 由 facade 直接沿用上一版（保留曲目 / 音量 / 起播），這裡空 audio_dna 即可。
        if not context.get("regenerate_music", True):
            print("[Agent State] ⏩ 微調不重抓配樂，沿用上一版 BGM。")
            context["audio_dna"] = {}
            return self._next_state()

        # 委派 MusicDirector 做實際決策（與 change_music 共用同一入口，邏輯一致）
        context["audio_dna"] = MusicDirector().resolve(
            music_strategy=context.get("music_strategy", MUSIC_STRATEGY_SEARCH_COPYRIGHT),
            user_music_file=context.get("user_music_file"),
            user_prompt=context.get("user_prompt", ""),
        )
        return self._next_state()

    def _next_state(self):
        """統一的狀態切換出口，轉至排程階段。"""
        from director_agent.states.scheduling_state import SchedulingState
        return SchedulingState()
