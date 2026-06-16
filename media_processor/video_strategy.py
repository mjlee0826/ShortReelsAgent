"""影片處理策略列舉，供 MediaProcessorFactory 路由使用。"""

from enum import Enum


class VideoStrategy(Enum):
    """
    策略模式 (Strategy) 列舉：決定影片使用哪種感知引擎。

    SIMPLE   → 本地 Qwen 全局分析（快速，無時間碼燒錄）
    COMPLEX  → Gemini API 精確索引（慢但準確，需燒錄視覺時間碼）
    TEMPLATE → 範本專屬精簡分析：純訊號 DAG（decode + scene），無任何 LLM。視覺理解改由導演
               view_template 親眼看原始幀，只保留導演還原不了的物理切點（剪輯節奏）與結構資訊，
               供 TemplateDnaProducer 的 template 分支使用。
    """
    SIMPLE = "simple"
    COMPLEX = "complex"
    TEMPLATE = "template"


# 全域影片預設策略：未被 asset_strategies 逐檔覆寫的影片一律走 SIMPLE（本地 Qwen）。
# 逐檔 COMPLEX（Gemini 深度索引）才是實際的策略切換入口（見 PipelineRunner._build_contexts），
# 故全域預設收斂為此具名常數、不再對外開放為 run() 參數，避免「呼叫端永遠只能傳 SIMPLE」的死彈性。
DEFAULT_VIDEO_STRATEGY = VideoStrategy.SIMPLE
