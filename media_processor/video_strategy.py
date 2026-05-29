"""影片處理策略列舉，供 MediaProcessorFactory 路由使用。"""

from enum import Enum


class VideoStrategy(Enum):
    """
    策略模式 (Strategy) 列舉：決定影片使用哪種感知引擎。

    SIMPLE  → 本地 Qwen 全局分析（快速，無時間碼燒錄）
    COMPLEX → Gemini API 精確索引（慢但準確，需燒錄視覺時間碼）
    """
    SIMPLE = "simple"
    COMPLEX = "complex"
