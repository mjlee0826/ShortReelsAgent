"""範本式 prompt 生成器（決定性、可重現、無 API）。

以 ``group_id`` 推導固定種子抽樣；保證涵蓋各詳細度級距（至少一個極簡、一個極詳細），並盡量
避免同組內 prompt 文字重複。
"""
from __future__ import annotations

import random

from ..constants import PROMPT_COMPOSE_MAX_ATTEMPTS
from ..logging_setup import get_logger
from ..models import GroupSpec, PromptVariant
from ..seeding import stable_seed
from .base import PromptGenerator
from .lexicon import (
    DETAIL_DETAILED,
    DETAIL_LEVEL_ORDER,
    DETAIL_MINIMAL,
    DURATION_CHOICES,
    MUSIC_CHOICES,
    PLATFORM_CHOICES,
    SCENARIO_CHOICES,
    SCOPE_TEMPLATES,
    STYLE_CHOICES,
    TEMPLATES,
    THEME_LEXICONS,
    TONE_CHOICES,
    generic_lexicon,
)

logger = get_logger(__name__)

# 種子用途後綴（避免與策展洗牌的種子相同）
_SEED_SUFFIX: str = "::prompts"
# 句尾可接受的結束符號（_tidy 用）
_SENTENCE_ENDINGS: tuple[str, ...] = ("。", "！", "？", "?", "!")


class TemplatePromptGenerator(PromptGenerator):
    """以手寫範本 + 主題詞庫組合出多樣 prompt。"""

    def generate(self, group: GroupSpec) -> list[PromptVariant]:
        """為單組生成 ``prompt_count`` 個 prompt。"""
        rng = random.Random(stable_seed(group.group_id + _SEED_SUFFIX))
        lexicon = THEME_LEXICONS.get(group.theme) or generic_lexicon(group.theme)
        levels = self._level_sequence(group.prompt_count)

        variants: list[PromptVariant] = []
        seen_texts: set[str] = set()
        for level in levels:
            variants.append(self._compose(level, group, lexicon, rng, seen_texts))
        return variants

    @staticmethod
    def _level_sequence(count: int) -> list[str]:
        """產生長度為 count 的詳細度序列，並保證含最簡與最詳細。"""
        base = DETAIL_LEVEL_ORDER
        sequence = [base[i % len(base)] for i in range(count)]
        if count >= 1:
            sequence[0] = DETAIL_MINIMAL
        if count >= 2:
            sequence[-1] = DETAIL_DETAILED
        return sequence

    def _compose(
        self,
        level: str,
        group: GroupSpec,
        lexicon: dict[str, list[str]],
        rng: random.Random,
        seen_texts: set[str],
    ) -> PromptVariant:
        """組出單一 prompt；盡量避免與已產生的重複。"""
        # 依 scope 把專屬模板併入該詳細度的候選池（無 scope 則照舊）
        scope_pool = SCOPE_TEMPLATES.get(group.scope or "", {}).get(level, [])
        templates = TEMPLATES[level] + scope_pool
        text = ""
        tone_name = ""
        scenario_name = ""
        for _ in range(PROMPT_COMPOSE_MAX_ATTEMPTS):
            template = rng.choice(templates)
            tone_name, tone_prefix = rng.choice(TONE_CHOICES)
            scenario_name, scenario_phrase = rng.choice(SCENARIO_CHOICES)
            fields = {
                "theme": group.theme,
                "tone": tone_prefix,
                "scenario": scenario_phrase,
                "subject": rng.choice(lexicon["subjects"]),
                "hook": rng.choice(lexicon["hooks"]),
                "duration": rng.choice(DURATION_CHOICES),
                "style": rng.choice(STYLE_CHOICES),
                "music": rng.choice(MUSIC_CHOICES),
                "platform": rng.choice(PLATFORM_CHOICES),
            }
            text = self._tidy(template.format(**fields))
            if text not in seen_texts:
                break
        seen_texts.add(text)
        return PromptVariant(text=text, detail_level=level, tone=tone_name, scenario=scenario_name)

    @staticmethod
    def _tidy(text: str) -> str:
        """清掉多餘空白並確保句尾有結束標點。"""
        cleaned = text.strip()
        if not cleaned.endswith(_SENTENCE_ENDINGS):
            cleaned += "。"
        return cleaned
