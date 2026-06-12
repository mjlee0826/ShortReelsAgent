"""
導演 Agent 行為常數集中管理 (Configuration Object Pattern)。
director_agent/ 的調校參數從此處 import，避免 magic number 散落各檔。
"""
import os

# ── 兩階段導演觸發門檻 (DirectorFacade) ───────────────────────────────────────
# 全新生成時，壓縮後素材數「超過」此值才啟用 Casting → Scheduling 兩階段（先選角縮小
# context、再精修時間軸）；未超過則維持單階段。素材一多，單次把全部素材塞進導演會讓模型
# 對物理鐵律（overlap/gap/duration/clip_id）的遵從度下滑、Critic 錯誤與重試暴增，故以此
# 門檻在進入退化區間前接管。可由 env DIRECTOR_TWO_STAGE_MIN_ASSETS 覆寫，方便不改碼從 log
# 觀測各區間失敗率後微調；壞字串視為未設定，回退預設值以保證啟動穩定。
_TWO_STAGE_MIN_ASSETS_DEFAULT = 40
try:
    DIRECTOR_TWO_STAGE_MIN_ASSETS = int(
        os.environ.get("DIRECTOR_TWO_STAGE_MIN_ASSETS", _TWO_STAGE_MIN_ASSETS_DEFAULT)
    )
except ValueError:
    DIRECTOR_TWO_STAGE_MIN_ASSETS = _TWO_STAGE_MIN_ASSETS_DEFAULT
