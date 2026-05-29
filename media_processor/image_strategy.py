"""圖片處理策略列舉，供 MediaProcessorFactory 路由使用。"""

from enum import Enum


class ImageStrategy(Enum):
    """
    策略模式 (Strategy) 列舉：決定圖片使用哪種感知引擎。

    SIMPLE  → 本地 Qwen 全局分析（快速，免費方案）
    COMPLEX → Gemini API 深度分析（品質更高，付費方案）
    """
    SIMPLE = "simple"
    COMPLEX = "complex"
