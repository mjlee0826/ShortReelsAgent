# 剪輯能力擴充路線圖：把「會套效果」升級成「精緻 ShortReels」

> 本文件記錄為了剪出更好看、更精緻的 ShortReels，剪輯能力該往哪五個方向擴充。
> 記錄每個方向「要做哪些事 / 技術難度 / 預估工時 / 風險 / 相依關係」。
> 工時為「1 人 + AI 協作、集中作業」概算，`prompt 調校` 與 `視覺 critic` 的「試到有效」部分屬 open-ended，與 coding 工時分開計。
>
> **實作進度**（✅ 已完成 / 🚧 進行中 / ⏸ 暫緩 / ⬜ 未開始；更新於 2026-06-14）：
> - ✅ **#1 精簡版**（變化＋卡點自動運鏡）— 2026-06-13 上線，細節見 §3。
> - ✅ **#2 精簡版**（結構化 `TextOverlay` + 解耦＋可拖曳字幕軌）— 已上線，細節見 §4。**實作交接見 [`docs/text_overlay_track_handoff.md`](text_overlay_track_handoff.md)**。完整版（卡拉OK逐字）未做。
> - ✅ **#3 精簡版**（能力層 primitive + 命名 preset 調色）— 已上線，細節見 §5。完整版（LUT）未做。
> - ⏸ **#4**（決策層 style 約束）暫緩，待之後再做（理由見 §6 狀態註）。
> - ⬜ **#5**（規則 / 視覺 critic）未開始；#1 / #2 / #3 各自的完整版未開始。

---

## 1. 為什麼：「精緻」的瓶頸不在選項數量

一支 reel 好不好看，由三件**互相獨立**的事決定：

| 層 | 負責什麼 | 現況 |
|---|---|---|
| **能力層** | renderer 有哪些表現力（濾鏡 / 字幕 / 動畫） | （起草時）靜態濾鏡 4 種、字幕寫死單一樣式、無動畫概念 →（2026-06 已升級）#1 卡點運鏡、#2 結構化字幕軌、#3 primitive+preset 調色 |
| **決策層** | 導演 LLM 知不知道**何時、怎麼**用得好 | 單一 mega-prompt、選項平行攤開 |
| **品管層** | 系統能不能**看到自己的成品**並修 | 只有結構性 critic（gap / overlap / duration），無美學檢查 |

**直覺作法（加更多濾鏡 + 改 Phase 4 prompt）只動了能力層，但能力層其實最不缺。**

兩個關鍵理由：

1. **靜態濾鏡多寡不是「業餘 vs 專業」的分水嶺**——真正拉開差距的是**動態**（運鏡、字幕動畫、卡點）。給同一顆導演腦袋 20 個濾鏡，它只會亂灑 → 更花，不是更精緻。**「精緻」來自一致與克制，而一致來自約束，不是選項數量。**
2. **3-way drift 會爆炸**——每加一個效果要同時改三處：前端 `FILTER_MAP`（`ClipComponent.jsx`）/ schema Enum（`schemas.py`）/ Phase 4 prompt 詞彙（`default_prompt_manager.py`）。`transition_in: slide` 就是這三處沒對齊的產物（前端下拉有、renderer 與 schema 沒有 → 選了等同無轉場）。濾鏡 / 字幕越加，飄移越多。
   （**註：#3 已把調色這條的 `FILTER_MAP` 換成 `buildCssFilter` + `colorPresets.json` 單一來源，調色的三方飄移已拔除；轉場仍適用此原則。**）

→ 所以該投資的順序是：**先補「會動」與「看得到自己醜在哪」，再把能力層做成可維護、讓決策層風格一致。**

---

## 2. 五個方向總覽

| # | 方向 | 層 | 難度 | 精簡版 | 完整版 |
|---|---|---|---|---|---|
| 1 | Keyframe / 動畫原語 + 卡點運鏡 | 能力 | 中 → 高 | ✅ 已完成 | 2–3 週 ⬜ |
| 2 | 結構化 TextOverlay + 卡拉OK字幕 | 能力 | 中 → 中高 | ✅ 已完成 | 1.5–2 週 ⬜ |
| 3 | 能力層 primitive + 命名 preset | 能力 | 中 | ✅ 已完成 | +LUT ~3 天 ⬜ |
| 4 | 決策層 style preset 約束 LLM | 決策 | 中 → 高 | 3–5 天 + 調校 ⏸ | 1.5–2 週 + 調校 |
| 5 | 品管層 視覺 critic 迴路 | 品管 | 中 → 很高 | 3–5 天（規則） | 3–4 週+（視覺） |

相依關係見 §8。

---

## 3. 方向一：Keyframe / 動畫原語 + 卡點運鏡

> **🟢 實作狀態（2026-06-13）：精簡版已上線。** 變化型自動運鏡（Ken Burns 推近 / 拉遠 / 左右平移、相鄰輪替 + 卡點 punch）、前端「啟用自動運鏡」總開關、逐段「運鏡」覆寫皆已實作。
> 採**務實精簡路線**：未做下方「keyframe 陣列」通用 schema，改在 clip 加 `motion` preset 欄位，由 `frontend/src/utils/motion.js` 於 render-time 依 preset / 節拍算逐幀 transform（純函式、與 fade 同源用 `interpolate`，縮放支點＝主體 `object_position`）。後端把 librosa 既有 beats 注入 `bgm_track`（post-LLM、刻意不入 LLM schema）＋ `global_settings.auto_motion`。
> 檔案：`utils/motion.js`(新)、`RemotionPlayer/ClipComponent.jsx`、`MainTimeline.jsx`、`schemas.py`(`Clip.motion`)、`backend/api/director.py`、`services/director_service.py`、`store/useBlueprintStore.js`、`GenerationForm.jsx`、`Inspector/ClipInspector.jsx`。
> **未做（完整版）**：通用 keyframe schema、Inspector 手動 keyframe 編輯 UI、變速 ramp、動態轉場（含 `slide`）。已知限制：music-only 換曲後暫無 punch（beats 尚未在換曲路徑注入）。

**問題**：現在每個屬性都是**一顆靜態值**（`scale` 一個數、`filter` 一個值）。精緻的 reel 靠**屬性隨時間變化**：Ken Burns 緩慢推軌、字幕彈入、卡節拍的縮放、變速 ramp。架構目前**沒有「屬性在片段內隨時間變化」的概念**。

**會做哪些事**
- **Schema**：把 `scale` / `object_position` / opacity / 色彩參數從「純量」擴成「可填 keyframe 陣列」`[{ t, value, easing }]`（或新增 `animations` 欄位）。
- **Renderer（`ClipComponent.jsx`）**：用 Remotion `interpolate` + `Easing` 把 keyframe 轉成逐幀值——**`transition_in: fade` 已經是這個機制（`interpolate(frame, [0, TRANSITION_FRAMES], [0, 1])`），等於延伸它**。
- **內建動畫 preset**：Ken Burns（緩慢 scale 1.0→1.1 + position 漂移）、彈入、卡點 punch-zoom。
- **卡點**：把 `music_beats`（生成階段「分析配樂節拍」）時間軸接進來，讓動畫關鍵點對齊 beat。
- **（完整版才做）** Inspector 的手動 keyframe 編輯 UI（時間軸上加關鍵幀點、拖曳）← **最難、最耗時**。

**難度**：渲染機制 **中**（已有底子）；完整 keyframe + 編輯 UI **高**。
**工時**
- 精簡版（只開 Ken Burns / beat-sync zoom 等 preset 動畫，**不做手動 keyframe UI**）：**3–5 天** → ✅ **已完成**
- 完整版（通用 keyframe schema + Inspector 拖曳編輯 + easing 曲線）：**2–3 週** ⬜

**風險**：beats 資料管線是否現成可取用、VFR（變動幀率）影片下的時間精度、多屬性逐幀 `interpolate` 的效能。
**相依**：是 #2 字幕動畫的地基（兩者共用同一 keyframe 機制）。

---

## 4. 方向二：結構化 TextOverlay + 卡拉OK字幕

> **🟢 實作狀態（2026-06-14）：精簡版已上線。** `overlay_text` 字串已升級為結構化 `TextOverlay`，且字幕**完全解耦成獨立於片段的字幕軌**（頂層 `text_overlays`，帶絕對 `start_at/end_at`，可跨片段持續顯示、同框可多條）；含時間軸可拖曳 / 拉伸字幕軌（lane-stacking）與 Inspector 樣式編輯。位置用 clamp 夾進 safe-area、字型走 `@remotion/google-fonts`(Noto Sans TC)。
> 檔案：`schemas.py`(`TextOverlay` + `DirectorBlueprint.text_overlays`、移除 `Clip.text_overlay`)、`default_prompt_manager.py`(獨立「字幕心法」段)、`utils/textOverlay.js`(`resolveTimelineTextOverlays`/`migrateBlueprintTextOverlays`/`fillOverlayDefaults`/clamp 定位)、`RemotionPlayer/{TextOverlayLayer,MainTimeline,constants}.jsx`、`Editor/Timeline/{TextBlock,TimelinePanel}.jsx`、`Editor/Inspector/TextOverlayInspector.jsx`、`store/blueprint/{editorSlice,generationSlice,snapshotSlice,history}.js`。**完整交接見 [`docs/text_overlay_track_handoff.md`](text_overlay_track_handoff.md)**。
> **未做（完整版）**：卡拉OK逐字高亮（需 Whisper word-level timestamp + 重跑既有素材感知；現只存句級 chunks）。

**問題**：字幕是「業餘感」最明顯的地方。現在 `overlay_text` 只是一個字串，渲染成寫死的白色 5xl 置中 `div`（`MainTimeline.jsx`）。

**會做哪些事**
- **Schema**：`overlay_text: str` → 結構化 `TextOverlay` 物件（text / 位置 / 字級 / 顏色 / 描邊陰影 / 底框 / 進出場動畫 / 逐字時間）——**照現有 `PipVideo` 巢狀物件（`schemas.py`）的模式抄**。
- **Renderer（`MainTimeline.jsx`）**：把寫死的字幕 `div` 改成讀樣式欄位渲染；進出場動畫**復用 #1 的 keyframe 機制**。
- **卡拉OK逐字**：接 Whisper word-level timestamp（生成階段已有「語音聽寫」），逐字高亮。
- **Safe area**：自動避開 IG / TikTok 上下 UI 遮擋區。
- **字型**：打包字型檔（中文字型尤其大），讓 Remotion 取用得到。
- **Inspector + prompt**：字幕樣式編輯 UI；導演把語音段落映射成字幕內容。

**難度**：樣式化字幕 **中**；卡拉OK逐字 **中–高**（取決於 Whisper word-level timing 有沒有現成存下來）。
**工時**
- 樣式化字幕（位置 / 顏色 / 字級 / 底框 / 進出場，共用 #1）：**3–4 天**
- + 卡拉OK逐字（需 word-timing 管線）：**+4–6 天**
- 合計完整：**~1.5–2 週**

**風險**：中文字型載入 / 打包、word timing 資料是否現成、safe area 定位。
**相依**：進出場動畫依賴 #1 的 keyframe 機制。

---

## 5. 方向三：能力層 primitive + 命名 preset

> **🟢 實作狀態（2026-06-14）：精簡版已上線。** 「寫死濾鏡名 → 固定字串」已重構成 **primitive（最小旋鈕）+ 命名 preset（純資料）**：SSOT 為 `frontend/src/config/colorPresets.json`，renderer / schema / prompt 共讀同一份。新增一個 look＝在 JSON 加一筆（schema enum 動態建、prompt 詞彙由 `color_vocabulary_text()` 自動列、renderer 不動），3-way drift 的根已拔除。blueprint 的 `color` 可「引用 preset + 覆寫個別 primitive」（如 `{preset:"cinematic", brightness:0.8}`），舊 `filter` 字串向後相容。
> 檔案：`frontend/src/config/colorPresets.json`(SSOT)、`config/color_presets.py`(後端唯讀載入 + `color_vocabulary_text()`)、`prompt_manager/schemas.py`(`ColorPreset` 動態 enum + `ClipColor`)、`frontend/src/utils/color.js`(`buildCssFilter`/`resolveColor`/`legacyFilterToColor`)、`RemotionPlayer/ClipComponent.jsx`、`Editor/Inspector/ClipInspector.jsx`、`director_facade.py`(舊 filter→color 相容補完)。
> **未做（完整版）**：LUT / vignette 等非 CSS-filter 效果（漸層 overlay / 色彩查表）。

**問題**：現在「濾鏡」是一個**寫死的名字**對應一條固定字串。想要「電影感但再暗一點」做不到——只能再新增 enum + 同步改三處（renderer / schema / 前端下拉），漏一個就是 `slide` 那種 bug。

```js
// ClipComponent.jsx —— 現況。每加一個 look 就要改這裡
const FILTER_MAP = {
  cinematic: 'contrast(1.1) saturate(0.85) brightness(0.9)',
  grayscale: 'grayscale(1)',
  blur:      'blur(4px)',
  none:      'none',
};
```

**拆成兩個概念**

1. **Primitive（原語）= 最小可調旋鈕，帶數值**：`brightness` / `contrast` / `saturate` / `blur` / `grayscale` / `vignette`…。renderer 只負責**機械式組裝成 CSS**，這個函式**寫一次，以後加再多 look 都不用動**：

```js
// 這個函式永遠不改：它只認得「原語」，不認得「look 的名字」
function buildCssFilter(color) {
  const parts = [];
  if (color.brightness != null) parts.push(`brightness(${color.brightness})`);
  if (color.contrast   != null) parts.push(`contrast(${color.contrast})`);
  if (color.saturate   != null) parts.push(`saturate(${color.saturate})`);
  if (color.blur       != null) parts.push(`blur(${color.blur}px)`);
  if (color.grayscale  != null) parts.push(`grayscale(${color.grayscale})`);
  return parts.join(' ') || 'none';
}
```

2. **Preset（命名預設）= 一包原語數值，而且是「資料」不是「程式」**：

```jsonc
// presets.json —— renderer / schema / prompt 三方都讀這一份（唯一來源）
{
  "cinematic": { "contrast": 1.1, "saturate": 0.85, "brightness": 0.9, "vignette": 0.2 },
  "warm_vlog": { "saturate": 1.15, "brightness": 1.05 },
  "bw_film":   { "grayscale": 1, "contrast": 1.2 }
}
```

於是 blueprint 的 filter 可以「引用 preset + 微調」：

```jsonc
"color": { "preset": "cinematic", "brightness": 0.8 }   // 電影感，但要再暗一點 ← 現在做得到
```

**會做哪些事**
- Schema：`ClipFilter` enum → `color` 物件（primitive 參數 + 可選 preset 引用），用 Pydantic Field 約束數值範圍。
- 建 `presets.json` 單一來源，把現有 cinematic / grayscale / blur 表達成 preset。
- Renderer：`FILTER_MAP` 寫死 → `buildCssFilter()` 組裝 + `resolvePreset()`（preset + override 合併）；vignette / LUT 等非 CSS-filter 的另做（漸層 overlay / 色彩查表）。
- Inspector：下拉（選 preset）+ 進階滑桿（微調 primitive）。
- prompt：從 `presets.json` **自動生成**可用清單給 LLM（取代手寫 enum 詞彙）。
- 向後相容：舊 blueprint 的 `filter: "cinematic"` 要能 fallback 讀進來。

**這買到什麼**：加一個新 look ＝ **加一筆資料**（renderer 不動、schema 只驗範圍、prompt 自動列）→ 從「改 3 個檔、容易漏」變成「改 1 處」，**drift 的根被拔掉**。

**難度**：**中**（概念清楚、檔案小，但碰點多：schema + renderer + inspector + prompt + 相容；屬 refactor，風險在別弄壞現有）。
**工時**：**3–5 天**（不含 LUT；要 LUT 另加 ~3 天）。
**相依**：是 #4 的前提（style 約束要拿 preset 來用）。

---

## 6. 方向四：決策層 style preset 約束 LLM

> **⏸ 實作狀態（2026-06-14）：暫緩，待之後再做。** 前置條件（#3 preset）已具備，技術上可動工，但評估後決定先擱置：
> - **現有導演 prompt 已內建半套**：`default_prompt_manager.py` 的工具箱已要求「**先為整支挑一個 preset 當統一基調（整支色調一致＝專業，勿每段亂換）**」＋最高指導原則「User Overrides Everything」。故當使用者把風格講清楚（如「暖色調、明亮通透」）時，Phase 4 在『色調一致』這條已能交付——#4 的「調色約束」部分對這種情況**邊際價值有限**。
> - **#4 真正不可替代的價值**在別處：(1) 約束的是「色彩＋運鏡＋轉場＋字幕＋配樂」**整包協調**，而非單一色調（用一句 prompt 把五維調成一套很難）；(2) **使用者指令模糊 / 非專業**時（「幫我剪好看一點」）給出有策劃過的預設風格；(3) 做成**可持久 / 可切換的具名風格**（存進 blueprint、未來前端下拉換風格）。這些痛點明確後再啟動。
> - **低成本中間路線**：先在現有導演 prompt 加一段「風格範例小抄」（列 4–6 個具名風格各自傾向哪套色彩 / 節奏 / 字幕 / 轉場），讓導演自行對號入座——不另開 pass、不改 fork-join、不加 LLM 成本；驗證有效再升級成獨立「定調 pass」。
> - **可重用接縫**（日後實作參考）：`BlueprintPreparer` fork-join + `DnaProducer` 抽象（定調 pass 可作新 producer 並行掛入、零額外延遲）；`CastingState` 是「輕量 Gemini Flash + response_schema」現成範本；`color_vocabulary_text()` 自動產詞彙、`filters=False` 的 post-LLM 強制重置是約束注入 / 校驗的先例。

這層講**導演 LLM 怎麼做決定**，跟 #3（能力長怎樣）無關。

**為什麼「把選項塞進 prompt」會讓品質變差**：若改 prompt 成「你有這 20 個濾鏡，請挑適合的」，LLM 面對平行選項又沒判斷依據，會「為用而用」→ 每段濾鏡都不同 → 整支色調不統一 → 看起來亂、廉價。**這是「選項越多、輸出越花」的反效果。**

> 類比：給新手「整本 Pantone 色票自由配」通常很醜；限制「只准用這 3 色」反而協調。**約束提升品質。**

**會做哪些事**
- **(a) 先定整支風格，再讓導演在裡面工作**
  - 定義 style preset 資料結構：一個 style ＝ 調色 preset + 字幕樣式 + 轉場傾向 + 運鏡節奏 + 配樂傾向的**約束包**；建 4–6 個（如 `vlog_warm` / `cinematic_travel` / `hype_fast` / `aesthetic_soft`）。
  - 新增「定調 pass」：輕量 LLM（或規則）決定整支用哪個 style，接進現有 producer 鏈（`dna_producer` / `prep_context` 那層）。
  - 改 prompt（`default_prompt_manager.py`）：「自由選濾鏡」→「在 style X 的調色盤內選」，並把 style 約束注入 context。
  - 導演只在**被縮小的調色盤**內逐段微調 → 輸出一致 ＝ 精緻。
- **(b) signal → motion 映射**：把 beats / bbox / speech 整理成結構化輸入供 prompt 引用（叫它「把訊號映射成運鏡」比「自己想辦法弄好看」可靠）。
- **(c)（可選、較大）多 pass**：把 mega-prompt 拆成「定調 / 節奏切點 / 美學細修」，各 pass 職責單一、prompt 短、可單獨驗證。

**#3 與 #4 的接縫**：#3 把「能力」做成 preset（資料）；#4 拿 **preset 名稱當 LLM 的選擇單位**。LLM 做高層決策（選 `cinematic_travel` 風格），不做低層參數（決定 brightness=0.9）→ 既穩又一致。

**難度**：只做 style 約束 + 定調 pass **中**；完整 multi-pass 重構 **高**。技術不難，**難在「調到真的有效」要反覆試**。
**工時**
- style 約束 + 定調 pass：coding **3–5 天** + 調效果 **數天–1 週（不確定）**
- 完整 multi-pass：**1.5–2 週** + 調校

**風險**：prompt 調校時間不確定性高；多 pass 增加 LLM 成本 / 延遲（成本敏感）。
**相依**：依賴 #3（preset 要先存在）——#3 已完成，**前置已滿足**（目前因價值評估暫緩，非被相依卡住）。

---

## 7. 方向五：品管層 視覺 critic 迴路

**問題**：現有 `critic/`（`critic_manager` + `gap_validator` / `overlap_validator` / `duration_validator`）只做**結構性 / 數值**檢查，沒有**美學**檢查。沒有 critic 就加選項，只是把「壞輸出的範圍」變大。

**會做哪些事**
- **便宜版（規則 critic）**：照 `base_validator` 模式（現有 validator 才 6–55 行）新增檢查，接進 `critic_manager`：
  - 字幕對比度（需抽背景幀算亮度）、主體 bbox 被 scale / position 裁掉、相鄰片段濾鏡衝突、切點密度 vs 節拍密度。
- **進階版（視覺 critic）**：
  - 把 blueprint 算成關鍵幀截圖（Remotion still / ffmpeg 抽幀管線）。
  - 丟 Gemini 多模態問「好不好看 / 字幕讀得到嗎 / 主體被切沒 / 節奏對嗎」。
  - 把回饋**落地成具體 blueprint 修改**，餵回 `reflection_state` 迴路。
  - 設停止條件（避免無限迴圈 + 成本爆）。

**難度**：規則版 **中**（架構已有，確定性規則好寫；抽幀算對比度中等）；視覺版 **高–很高**。
**工時**
- 規則 critic（幾條確定性檢查）：**3–5 天**
- 視覺 critic 完整迴路：**3–4 週+**，且**屬研究性質、效果不保證一次到位**。

**風險**：截圖渲染管線；「模型說醜 → 自動改 blueprint」是開放式難題；迴圈成本與收斂。
**相依**：規則版獨立，隨時可插；視覺版接 `reflection_state`。

---

## 8. 相依關係與建議順序

**相依關係**
- **#1 是地基** → #2 的字幕動畫直接復用它的 keyframe 機制 ⇒ **先 #1 再 #2**（皆 ✅ 已完成）。
- **#3 是前提** → #4 的 style 約束要拿 preset 來用 ⇒ **先 #3 再 #4**（#3 ✅ 已完成；#4 前置已滿足、目前暫緩）。
- **#5 規則版獨立**，隨時可插，CP 值高 ⇒ **建議作為下一步**。

**建議路徑（最省力、最快看到「精緻」）**

```
#1 精簡(Ken Burns + 卡點)   ✅ 已完成 (2026-06-13)
#2 樣式字幕(解耦字幕軌)     ✅ 已完成 (2026-06)
#3 primitive + preset       ✅ 已完成 (2026-06)
   → #5 規則 critic         ← 下一步（獨立、CP 值高）
   → #4 style 約束導演       ⏸ 暫緩，待之後再做（理由見 §6）
   → 之後回頭做 #1 / #2 / #3 / #5 的完整版
```

- **前三步（#1 / #2 / #3）**：✅ 已完成——成品已從「會套效果」變成「**會動、字幕精緻、調色一致且可維護**」，肉眼可見的跳級。
- **#3 / #4**：讓系統**可維護又風格一致**——#3（拔掉 3-way drift）已完成；#4（收斂導演自由度）暫緩。
- **#5**：規則版建議下一步、CP 值高；視覺版留到最後當研究題。
