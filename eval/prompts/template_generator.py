"""範本式 prompt 生成器（決定性、可重現、無 API）。

以 ``group_id`` 推導固定種子抽樣；保證涵蓋各詳細度級距（至少一個極簡、一個極詳細），並盡量
避免同組內 prompt 文字重複。
"""
from __future__ import annotations

import random

from ..constants import (
    CAPTION_ADD,
    CAPTION_NEGATIVE_MIN_PROMPTS,
    CAPTION_NO,
    CAPTION_NONE,
    PROMPT_COMPOSE_MAX_ATTEMPTS,
)
from ..logging_setup import get_logger
from ..models import GroupSpec, PromptVariant
from ..seeding import stable_seed
from .base import PromptGenerator
from .lexicon import (
    CAPTION_CHOICES,
    CAPTION_NEGATIVE_TEMPLATES,
    CAPTION_TEMPLATES,
    DETAIL_DETAILED,
    DETAIL_LEVEL_ORDER,
    DETAIL_MINIMAL,
    DETAIL_SPECIFIC,
    DETAIL_TO_PROMPT_DIFFICULTY,
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
        captions = self._caption_sequence(levels, rng)

        variants: list[PromptVariant] = []
        seen_texts: set[str] = set()
        for level, caption in zip(levels, captions):
            variants.append(self._compose(level, caption, group, lexicon, rng, seen_texts))
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

    @staticmethod
    def _caption_sequence(levels: list[str], rng: random.Random) -> list[str]:
        """對齊 levels 產生字幕標記序列：保證至少一個正面字幕 prompt，量夠時再保證一個負面。

        字幕範本只存在於 specific/detailed 兩級，故只在這些位置指派（其餘維持 none）。
        """
        labels = [CAPTION_NONE] * len(levels)
        capable = [i for i, lv in enumerate(levels) if lv in (DETAIL_SPECIFIC, DETAIL_DETAILED)]
        if not capable:
            return labels  # 例如 prompt_count 過小、無 specific/detailed 位置
        rng.shuffle(capable)  # 決定性洗牌：保證涵蓋但位置不固定
        labels[capable[0]] = CAPTION_ADD
        if len(levels) >= CAPTION_NEGATIVE_MIN_PROMPTS and len(capable) >= 2:
            labels[capable[1]] = CAPTION_NO
        return labels

    def _compose(
        self,
        level: str,
        caption: str,
        group: GroupSpec,
        lexicon: dict[str, list[str]],
        rng: random.Random,
        seen_texts: set[str],
    ) -> PromptVariant:
        """組出單一 prompt；盡量避免與已產生的重複。"""
        templates = self._templates_for(level, caption, group)
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
                "caption": rng.choice(CAPTION_CHOICES),  # 僅字幕正面範本會用到
            }
            text = self._tidy(template.format(**fields))
            if text not in seen_texts:
                break
        seen_texts.add(text)
        return PromptVariant(
            text=text,
            detail_level=level,
            difficulty=DETAIL_TO_PROMPT_DIFFICULTY[level],  # U 型：兩端難、中間易
            tone=tone_name,
            scenario=scenario_name,
            caption=caption,
        )

    @staticmethod
    def _templates_for(level: str, caption: str, group: GroupSpec) -> list[str]:
        """依字幕標記挑模板池：字幕正面/負面走專用模板，其餘走一般模板＋scope 專屬模板。"""
        if caption == CAPTION_ADD:
            return CAPTION_TEMPLATES[level]
        if caption == CAPTION_NO:
            return CAPTION_NEGATIVE_TEMPLATES[level]
        scope_pool = SCOPE_TEMPLATES.get(group.scope or "", {}).get(level, [])
        return TEMPLATES[level] + scope_pool

    @staticmethod
    def _tidy(text: str) -> str:
        """清掉多餘空白並確保句尾有結束標點。"""
        cleaned = text.strip()
        if not cleaned.endswith(_SENTENCE_ENDINGS):
            cleaned += "。"
        return cleaned
