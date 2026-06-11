"""藍圖準備階段(Phase 2 Template DNA ∥ Phase 3 Music DNA)的 fork-join 並行套件。

把彼此獨立的 template / music 兩分支抽成 ``DnaProducer``(Strategy),由 ``BlueprintPreparer``
以 fork-join 並行;兩分支的 GPU 工作經 Tier A(``ModelPoolRegistry``)共用同一 GpuGate,
並行不撞 VRAM。設計見 docs/blueprint_prep_design.md。
"""
from director_agent.blueprint.prep_context import PrepContext
from director_agent.blueprint.dna_producer import DnaProducer
from director_agent.blueprint.template_dna_producer import TemplateDnaProducer
from director_agent.blueprint.music_dna_producer import MusicDnaProducer
from director_agent.blueprint.blueprint_preparer import BlueprintPreparer

__all__ = [
    "PrepContext",
    "DnaProducer",
    "TemplateDnaProducer",
    "MusicDnaProducer",
    "BlueprintPreparer",
]
