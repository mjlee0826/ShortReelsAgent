"""範本式 prompt 生成器（決定性、可重現、無 API）。

每組素材生成「恰好一個」完整的 EditDuet 風格剪輯指令：先決定目標秒數（ground truth），
再以 ``group_id`` 推導的固定種子組裝指令文字，確保句中秒數與 ``target_duration_sec`` 一致。
"""
from __future__ import annotations

import random

from ..constants import (
    BROAD_TARGET_DURATIONS_SEC,
    CAPTION_REQUIREMENT_WEIGHTS,
    DEFAULT_TARGET_DURATIONS_SEC,
    FOCUSED_TARGET_DURATIONS_SEC,
    SCOPE_BROAD,
    SCOPE_FOCUSED,
)
from ..logging_setup import get_logger
from ..models import GroupSpec, PromptVariant
from ..seeding import stable_seed
from .base import PromptGenerator
from .lexicon import (
    CAPTION_CLAUSES,
    CLEANUP_CHOICES,
    GENERIC_PROMPT_TEMPLATES,
    MUSIC_CHOICES,
    SCENARIO_CHOICES,
    SCOPE_PROMPT_TEMPLATES,
    STYLE_CHOICES,
    THEME_LEXICONS,
    TONE_CHOICES,
    generic_lexicon,
)

logger = get_logger(__name__)

# 種子用途後綴（避免與策展洗牌的種子相同）
_SEED_SUFFIX: str = "::prompts"
# 句尾可接受的結束符號（_tidy 用）
_SENTENCE_ENDINGS: tuple[str, ...] = ("。", "！", "？", "?", "!")
# 一段指令中要鋪陳的不同主體數量（中段兩個 + 結尾一個）
_SUBJECTS_PER_PROMPT: int = 3
# 每組固定產生的 prompt 數量
_PROMPTS_PER_GROUP: int = 1


class TemplatePromptGenerator(PromptGenerator):
    """以手寫範本 + 主題詞庫組出單一完整的 EditDuet 風格指令。"""

    def generate(self, group: GroupSpec) -> list[PromptVariant]:
        """為單組生成恰好一個 canonical prompt（決定性）。"""
        if group.prompt_count != _PROMPTS_PER_GROUP:
            # 已改為單一 canonical prompt 設計；舊 spec 的 prompt_count 一律忽略（不報錯）
            logger.info(
                "組 %s：已改為單一 canonical prompt 設計，忽略 prompt_count=%d",
                group.group_id, group.prompt_count,
            )
        rng = random.Random(stable_seed(group.group_id + _SEED_SUFFIX))
        lexicon = THEME_LEXICONS.get(group.theme) or generic_lexicon(group.theme)
        return [self._compose(group, lexicon, rng)]

    def _compose(
        self, group: GroupSpec, lexicon: dict[str, list[str]], rng: random.Random
    ) -> PromptVariant:
        """組出單一完整指令；先決定秒數與字幕要求（ground truth），再渲染文字。"""
        # 1) 目標秒數：依 scope 取對應秒數集合（保證短於素材秒數預算）
        target_duration_sec = rng.choice(self._duration_choices_for(group.scope))
        # 2) 字幕要求：依權重決定性抽樣，並取對應子句
        caption_requirement = self._pick_caption_requirement(rng)
        caption_clause = rng.choice(CAPTION_CLAUSES[caption_requirement])
        # 3) 其餘描述性欄位與內容詞
        tone_name, tone_prefix = rng.choice(TONE_CHOICES)
        scenario_name, scenario_phrase = rng.choice(SCENARIO_CHOICES)
        style = rng.choice(STYLE_CHOICES)
        music = rng.choice(MUSIC_CHOICES)
        hook = rng.choice(lexicon["hooks"])
        subject_a, subject_b, subject_c = self._pick_subjects(lexicon["subjects"], rng)
        cleanup = rng.choice(CLEANUP_CHOICES)
        # 4) 選 scope 範本並渲染（秒數以整數填入「N 秒」，與 target_duration_sec 必然一致）
        template = rng.choice(self._templates_for(group.scope))
        text = self._tidy(template.format(
            tone=tone_prefix,
            theme=group.theme,
            duration=target_duration_sec,
            hook=hook,
            subject_a=subject_a,
            subject_b=subject_b,
            subject_c=subject_c,
            style=style,
            music=music,
            cleanup=cleanup,
            caption_clause=caption_clause,
            scenario=scenario_phrase,
        ))
        return PromptVariant(
            text=text,
            target_duration_sec=target_duration_sec,
            caption_requirement=caption_requirement,
            style=style,
            music=music,
            opening_hook=hook,
            tone=tone_name,
            scenario=scenario_name,
        )

    @staticmethod
    def _duration_choices_for(scope: str | None) -> tuple[int, ...]:
        """依 scope 回傳目標秒數候選集合（focused 較短、broad 較長）。"""
        if scope == SCOPE_FOCUSED:
            return FOCUSED_TARGET_DURATIONS_SEC
        if scope == SCOPE_BROAD:
            return BROAD_TARGET_DURATIONS_SEC
        return DEFAULT_TARGET_DURATIONS_SEC

    @staticmethod
    def _templates_for(scope: str | None) -> list[str]:
        """依 scope 回傳指令範本池；未分類用通用範本。"""
        return SCOPE_PROMPT_TEMPLATES.get(scope or "", GENERIC_PROMPT_TEMPLATES)

    @staticmethod
    def _pick_caption_requirement(rng: random.Random) -> str:
        """依 CAPTION_REQUIREMENT_WEIGHTS 決定性加權抽出字幕要求。"""
        requirements = list(CAPTION_REQUIREMENT_WEIGHTS.keys())
        weights = list(CAPTION_REQUIREMENT_WEIGHTS.values())
        return rng.choices(requirements, weights=weights, k=1)[0]

    @staticmethod
    def _pick_subjects(subjects: list[str], rng: random.Random) -> tuple[str, str, str]:
        """抽出三個（盡量不重複）主體，供中段與結尾鋪陳。"""
        if len(subjects) >= _SUBJECTS_PER_PROMPT:
            picks = rng.sample(subjects, _SUBJECTS_PER_PROMPT)
        else:
            # 主體不足三個時允許重複，仍維持決定性
            picks = [rng.choice(subjects) for _ in range(_SUBJECTS_PER_PROMPT)]
        return picks[0], picks[1], picks[2]

    @staticmethod
    def _tidy(text: str) -> str:
        """清掉多餘空白並確保句尾有結束標點。"""
        cleaned = text.strip()
        if not cleaned.endswith(_SENTENCE_ENDINGS):
            cleaned += "。"
        return cleaned
