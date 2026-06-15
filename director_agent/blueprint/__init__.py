"""藍圖準備的 DNA 生產者 (Strategy)：Template DNA / Music DNA。

把素材深度感知 / 配樂解析抽成 ``DnaProducer``(Strategy)。Phase 4 agentic 改造後改由 ``director_service``
inline 編排（template 主執行緒、music 背景 future 與導演 loop 重疊），不再經 ``BlueprintPreparer`` fork-join
（已移除）。配樂解析的實際入口為 ``director_agent.music_director.MusicDirector``。
"""
from director_agent.blueprint.prep_context import PrepContext
from director_agent.blueprint.dna_producer import DnaProducer
from director_agent.blueprint.template_dna_producer import TemplateDnaProducer

__all__ = [
    "PrepContext",
    "DnaProducer",
    "TemplateDnaProducer",
]
