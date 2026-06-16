"""
導演 Agent 行為常數集中管理 (Configuration Object Pattern)。
director_agent/ 的調校參數從此處 import，避免 magic number 散落各檔。
"""
import os

# ── source_end 溢位的 deterministic 修補容差 (ClipDurationRepairer) ───────────────
# 導演（LLM）常把 source_end 四捨五入到數位小數（如把 1.6666666666666667 寫成 1.6667），
# 使其「超出」素材物理時長一個次毫秒的量；這純屬捨入雜訊，素材本就沒有那一格可放，夾回物理
# 長度即可，毫無視覺影響。低於此容差的溢位於 Critic 驗證『之前』被就地夾回，省下本可確定修掉的
# 捨入誤差所觸發的反思往返；超過此容差才視為導演真的要了不存在的片段，保留原值交由 Critic
# 標錯、退回重寫。值取 0.05s：對「捨入到 2 位小數」最壞的 0.005s 仍留 10× 餘裕，且 ≤ 既有
# playback_rate 一致性檢查的 0.1s 容差，故夾回造成的時長變動永遠落在該檢查容差內，不會反倒
# 製造新的 Critic 錯誤。
SOURCE_END_OVERFLOW_REPAIR_TOLERANCE_SECONDS = 0.05

# ── 偏好 few-shot 注入上限 (偏好資料飛輪 T2;見 prompt_manager/preference_few_shot.py) ──
# 把過往使用者修正當 few-shot 餵進導演 prompt 時的硬性截長,杜絕 prompt 暴長:整份藍圖很大,
# 故只放「壓縮版欄位 diff」(path: before → after)並以下列具名上限封頂(見
# docs/preference_data_flywheel.md)。
# 最多注入幾筆修正範例。
MAX_FEWSHOT_EXAMPLES = 5
# 每筆範例最多列幾個被改欄位(超過則截斷,只留最具代表性的前幾項)。
MAX_FIELDS_PER_EXAMPLE = 6
# 人工策展的偏好範例檔(與本 config 同目錄);檔缺 / 空 → 不注入,prompt 完全不變(預設關)。
PREFERENCE_FEW_SHOT_EXAMPLES_PATH = os.path.join(
    os.path.dirname(__file__), "preference_few_shot_examples.json"
)

# ── Agentic 導演 loop 行為參數 (Phase 4 改造：固定兩階段 → 多輪 tool-use) ──────────────
# 導演 agentic loop 的硬性步數上限(每步 = 一次模型回合 / 一輪工具呼叫)。自選讀取 + 必讀原素材 +
# Critic 餵回修正都在此預算內收斂;達上限強制收尾,避免無限往返扣款。可由 env 覆寫;壞字串回退預設。
_AGENTIC_MAX_STEPS_DEFAULT = 24
try:
    DIRECTOR_AGENTIC_MAX_STEPS = int(
        os.environ.get("DIRECTOR_AGENTIC_MAX_STEPS", _AGENTIC_MAX_STEPS_DEFAULT)
    )
except ValueError:
    DIRECTOR_AGENTIC_MAX_STEPS = _AGENTIC_MAX_STEPS_DEFAULT

# submit_blueprint 後 Critic 驗證不過 → 把錯誤當 tool_result 餵回同一對話就地修的最大重試次數
# (沿用舊 ReflectionState 的 3 次;達上限即輸出當前草稿,行為與舊一致)。
_MAX_CRITIC_RETRIES_DEFAULT = 3
try:
    DIRECTOR_MAX_CRITIC_RETRIES = int(
        os.environ.get("DIRECTOR_MAX_CRITIC_RETRIES", _MAX_CRITIC_RETRIES_DEFAULT)
    )
except ValueError:
    DIRECTOR_MAX_CRITIC_RETRIES = _MAX_CRITIC_RETRIES_DEFAULT

# get_fields 單次最多投影幾個素材 id(杜絕模型一次把整庫所有重欄位拉出來,違背漸進精讀初衷)。
_GET_FIELDS_MAX_IDS_DEFAULT = 60
try:
    DIRECTOR_GET_FIELDS_MAX_IDS = int(
        os.environ.get("DIRECTOR_GET_FIELDS_MAX_IDS", _GET_FIELDS_MAX_IDS_DEFAULT)
    )
except ValueError:
    DIRECTOR_GET_FIELDS_MAX_IDS = _GET_FIELDS_MAX_IDS_DEFAULT

# view_raw 單次最多抓幾張幀(影片);像素 token 昂貴(高解析圖約 4.8K tokens/張),故封頂。
_VIEW_RAW_MAX_FRAMES_DEFAULT = 4
try:
    DIRECTOR_VIEW_RAW_MAX_FRAMES = int(
        os.environ.get("DIRECTOR_VIEW_RAW_MAX_FRAMES", _VIEW_RAW_MAX_FRAMES_DEFAULT)
    )
except ValueError:
    DIRECTOR_VIEW_RAW_MAX_FRAMES = _VIEW_RAW_MAX_FRAMES_DEFAULT

# view_template 單次最多抓幾張範本幀。範本切點可能很多,但每張幀都是昂貴的像素 token,故另封一個
# 上限(與看單一素材的 view_raw 分開計):值略高於 view_raw,讓導演一次看清範本的鏡頭序列 / 節奏。
_VIEW_RAW_TEMPLATE_MAX_FRAMES_DEFAULT = 6
try:
    DIRECTOR_VIEW_RAW_TEMPLATE_MAX_FRAMES = int(
        os.environ.get("DIRECTOR_VIEW_RAW_TEMPLATE_MAX_FRAMES", _VIEW_RAW_TEMPLATE_MAX_FRAMES_DEFAULT)
    )
except ValueError:
    DIRECTOR_VIEW_RAW_TEMPLATE_MAX_FRAMES = _VIEW_RAW_TEMPLATE_MAX_FRAMES_DEFAULT

# view_raw 抓出的幀長邊降到此像素再 base64(控成本;對導演判斷構圖 / 主體已足夠)。
_VIEW_RAW_DOWNSCALE_PX_DEFAULT = 1080
try:
    DIRECTOR_VIEW_RAW_DOWNSCALE_PX = int(
        os.environ.get("DIRECTOR_VIEW_RAW_DOWNSCALE_PX", _VIEW_RAW_DOWNSCALE_PX_DEFAULT)
    )
except ValueError:
    DIRECTOR_VIEW_RAW_DOWNSCALE_PX = _VIEW_RAW_DOWNSCALE_PX_DEFAULT

# 「必讀原素材才能用」的時間重疊容差(秒):判定某 clip 的 [source_start, source_end] 是否被已
# view_raw 的時間範圍涵蓋時允許此容差,避免邊界捨入造成誤判。
DIRECTOR_VIEWED_OVERLAP_TOLERANCE_SECONDS = 0.5

# Task Budget(beta):>0 才啟用,把整輪 agentic 的 token 預算告知模型讓它自我節制。預設 0(關閉)
# 以走最穩定的非 beta 串流路徑;要開再設正值(走 beta header,見 ClaudeModelManager)。
_TASK_BUDGET_TOKENS_DEFAULT = 0
try:
    DIRECTOR_TASK_BUDGET_TOKENS = int(
        os.environ.get("DIRECTOR_TASK_BUDGET_TOKENS", _TASK_BUDGET_TOKENS_DEFAULT)
    )
except ValueError:
    DIRECTOR_TASK_BUDGET_TOKENS = _TASK_BUDGET_TOKENS_DEFAULT

# get_music_beats join 背景配樂 future 的逾時(秒)：配樂下載 + 節拍分析可能慢,給夠避免誤判失敗。
DIRECTOR_MUSIC_FUTURE_TIMEOUT_SECONDS = 180
