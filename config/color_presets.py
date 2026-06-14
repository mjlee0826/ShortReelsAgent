"""
調色 (color grading) 設定的後端讀取層 (Configuration Object Pattern)。

唯一事實來源 (SSOT) 是 ``frontend/src/config/colorPresets.json``：renderer (前端 utils/color.js)、
Inspector、後端 schema (``prompt_manager.schemas``) 與導演 prompt 四方共讀**同一份檔**，從根拔除
「濾鏡名稱手抄四處」的飄移 (對應 docs/editing_capability_roadmap.md 方向三)。

之所以由後端反向讀取前端目錄下的 JSON：方向三採『前端 render-time 解析』(Q1=A)，前端是逐幀解析的
主消費者，JSON 放 frontend/src 讓 Vite 預覽與 Remotion SSR 都能原生 import、零打包風險；後端只需
唯讀取用 (產 schema enum + prompt 詞彙)，故以路徑反查同一份檔，封裝在本模組成為單一乾淨接縫。
"""
import json
import os

# ── JSON 結構鍵名 (集中具名，避免 magic string 散落各處) ──────────────────────────
_KEY_PRIMITIVES = "primitives"   # 最小可調旋鈕定義 (含 CSS 函式名 / 範圍 / 預設 / 標籤)
_KEY_PRESETS = "presets"         # 命名預設：一包 primitive 數值 (純資料)
_KEY_PRESET_LABELS = "presetLabels"  # preset → 中文標籤 (僅 UI / prompt 顯示用)
_KEY_MIN = "min"
_KEY_MAX = "max"
_KEY_DEFAULT = "default"
_KEY_LABEL = "label"
_KEY_UNIT = "unit"

# ── SSOT 檔路徑：由本檔位置 (<repo>/config/color_presets.py) 反推 repo root，再指向前端 JSON ──
# 手法同 backend/services/remotion_adapter.py：以 __file__ 定位，避免相依當下工作目錄 (CWD)。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COLOR_PRESETS_JSON_PATH = os.path.join(
    _REPO_ROOT, "frontend", "src", "config", "colorPresets.json"
)


def load_color_config() -> dict:
    """
    讀取並解析調色 SSOT JSON，回傳完整設定 dict (含 primitives / presets / presetLabels)。

    找不到檔或格式錯誤時 raise 明確例外 (調色詞彙是 schema 與 prompt 的硬相依，靜默退化只會讓
    導演拿到空清單而產出怪輸出，故寧可在啟動時大聲失敗)。
    """
    try:
        with open(_COLOR_PRESETS_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"找不到調色 SSOT 設定檔：{_COLOR_PRESETS_JSON_PATH}"
            "（方向三：renderer 與後端共讀此檔，請確認 frontend/src/config/colorPresets.json 存在）"
        ) from exc


# ── 模組層載入一次：供 schema 在 class 定義期取用 (動態建 enum / 取數值範圍) ────────────
COLOR_CONFIG = load_color_config()
COLOR_PRIMITIVES = COLOR_CONFIG[_KEY_PRIMITIVES]
COLOR_PRESETS = COLOR_CONFIG[_KEY_PRESETS]
COLOR_PRESET_LABELS = COLOR_CONFIG[_KEY_PRESET_LABELS]
# preset 名稱清單 (供 schema 動態建 ColorPreset enum；順序即 JSON 定義順序)
COLOR_PRESET_NAMES = list(COLOR_PRESETS.keys())
# primitive 名稱清單 (供 schema 逐顆宣告覆寫欄位 / Inspector 逐顆產滑桿)
COLOR_PRIMITIVE_NAMES = list(COLOR_PRIMITIVES.keys())


def primitive_range(name: str) -> tuple[float, float]:
    """
    回傳某 primitive 的 (min, max) 合法範圍，供 schema 以 ``Field(ge=, le=)`` 約束數值。

    範圍同源於 SSOT JSON，故 schema 驗證邊界與 Inspector 滑桿邊界永遠一致、不會飄移。
    """
    meta = COLOR_PRIMITIVES[name]
    return meta[_KEY_MIN], meta[_KEY_MAX]


def color_vocabulary_text() -> str:
    """
    把 presets 與 primitives 自動序列化成給導演 LLM 看的中文清單字串 (取代手寫 enum 詞彙)。

    只產『事實清單』(有哪些 preset、各包含什麼旋鈕、各 primitive 的範圍)；心法框架 (何時用、
    一致性原則) 留給 ``default_prompt_manager`` 包覆，維持「config 出事實、prompt 出心法」分工。
    新增 preset / primitive 後本函式自動帶到 prompt，無需手改。
    """
    # preset 清單：每筆列出中文標籤 + 該 preset 的非預設旋鈕 gist (讓導演約略知道長相)
    preset_lines = []
    for name in COLOR_PRESET_NAMES:
        label = COLOR_PRESET_LABELS.get(name, name)
        knobs = COLOR_PRESETS.get(name, {})
        gist = "、".join(f"{k} {v}" for k, v in knobs.items()) or "原樣不調"
        preset_lines.append(f"  - {name}（{label}：{gist}）")

    # primitive 清單：每顆列出中文標籤與允許範圍 (含單位)
    primitive_lines = []
    for name, meta in COLOR_PRIMITIVES.items():
        unit = meta.get(_KEY_UNIT, "")
        primitive_lines.append(
            f"  - {name} {meta.get(_KEY_LABEL, '')}"
            f"（{meta[_KEY_MIN]}~{meta[_KEY_MAX]}{unit}，預設 {meta[_KEY_DEFAULT]}{unit}）"
        )

    return (
        "可用調色 preset（先選一個 preset 當整支基調）：\n"
        + "\n".join(preset_lines)
        + "\n可微調的 primitive（選定 preset 後，可覆寫個別旋鈕做精修）：\n"
        + "\n".join(primitive_lines)
    )
