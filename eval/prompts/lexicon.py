"""手寫的繁體中文 prompt 範本庫與各主題詞庫（多樣性來源）。

設計目標（對應 docs 的多樣性三軸）：
- **詳細度**：minimal（「幫我剪一下」）→ light（帶平台/情境）→ specific（指定時長/風格/音樂）
  → detailed（多項具體要求，並提到素材是亂序、要剔除壞片）。
- **語氣**：隨興／禮貌／急迫／興奮。
- **情境**：發限動／紀念／分享朋友／投稿。

範本以 ``str.format`` 佔位符填入：``{theme} {subject} {hook} {duration} {style} {music}
{platform} {scenario} {tone}``。未列入 ``THEME_LEXICONS`` 的主題會用 ``generic_lexicon`` 以
主題字串本身填空，確保 prompt 仍切合主題。
"""
from __future__ import annotations

from ..constants import SCOPE_BROAD, SCOPE_FOCUSED

# ──────────────────────────── 詳細度級別 ────────────────────────────
DETAIL_MINIMAL: str = "minimal"
DETAIL_LIGHT: str = "light"
DETAIL_SPECIFIC: str = "specific"
DETAIL_DETAILED: str = "detailed"

# 由低到高的順序（generator 用來保證涵蓋度）
DETAIL_LEVEL_ORDER: list[str] = [
    DETAIL_MINIMAL,
    DETAIL_LIGHT,
    DETAIL_SPECIFIC,
    DETAIL_DETAILED,
]

# ──────────────────────────── 各級別範本 ────────────────────────────
TEMPLATES: dict[str, list[str]] = {
    DETAIL_MINIMAL: [
        "{tone}幫我把這些{theme}的影片剪成一支短片",
        "{tone}{theme}的素材幫我剪一下",
        "{tone}這批{theme}的片段幫我湊成一支短影音",
    ],
    DETAIL_LIGHT: [
        "{tone}幫我把{theme}的影片剪成適合{platform}的短片，{scenario}",
        "{tone}想用這些{theme}的素材做一支短影音放到{platform}，{scenario}",
        "{tone}幫我把{theme}的片段剪得順一點，{scenario}就好",
    ],
    DETAIL_SPECIFIC: [
        "{tone}想把{theme}的片段剪成{duration}的短影音，走{style}，配{music}的音樂",
        "{tone}幫我把這些{theme}素材剪成{duration}、{style}的影片，音樂用{music}的",
        "{tone}這批{theme}的影片幫我做成{duration}短片，風格{style}，節奏配{music}",
    ],
    DETAIL_DETAILED: [
        "{tone}這批{theme}的素材順序是亂的，幫我重新排好剪成{duration}的短片："
        "開頭放{hook}，整體走{style}，配{music}音樂，畫質差或晃動的請剔除，最後{scenario}",
        "{tone}幫我把{theme}的片段剪成{duration}、適合{platform}的成品："
        "先用{hook}開場，色調走{style}，音樂{music}，轉場順一點，{scenario}",
        "{tone}想要一支{duration}的{theme}短影音：用{hook}當開頭，{style}風格，"
        "{music}配樂，把重複的片段拿掉，{scenario}",
    ],
}

# scope 專屬模板：依素材組聚焦度併入既有四級詳細度（focused=單一主體多角度；broad=多場景敘事）
SCOPE_TEMPLATES: dict[str, dict[str, list[str]]] = {
    SCOPE_FOCUSED: {
        DETAIL_LIGHT: [
            "{tone}幫我把這些{theme}的鏡頭剪成一支聚焦的短片，多放幾個{subject}的角度，{scenario}",
        ],
        DETAIL_SPECIFIC: [
            "{tone}這些都是{theme}的素材，幫我剪成{duration}的特寫短片，主角就是它，風格{style}、配{music}音樂",
        ],
        DETAIL_DETAILED: [
            "{tone}全部都是{theme}，幫我挑最好看的幾顆剪成{duration}：用{hook}開場，"
            "多放不同角度的{subject}特寫，{style}風格、{music}配樂，重複或晃動的剔除，{scenario}",
        ],
    },
    SCOPE_BROAD: {
        DETAIL_LIGHT: [
            "{tone}這批{theme}有好幾個場景，幫我串成一支有故事感的短片放到{platform}，{scenario}",
        ],
        DETAIL_SPECIFIC: [
            "{tone}{theme}的素材場景很雜，幫我排成{duration}的短片，走{style}、配{music}，場景之間轉場要順",
        ],
        DETAIL_DETAILED: [
            "{tone}{theme}的素材是不同場景、順序也亂，幫我重排成{duration}有起承轉合的一支："
            "{hook}開場，{style}風格、{music}配樂，把重複的拿掉，{scenario}",
        ],
    },
}

# ──────────────────────────── 通用詞庫（跨主題）────────────────────────────
DURATION_CHOICES: list[str] = ["15 秒", "30 秒", "45 秒左右", "一分鐘以內"]
STYLE_CHOICES: list[str] = [
    "電影感調色",
    "清新明亮的風格",
    "復古濾鏡",
    "日系小清新",
    "高對比的質感",
]
MUSIC_CHOICES: list[str] = ["輕快", "抒情", "熱血", "Lo-fi 慵懶", "節奏感強"]
PLATFORM_CHOICES: list[str] = ["IG Reels", "TikTok", "YouTube Shorts"]

# 語氣：(標記, 句首前綴)；前綴可為空字串（隨興）
TONE_CHOICES: list[tuple[str, str]] = [
    ("隨興", ""),
    ("禮貌", "麻煩你，"),
    ("急迫", "趕時間，"),
    ("興奮", "超期待這支成品！"),
]

# 情境：(標記, 句中用語)
SCENARIO_CHOICES: list[tuple[str, str]] = [
    ("發限動", "要發 IG 限動"),
    ("紀念", "想留個紀念"),
    ("分享朋友", "想分享給朋友"),
    ("投稿", "要拿去投稿"),
]

# ──────────────────────────── 各主題專屬詞庫 ────────────────────────────
# key 須與設定檔的 group.theme 完全一致；找不到時改用 generic_lexicon。
THEME_LEXICONS: dict[str, dict[str, list[str]]] = {
    "海邊一日遊": {
        "subjects": ["海浪", "夕陽", "踏浪的畫面", "沙灘散步", "海邊的剪影"],
        "hooks": ["最美的那顆夕陽", "海浪拍上岸的瞬間", "跳進海裡的那一刻"],
    },
    "咖啡廳": {
        "subjects": ["拉花特寫", "咖啡杯", "慵懶的午後", "窗邊的光", "翻書的手"],
        "hooks": ["拉花完成的瞬間", "咖啡倒進杯子的特寫", "陽光灑進來的畫面"],
    },
    "城市散步": {
        "subjects": ["街頭人潮", "霓虹招牌", "斑馬線", "櫥窗", "地鐵站"],
        "hooks": ["紅綠燈轉換的瞬間", "霓虹燈亮起來的畫面", "人潮川流的縮時"],
    },
    "美食": {
        "subjects": ["食物特寫", "熱氣騰騰的畫面", "精緻擺盤", "夾起來的瞬間", "醬汁淋上去"],
        "hooks": ["起司牽絲的瞬間", "熱氣冒出來的特寫", "咬下去的那一口"],
    },
    "寵物": {
        "subjects": ["貓咪打呵欠", "狗狗奔跑", "玩玩具的樣子", "睡覺的模樣", "歪頭看鏡頭"],
        "hooks": ["飛撲過來的瞬間", "歪頭看鏡頭的畫面", "打呵欠的特寫"],
    },
    # ── v2 新增（含多樣 broad 與聚焦 focused 主題）──
    "東京一日遊": {
        "subjects": ["澀谷路口", "電車進站", "街邊小吃", "神社鳥居", "霓虹街景", "藥妝店"],
        "hooks": ["澀谷路口人潮過馬路", "電車呼嘯而過的瞬間", "鳥居前的畫面"],
    },
    "城市夜散步": {
        "subjects": ["霓虹招牌", "車流光軌", "櫥窗", "夜市攤位", "天橋上的視角"],
        "hooks": ["霓虹燈亮起來的瞬間", "車流光軌縮時", "抬頭看招牌的畫面"],
    },
    "特調飲料": {
        "subjects": ["飲料特寫", "倒飲料的瞬間", "冰塊落下", "吸管攪拌", "氣泡上升", "杯壁的水珠"],
        "hooks": ["飲料倒進杯子的慢動作", "冰塊落入的瞬間", "氣泡往上冒的特寫"],
    },
    "拉花咖啡": {
        "subjects": ["拉花特寫", "奶泡倒入", "咖啡表面的紋路", "端起咖啡杯", "蒸氣升起"],
        "hooks": ["拉花完成的瞬間", "奶泡倒入畫出葉子", "蒸氣升起的特寫"],
    },
    "貓咪日常": {
        "subjects": ["貓咪特寫", "貓咪舔毛", "貓咪伸懶腰", "肉球", "尾巴擺動", "打呵欠"],
        "hooks": ["歪頭看鏡頭的畫面", "打呵欠的特寫", "伸懶腰的瞬間"],
    },
}


def generic_lexicon(theme: str) -> dict[str, list[str]]:
    """為未收錄的主題產生通用詞庫（以主題字串本身填空，仍切合主題）。"""
    return {
        "subjects": [theme, f"{theme}的畫面", f"{theme}的精彩片段"],
        "hooks": ["最有感覺的那一幕", "最精彩的片段", f"{theme}最吸睛的畫面"],
    }
