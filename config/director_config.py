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

# ── Casting 候選池目標大小 (CastingState) ───────────────────────────────────────
# 第一段 Casting 是『粗篩』不是『定剪』:它只剔除明顯不相關 / 重複 / 品質太差的,把素材收斂成一個
# 『候選池』,最終要用哪些、怎麼排由較強的第二段(精修)決定。池子大小設成「壓回單階段也能穩定
# 處理的規模」,故預設與觸發門檻同為 40(上百素材 → ~40,而非被砍到剩成片數量)。CastingState 會
# deterministic 強制此規模:模型選太多 → 取最相關的前 N;選太少 → 用高 aes 的未選素材補足,確保第二段
# 永遠有充足素材可選。調大 = 給第二段更多選擇但 context 更大、調小 = context 更省但選擇更少。
# 可由 env DIRECTOR_CASTING_POOL_TARGET 覆寫;壞字串回退預設。
_CASTING_POOL_TARGET_DEFAULT = 40
try:
    DIRECTOR_CASTING_POOL_TARGET = int(
        os.environ.get("DIRECTOR_CASTING_POOL_TARGET", _CASTING_POOL_TARGET_DEFAULT)
    )
except ValueError:
    DIRECTOR_CASTING_POOL_TARGET = _CASTING_POOL_TARGET_DEFAULT
