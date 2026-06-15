"""
極輕素材目錄 + 欄位 manifest + 批次 ``get_fields`` 投影（混合式看 metadata 的核心）。

設計（決策 4）：上層目錄只給導演極輕資訊（id + type + 一行摘要），全部素材常駐但省 token；
其餘所有欄位列在「欄位 manifest」並按需用 ``get_fields(ids, fields)`` 批次投影。manifest 的每筆
``desc`` 同時承載「何時該讀此欄位」的引導（取代分風格 Skill 的角色）。

資料來源：``ContextCompressor.compress()`` 已產出的完整 dossier（loop 以 id 建成 asset_index），
本模組只做「投影 / 摘要」，零新解析。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from config.director_config import DIRECTOR_GET_FIELDS_MAX_IDS

# 摘要最長字數（避免複雜影片的事件摘要把「極輕目錄」撐大）
_SUMMARY_MAX_CHARS = 160


class FieldManifestEntry(BaseModel):
    """欄位 manifest 的單筆：欄位名、給導演看的說明（含何時該讀）、是否為重欄位。"""
    name: str = Field(description="get_fields 可請求的欄位名")
    desc: str = Field(description="此欄位是什麼 + 何時該讀")
    heavy: bool = Field(default=False, description="是否為重欄位（長文 / 大陣列，省著讀）")


# 欄位 manifest（SSOT）：對齊 ``ContextCompressor.compress()`` 的 dossier 鍵。
# 不列 id / type / cap —— 那三項已在極輕目錄常駐（cap 即摘要來源）。
FIELD_MANIFEST: list[FieldManifestEntry] = [
    FieldManifestEntry(name="aes", desc="美學分(0~100)。挑畫面好不好看、選材排序時讀。"),
    FieldManifestEntry(name="tech", desc="技術畫質分。怕素材糊 / 抖 / 曝光差時讀。"),
    FieldManifestEntry(name="mood", desc="情緒(energetic/calm/...)。編排情緒弧線時讀。"),
    FieldManifestEntry(name="scene_tags", desc="場景標籤。確保相鄰片段場景有變化時讀。"),
    FieldManifestEntry(name="actions", desc="動作標籤。需要動作多樣性 / 對應使用者主題時讀。"),
    FieldManifestEntry(name="cam", desc="鏡頭視角(close-up/wide/...)。排鏡頭語言時讀。"),
    FieldManifestEntry(name="tod", desc="時段(golden_hour/day/night/...)。"),
    FieldManifestEntry(name="crop", desc="9:16 可裁性(full/not_recommended/...)。決定能否直接用此素材。"),
    FieldManifestEntry(name="bbox", desc="最佳主體框{x1,y1,x2,y2}(0~100)。算 object_position 裁切定位必讀。"),
    FieldManifestEntry(name="subjects", desc="候選主體清單(label/conf/bbox)。想改用畫面中另一個主體時讀。", heavy=True),
    FieldManifestEntry(name="face_count", desc="臉數。判斷是否人物特寫。"),
    FieldManifestEntry(name="face_ratio", desc="最大臉佔比(越大越特寫)。"),
    FieldManifestEntry(name="bright", desc="亮度。"),
    FieldManifestEntry(name="color_temp", desc="色溫(warm/cool/neutral)。配色 / 調色一致時讀。"),
    FieldManifestEntry(name="colors", desc="主色清單。"),
    FieldManifestEntry(name="res", desc="解析度{w,h}。"),
    FieldManifestEntry(name="time", desc="拍攝時間。"),
    FieldManifestEntry(name="geo", desc="拍攝地點 GPS。"),
    FieldManifestEntry(name="critique", desc="攝影評論(光影/構圖/情緒的深度描述)。兩個視覺相近素材二選一時讀。", heavy=True),
    # ── 影片專屬 ──────────────────────────────────────────────────────────────
    FieldManifestEntry(name="dur", desc="影片時長(秒)。排時間軸 / 變速前必讀。"),
    FieldManifestEntry(name="fps", desc="影片幀率。"),
    FieldManifestEntry(name="motion", desc="動態強度。高能段選動態大的素材時讀。"),
    FieldManifestEntry(name="has_speech", desc="是否有人聲。決定是否需要對白字幕 / ducking。"),
    FieldManifestEntry(name="lang", desc="人聲語言代碼。"),
    FieldManifestEntry(name="cuts", desc="場景切點秒數清單。在影片內找乾淨剪輯點時讀。"),
    FieldManifestEntry(name="transcript", desc="逐字稿(text + 帶時間戳 chunks + language)。對齊對白字幕 / BGM 避讓必讀。", heavy=True),
    FieldManifestEntry(name="env", desc="主要環境音清單。"),
    FieldManifestEntry(name="events", desc="複雜影片逐段視聽事件索引(含時間戳 / 主體框 / 視聽層)。精修複雜影片切點時讀。", heavy=True),
    FieldManifestEntry(name="is_complex", desc="是否為複雜(密集索引)影片。"),
]

# manifest 合法欄位名集合（get_fields 驗證用）
_MANIFEST_NAMES = {entry.name for entry in FIELD_MANIFEST}


def build_manifest_text() -> str:
    """把欄位 manifest 渲染成精簡文字（放進首則 prompt，讓導演知道有哪些欄位可 get_fields）。"""
    lines = ["可用 get_fields 取得的欄位（標 [heavy] 者為長文 / 大陣列，省著讀）："]
    for entry in FIELD_MANIFEST:
        tag = " [heavy]" if entry.heavy else ""
        lines.append(f"- {entry.name}{tag}：{entry.desc}")
    return "\n".join(lines)


def _summarize(dossier: dict) -> str:
    """取一行摘要：優先用 caption；空則用複雜影片的事件視覺摘要；皆無回空字串。"""
    cap = (dossier.get("cap") or "").strip()
    if cap:
        return cap[:_SUMMARY_MAX_CHARS]
    events = dossier.get("events") or []
    digest = " / ".join(e.get("visual_layer", "") for e in events if e.get("visual_layer"))
    return digest[:_SUMMARY_MAX_CHARS]


def build_catalog(compressed_assets: list[dict]) -> list[dict]:
    """
    從完整 dossier 清單投影出「極輕目錄」：每素材只 id + type + 一行摘要。

    這是常駐第一則 user 訊息的全素材清單；刻意極輕以省 token、cache 友善，其餘欄位一律走
    ``get_fields`` 按需取。無 id 者跳過（無法被選回）。
    """
    catalog = []
    for dossier in compressed_assets:
        asset_id = dossier.get("id")
        if not asset_id:
            continue
        catalog.append({
            "id": asset_id,
            "type": dossier.get("type", ""),
            "summary": _summarize(dossier),
        })
    return catalog


def _resolve_field(dossier: dict, name: str) -> Any:
    """投影單一欄位值（處理 transcript / env 的巢狀；其餘為 dossier 頂層鍵）。"""
    if name == "transcript":
        return (dossier.get("audio") or {}).get("transcript")
    if name == "env":
        return (dossier.get("audio") or {}).get("env")
    return dossier.get(name)


def project_fields(
    asset_index: dict[str, dict], asset_ids: list[str], fields: list[str]
) -> tuple[dict, list[str]]:
    """
    批次投影：回 ``({id: {field: value, ...}, ...}, 警告清單)``，只含 manifest 內合法欄位且有值者。

    id 數量上限 ``DIRECTOR_GET_FIELDS_MAX_IDS``（超過截斷並附警告）；未知欄位、查無素材、值為
    None / 空者一律略過以保持 payload 精簡，並把未知欄位 / 查無 id 收進警告供模型自我修正。
    """
    warnings: list[str] = []
    unknown = [f for f in fields if f not in _MANIFEST_NAMES]
    if unknown:
        warnings.append(f"未知欄位(已略過)：{unknown}")
    valid_fields = [f for f in fields if f in _MANIFEST_NAMES]

    ids = asset_ids
    if len(ids) > DIRECTOR_GET_FIELDS_MAX_IDS:
        warnings.append(
            f"一次最多 {DIRECTOR_GET_FIELDS_MAX_IDS} 個 id，已截斷（請分批讀取）。"
        )
        ids = ids[:DIRECTOR_GET_FIELDS_MAX_IDS]

    out: dict = {}
    missing: list[str] = []
    for asset_id in ids:
        dossier = asset_index.get(asset_id)
        if dossier is None:
            missing.append(asset_id)
            continue
        projected = {}
        for field_name in valid_fields:
            val = _resolve_field(dossier, field_name)
            if val is not None and val != [] and val != "":
                projected[field_name] = val
        if projected:
            out[asset_id] = projected
    if missing:
        warnings.append(f"查無素材 id(已略過)：{missing}")
    return out, warnings
