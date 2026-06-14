"""手寫的繁體中文 prompt 範本庫與各主題詞庫（多樣性來源）。

設計目標（對應 docs 的多樣性軸）：
- **詳細度**：minimal（「幫我剪一下」）→ light（帶平台/情境）→ specific（指定時長/風格/音樂）
  → detailed（多項具體要求，並提到素材是亂序、要剔除壞片）。
- **語氣**：隨興／禮貌／急迫／興奮。
- **情境**：發限動／紀念／分享朋友／投稿。
- **字幕**：none（未提及）／add（要字幕/字卡/標題）／no_subtitle（明確不要）。素材為無對白 stock 片，
  故「字幕」指畫面上的文字／字卡／標題，而非語音轉字幕。

範本以 ``str.format`` 佔位符填入：``{theme} {subject} {hook} {duration} {style} {music}
{platform} {scenario} {tone} {caption}``。未列入 ``THEME_LEXICONS`` 的主題會用 ``generic_lexicon`` 以
主題字串本身填空，確保 prompt 仍切合主題。
"""
from __future__ import annotations

from ..constants import (
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_MEDIUM,
    SCOPE_BROAD,
    SCOPE_FOCUSED,
)

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

# 詳細度 → Prompt 難度（U 型）：兩端都難、中間易。
# - minimal：欠規格、需 agent 自行推斷意圖 → hard
# - light：帶平台/情境的輕量指示 → easy
# - specific：指定時長/風格/音樂等具體但有限 → medium
# - detailed：多項約束要同時滿足（重排/剔除/開場/調色…）→ hard
DETAIL_TO_PROMPT_DIFFICULTY: dict[str, str] = {
    DETAIL_MINIMAL: DIFFICULTY_HARD,
    DETAIL_LIGHT: DIFFICULTY_EASY,
    DETAIL_SPECIFIC: DIFFICULTY_MEDIUM,
    DETAIL_DETAILED: DIFFICULTY_HARD,
}

# ──────────────────────────── 各級別範本 ────────────────────────────
TEMPLATES: dict[str, list[str]] = {
    DETAIL_MINIMAL: [
        "{tone}幫我把這些{theme}的影片剪成一支短片",
        "{tone}{theme}的素材幫我剪一下",
        "{tone}這批{theme}的片段幫我湊成一支短影音",
        "{tone}這些{theme}的影片幫我隨便剪成一支就好",
        "{tone}{theme}的片段，幫我快速做成一支短影音",
    ],
    DETAIL_LIGHT: [
        "{tone}幫我把{theme}的影片剪成適合{platform}的短片，{scenario}",
        "{tone}想用這些{theme}的素材做一支短影音放到{platform}，{scenario}",
        "{tone}幫我把{theme}的片段剪得順一點，{scenario}就好",
        "{tone}幫我把{theme}的素材剪成一支短片放{platform}，{scenario}，順順的就好",
        "{tone}這些{theme}想做成短影音貼到{platform}，{scenario}",
    ],
    DETAIL_SPECIFIC: [
        "{tone}想把{theme}的片段剪成{duration}的短影音，走{style}，配{music}的音樂",
        "{tone}幫我把這些{theme}素材剪成{duration}、{style}的影片，音樂用{music}的",
        "{tone}這批{theme}的影片幫我做成{duration}短片，風格{style}，節奏配{music}",
        "{tone}幫我把{theme}剪成{duration}、走{style}的短片，配{music}的音樂，給{platform}用",
        "{tone}這批{theme}想剪成{duration}短影音：{style}風格、{music}配樂",
    ],
    DETAIL_DETAILED: [
        "{tone}這批{theme}的素材順序是亂的，幫我重新排好剪成{duration}的短片："
        "開頭放{hook}，整體走{style}，配{music}音樂，畫質差或晃動的請剔除，最後{scenario}",
        "{tone}幫我把{theme}的片段剪成{duration}、適合{platform}的成品："
        "先用{hook}開場，色調走{style}，音樂{music}，轉場順一點，{scenario}",
        "{tone}想要一支{duration}的{theme}短影音：用{hook}當開頭，{style}風格，"
        "{music}配樂，把重複的片段拿掉，{scenario}",
        "{tone}{theme}的素材有點亂，幫我剪成{duration}適合{platform}的成品："
        "{hook}開場、{style}調色、{music}配樂，模糊或重複的拿掉，{scenario}",
    ],
}

# scope 專屬模板：依素材組聚焦度併入既有四級詳細度（focused=單一主體多角度；broad=多場景敘事）
SCOPE_TEMPLATES: dict[str, dict[str, list[str]]] = {
    SCOPE_FOCUSED: {
        DETAIL_LIGHT: [
            "{tone}幫我把這些{theme}的鏡頭剪成一支聚焦的短片，多放幾個{subject}的角度，{scenario}",
            "{tone}這些都是{theme}，幫我挑幾顆{subject}剪成一支特寫短片放{platform}，{scenario}",
        ],
        DETAIL_SPECIFIC: [
            "{tone}這些都是{theme}的素材，幫我剪成{duration}的特寫短片，主角就是它，風格{style}、配{music}音樂",
            "{tone}全部是{theme}，幫我剪成{duration}的單品短片：多給{subject}的特寫，{style}、配{music}",
        ],
        DETAIL_DETAILED: [
            "{tone}全部都是{theme}，幫我挑最好看的幾顆剪成{duration}：用{hook}開場，"
            "多放不同角度的{subject}特寫，{style}風格、{music}配樂，重複或晃動的剔除，{scenario}",
            "{tone}這支主角只有{theme}：用{hook}開場，{subject}的特寫換不同角度排出節奏，"
            "剪成{duration}、{style}、配{music}，糊掉或重複的拿掉，{scenario}",
        ],
    },
    SCOPE_BROAD: {
        DETAIL_LIGHT: [
            "{tone}這批{theme}有好幾個場景，幫我串成一支有故事感的短片放到{platform}，{scenario}",
            "{tone}{theme}場景蠻多的，幫我串成一支順順的短片放{platform}，{scenario}",
        ],
        DETAIL_SPECIFIC: [
            "{tone}{theme}的素材場景很雜，幫我排成{duration}的短片，走{style}、配{music}，場景之間轉場要順",
            "{tone}{theme}有不同場景，幫我排成{duration}有節奏的一支：{style}、配{music}，從{hook}帶出整段",
        ],
        DETAIL_DETAILED: [
            "{tone}{theme}的素材是不同場景、順序也亂，幫我重排成{duration}有起承轉合的一支："
            "{hook}開場，{style}風格、{music}配樂，把重複的拿掉，{scenario}",
            "{tone}{theme}橫跨好幾個場景又是亂序，幫我重排成{duration}的一支：用{hook}開場帶氣氛，"
            "場景之間轉場順一點，{style}、配{music}，畫質差的剔除，{scenario}",
        ],
    },
}

# ──────────────────────────── 字幕（字卡／畫面文字）範本 ────────────────────────────
# 正面：要求加字幕／字卡。僅 specific 與 detailed 兩級（字幕屬具體要求，不放在極簡級）。
# ``{caption}`` 由 CAPTION_CHOICES 填入具體字幕要求。
CAPTION_TEMPLATES: dict[str, list[str]] = {
    DETAIL_SPECIFIC: [
        "{tone}幫我把{theme}剪成{duration}的短片，{caption}，配{music}的音樂",
        "{tone}這批{theme}剪成{duration}、走{style}的短影音，記得{caption}",
        "{tone}幫我把{theme}做成{duration}的短片放{platform}，{caption}",
    ],
    DETAIL_DETAILED: [
        "{tone}這批{theme}的素材順序是亂的，幫我重排成{duration}的短片：開頭放{hook}，{caption}，"
        "整體走{style}、配{music}音樂，畫質差的剔除，{scenario}",
        "{tone}幫我把{theme}剪成{duration}適合{platform}的成品：{hook}開場、{style}調色、{music}配樂，"
        "{caption}，重複的拿掉，{scenario}",
        "{tone}想要一支{duration}的{theme}短影音：用{hook}當開頭，{caption}，{style}風格、{music}配樂，{scenario}",
    ],
}

# 負面：明確不要任何字幕／畫面文字（eval 的控制組，測 agent 會不會該不加時亂加）。
CAPTION_NEGATIVE_TEMPLATES: dict[str, list[str]] = {
    DETAIL_SPECIFIC: [
        "{tone}幫我把{theme}剪成{duration}的短片，走{style}、配{music}，不要加任何字幕，純畫面就好",
        "{tone}這批{theme}做成{duration}的短影音放{platform}，{style}、配{music}，全程不要字幕或文字",
    ],
    DETAIL_DETAILED: [
        "{tone}這批{theme}是亂序的，幫我重排成{duration}的成品：{hook}開場、{style}調色、{music}配樂，"
        "整支都不要字幕或畫面文字，乾淨一點，{scenario}",
        "{tone}幫我把{theme}剪成{duration}適合{platform}的成品：{hook}開場、{style}、{music}配樂，"
        "不要任何字幕純靠畫面，重複的拿掉，{scenario}",
    ],
}

# ──────────────────────────── 通用詞庫（跨主題）────────────────────────────
DURATION_CHOICES: list[str] = ["15 秒", "20 秒", "30 秒", "40 秒", "45 秒左右", "一分鐘以內", "一分鐘左右"]
# 字幕的具體要求（填入 CAPTION_TEMPLATES 的 {caption}）：涵蓋位置、大小、配色、字卡、關鍵字
CAPTION_CHOICES: list[str] = [
    "幫每段配上說明字幕",
    "重點的地方打上字幕",
    "幫我加字幕、放在畫面下方",
    "字幕記得大一點、白字黑邊",
    "開頭打一張標題字卡",
    "把關鍵字打在畫面上",
    "幫我上字幕，字體再大一點",
    "重要的句子用字卡帶出來",
]
STYLE_CHOICES: list[str] = [
    "電影感調色",
    "清新明亮的風格",
    "復古濾鏡",
    "日系小清新",
    "高對比的質感",
    "暖色底片感",
    "黑白質感",
    "Vlog 手持感",
    "ins 風淡雅",
    "賽博龐克霓虹",
]
MUSIC_CHOICES: list[str] = [
    "輕快",
    "抒情",
    "熱血",
    "Lo-fi 慵懶",
    "節奏感強",
    "chill 電子",
    "鋼琴純音樂",
    "city pop",
    "輕快口哨",
]
PLATFORM_CHOICES: list[str] = ["IG Reels", "TikTok", "YouTube Shorts", "小紅書", "Facebook Reels"]

# 語氣：(標記, 句首前綴)；前綴可為空字串（隨興）
TONE_CHOICES: list[tuple[str, str]] = [
    ("隨興", ""),
    ("禮貌", "麻煩你，"),
    ("急迫", "趕時間，"),
    ("興奮", "超期待這支成品！"),
    ("猶豫", "其實我不太確定，"),
    ("專業", "依品牌調性，"),
]

# 情境：(標記, 句中用語)
SCENARIO_CHOICES: list[tuple[str, str]] = [
    ("發限動", "要發 IG 限動"),
    ("紀念", "想留個紀念"),
    ("分享朋友", "想分享給朋友"),
    ("投稿", "要拿去投稿"),
    ("品牌宣傳", "要當品牌宣傳"),
    ("回顧", "想做個回顧"),
    ("開箱", "要配開箱片"),
]

# ──────────────────────────── 各主題專屬詞庫 ────────────────────────────
# key 須與設定檔的 group.theme 完全一致；找不到時改用 generic_lexicon。
THEME_LEXICONS: dict[str, dict[str, list[str]]] = {
    "海邊一日遊": {
        "subjects": [
            "海浪", "夕陽沙灘", "衝浪的身影", "棕櫚樹", "沙灘陽傘",
            "浮潛看珊瑚", "沙上的腳印", "海邊懸崖", "沙灘排球", "海邊喝椰子",
        ],
        "hooks": [
            "最美的那顆夕陽", "海浪拍上岸的瞬間", "衝上浪頭的那一刻",
            "腳印延伸到海平面的畫面", "陽光灑在浪花上的特寫",
        ],
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
    # 「日本旅遊」放寬地理範圍：可含東京/京都/大阪/北海道/富士山等跨地標誌性素材
    "日本旅遊": {
        "subjects": [
            "壽司", "拉麵", "東京鐵塔", "淺草寺鳥居", "澀谷路口", "富士山",
            "京都老街", "新幹線", "櫻花", "北海道雪景", "大阪夜景", "街邊小吃",
        ],
        "hooks": [
            "澀谷路口人潮過馬路", "新幹線呼嘯而過的瞬間", "鳥居前的畫面",
            "富士山映入眼簾的那一刻", "櫻花飄落的特寫",
        ],
    },
    "城市夜散步": {
        "subjects": [
            "霓虹招牌", "車流光軌", "夜市攤位", "夜間斑馬線", "高樓夜景",
            "雨夜倒影", "居酒屋小巷", "地鐵站", "頂樓視角", "街邊燒烤",
        ],
        "hooks": [
            "霓虹燈亮起來的瞬間", "車流光軌縮時", "抬頭看招牌的畫面",
            "雨後街面倒映霓虹的畫面", "夜市第一攤冒出熱氣的瞬間",
        ],
    },
    "特調飲料": {
        "subjects": [
            "倒冰咖啡", "調酒特寫", "珍珠奶茶", "汽水濺起", "抹茶拿鐵",
            "冰塊落下", "柑橘裝飾", "果昔倒入", "杯壁的水珠", "吸管攪拌",
        ],
        "hooks": ["飲料倒進杯子的慢動作", "冰塊落入的瞬間", "氣泡往上冒的特寫"],
    },
    "拉花咖啡": {
        "subjects": [
            "拉花注入", "濃縮萃取", "奶泡葉形", "咖啡油脂", "填壓粉餅",
            "蒸奶鋼杯", "俯拍拉花", "磨豆機",
        ],
        "hooks": ["拉花完成的瞬間", "奶泡倒入畫出葉子", "濃縮滴落的特寫"],
    },
    "貓咪日常": {
        "subjects": [
            "貓咪特寫", "小貓玩耍", "打呵欠", "肉球", "伸懶腰",
            "尾巴擺動", "舔毛理毛", "盯著鏡頭", "蜷著睡覺",
        ],
        "hooks": ["歪頭看鏡頭的畫面", "打呵欠的特寫", "伸懶腰的瞬間"],
    },
    # ── v3 新增（3 broad 多場景 + 3 focused 單一主體）──
    "健行登山": {
        "subjects": [
            "登山步道", "攻頂日出", "雲海", "森林小徑", "高山湖泊",
            "岩稜線", "登山鞋特寫", "登山背包", "森林瀑布", "高山野花",
        ],
        "hooks": ["登頂看到雲海的瞬間", "陽光穿過樹林的畫面", "回頭俯瞰整片山谷"],
    },
    "居家料理": {
        "subjects": [
            "切菜特寫", "爆炒的鑊氣", "煮義大利麵", "擺盤完成", "煎牛排滋滋作響",
            "揉麵團", "淋上醬汁", "新鮮食材", "撒上香草", "刀工切片",
        ],
        "hooks": ["食材下鍋爆香的瞬間", "起鍋擺盤的特寫", "熱氣冒出來的畫面"],
    },
    "健身房日常": {
        "subjects": [
            "硬舉", "深蹲架", "跑步機", "啞鈴彎舉", "戰繩",
            "壺鈴擺盪", "汗水特寫", "划船機", "伸展", "引體向上",
        ],
        "hooks": ["槓鈴舉起的瞬間", "汗水滴下的特寫", "完成最後一組的瞬間"],
    },
    "烘焙甜點": {
        "subjects": [
            "蛋糕裝飾", "擠鮮奶油", "進爐烘烤", "撒糖粉", "巧克力甘納許",
            "切開夾層蛋糕", "草莓塔", "餅乾麵團", "馬卡龍",
        ],
        "hooks": ["蛋糕出爐的瞬間", "糖粉灑下的畫面", "巧克力淋上的特寫"],
    },
    "多肉植物": {
        "subjects": [
            "多肉特寫", "整排盆栽", "澆水的水珠", "換盆的雙手", "仙人掌微距",
            "窗台植栽", "陶土花盆", "葉片紋理", "扦插的葉片",
        ],
        "hooks": ["水珠滑過葉片的瞬間", "陽光灑在多肉上的畫面", "整排盆栽的俯視"],
    },
    "水族箱": {
        "subjects": [
            "熱帶魚游動", "水草搖曳", "氣泡上升", "餵食的瞬間", "小丑魚特寫",
            "光線穿過水面", "珊瑚缸", "魚群轉向", "玻璃上的螺",
        ],
        "hooks": ["魚群轉向的瞬間", "氣泡上升的特寫", "光線穿過水草的畫面"],
    },
}


def generic_lexicon(theme: str) -> dict[str, list[str]]:
    """為未收錄的主題產生通用詞庫（以主題字串本身填空，仍切合主題）。"""
    return {
        "subjects": [theme, f"{theme}的畫面", f"{theme}的精彩片段"],
        "hooks": ["最有感覺的那一幕", "最精彩的片段", f"{theme}最吸睛的畫面"],
    }
