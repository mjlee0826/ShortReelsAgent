# 方向二 字幕系統實作交接文件（v2：獨立字幕軌）

> **這份文件給接手的工程師 / agent。** 目標是讓你**不需要原始對話**就能完整理解「要做什麼、為什麼、現況到哪、接下來逐檔怎麼改」。
> 對應路線圖 `docs/editing_capability_roadmap.md` §4「方向二：結構化 TextOverlay + 卡拉OK字幕」的**精簡版**（樣式字幕），但位置模型升級成「字幕完全獨立於 Clip 的字幕軌」。
> 規範遵循 `CLAUDE.md`：輸出中文、程式邏輯註解中文、每個 class/function 有 docstring、用 pydantic/dataclass、禁 magic number（常數命名、適合則進共通 config）、不寫 test。

---

## 0. TL;DR

把「畫面字幕」從寫死樣式升級成**結構化、可逐條調樣式、會進出場、避開平台 UI、且完全獨立於影片片段（可跨素材、可同框多條）的字幕軌**。

- **資料模型**：新增 `blueprint.text_overlays: [TextOverlay]`，每條帶**絕對** `start_at/end_at`，與 `timeline`（clip 陣列）平行、互不綁定。
- **這是 LLM 要產出的**（進 `response_schema`），不是 post-LLM 注入。
- **編輯**：時間軸新增一條「字幕軌」，可拖移 / 拉伸 / 點選；Inspector 新增字幕面板。
- **本次不做**：卡拉OK逐字高亮、Whisper word-timestamp、感知管線改動（屬完整版，見 §9）。

---

## 1. 目標與動機

字幕是「業餘感」最明顯的地方。原本 `overlay_text` 只是字串，渲染成寫死的白色 5xl 置中 div。要做到「精緻」需要：可調位置 / 字級 / 顏色 / 描邊陰影 / 底框 / 進出場動畫，且字幕要能**跨多個片段持續顯示**、**同一畫面多條並存**——這兩點是「每個 clip 綁一條字幕」的舊模型**根本做不到**的（跨片段會在切點 fade out/in 閃爍、時長被切死；一個 clip 只能掛一條）。所以字幕必須**從 Clip 解耦**，做成 timeline 層級的獨立軌（CapCut / Premiere / Final Cut 的標準心智模型：文字是獨立軌道）。

---

## 2. 已拍板的決策（含理由，請勿重議）

| # | 決策 | 理由 |
|---|------|------|
| D1 | **範圍 = 精簡版（樣式字幕）**，不做卡拉OK、不動 `media_processor` 感知管線 | 路線圖把精簡版列為「下一步」；卡拉OK需改 Whisper 並重跑既有素材分析（Leibniz 共用 GPU 成本高），延後 |
| D2 | **樣式由導演 LLM 直接輸出細部欄位**；類別維度用 **Enum**、數值維度用 **bounded float** | 使用者選「細部欄位」而非「具名 preset」。用 enum/bounded 仍是「細部」，且延續 `schemas.py` 全檔以 enum 當 SSOT 的房規，避免 LLM 吐不可讀的自由 hex/px |
| D3 | **字型 = `@remotion/google-fonts`（Noto Sans TC）** | 使用者選此方案。⚠️ 已知 `npx remotion render` 當下需可連 Google Fonts，Leibniz 共用機有失敗風險，使用者接受 |
| D4 | **字幕位置 = 連續垂直 + 連續水平 %（LLM 自由微調）**，非固定 enum 位置 | 固定四角會擋主體；連續 % 讓導演依主體 bbox 避開主體。水平預設 50 置中（閱讀型字幕不受影響），可左右擺放花字 / 避主體 |
| D5 | **位置用 clamp 夾進 safe-area**（非 remap） | `position` 直接是畫面 %（50＝正中、85≈下三分之一），夾進安全帶確保不撞 IG/TikTok UI。比 remap 直覺（remap 會讓 50≠正中） |
| D6 | **字幕完全獨立於 Clip → `blueprint.text_overlays` 獨立陣列** | 解「跨素材字幕」與「同框多字幕」，這兩點 per-clip 模型做不到 |
| D7 | **編輯 UI 全做，含時間軸可拖曳字幕軌** | 使用者明確要「連可拖曳字幕軌一起做」，不只清單式 |

**一個已知取捨**：字幕一旦跨素材，就無法「逐 clip 自動避開各自不同的主體」（一條字幕壓在三個不同構圖上本來就不可能三邊都閃）。單一片段時長內的字幕仍可避主體。使用者已接受。

---

## 3. 現況：v1（per-clip 版）已在工作樹（**尚未 commit**）

⚠️ **重要**：前一輪已經實作了「**每個 clip 綁一條字幕**」的 v1 版本，這些改動**已存在於工作樹**（git 未 commit）。v2 要把它**改寫成獨立字幕軌**。下面逐一列出 v1 已經做了什麼，你要在這基礎上改（很多東西可直接沿用，只有「容器/計時/編輯」要動）。

### 3.1 後端（v1 已改）
- **`prompt_manager/schemas.py`**：
  - 已新增 enum：`TextSize`(s/m/l/xl)、`TextColor`(white/black/yellow/accent)、`TextOutline`(none/outline/shadow/outline_shadow)、`TextBackground`(none/solid/blur/pill)、`TextAnimation`(none/fade/slide_up/pop)。
  - 已新增 `TextOverlay(BaseModel)`：`text` / `vertical_position`(float, default 85, ge=0 le=100) / `size` / `color` / `outline` / `background` / `animation`。模組常數 `_TEXT_VPOS_MIN/MAX/DEFAULT`。
  - 已把 `Clip.overlay_text: str` 改成 `Clip.text_overlay: Optional[TextOverlay] = None`。
- **`prompt_manager/default_prompt_manager.py`**：工具箱 `overlay_text` 那行已換成 per-clip `text_overlay` 的多行心法（避主體 vertical_position + 樣式一致）。
- **`backend/services/director_service.py`**（約 line 464）：`subtitles=False` 提示已改成「請讓每個片段的 text_overlay 保持為 null」。
- **`director_agent/context_compressor.py`**（約 line 92）：註解 `overlay_text` 已改 `text_overlay`。

### 3.2 前端（v1 已改 / 新增）
- **`frontend/package.json` + `package-lock.json`**：已加依賴 `@remotion/google-fonts`（`^4.0.451`，實際裝到 4.0.476）並 `npm install` 完成。**已驗證 `@remotion/google-fonts/NotoSansTC` 可 resolve**，`loadFont()` 回傳 `fontFamily = "Noto Sans TC"`，subsets 含 `chinese-traditional`/`latin`。
- **`frontend/src/utils/fonts.js`（新檔）**：`loadFont()` → 匯出 `SUBTITLE_FONT_FAMILY`。**v2 不用改。**
- **`frontend/src/utils/textOverlay.js`（新檔）**：純函式集。目前內容：
  - `DEFAULT_OVERLAY`（已 export）= { vertical_position:85, size:'m', color:'white', outline:'outline_shadow', background:'none', animation:'fade' }
  - `resolveTextOverlay(clip)`：**per-clip** 版，讀 `clip.text_overlay`（物件）或 legacy `clip.overlay_text`（字串）→ 填預設 / null。**v2 要改/取代**。
  - `resolveVerticalCenterPct(verticalPosition)`：目前是 **remap**（`min + v/100*(max-min)`），**v2 要改成 clamp**。
  - `buildOutlineShadow(color, outline)`、`buildSubtitleCssStyle(overlay)`、`computeTextAnimationStyle({animation,frame,durationInFrames})`：**v2 全部沿用，不用改**。
  - 模組常數：`SUBTITLE_FONT_WEIGHT=700`、`SUBTITLE_LINE_HEIGHT=1.25`、`SLIDE_DISTANCE_PX=40`、`POP_MIN_SCALE=0.8`。
- **`frontend/src/components/RemotionPlayer/constants.js`**：已新增字幕常數區：`SAFE_AREA{TOP_PCT:12, BOTTOM_PCT:18}`、`SUBTITLE_Z_INDEX:50`、`SUBTITLE_SIZE_MAP{s:48,m:64,l:84,xl:110}`、`SUBTITLE_COLOR_MAP`、`SUBTITLE_OUTLINE_CONTRAST`、`SUBTITLE_OUTLINE_WIDTH_PX:2`、`SUBTITLE_DROP_SHADOW`、`SUBTITLE_BG_MAP`、`SUBTITLE_BOX_PADDING`、`SUBTITLE_MAX_WIDTH_PCT:86`、`SUBTITLE_ANIM_FRAMES:8`。**v2 要再加水平 safe margin 與字幕軌常數**。
- **`frontend/src/components/RemotionPlayer/TextOverlayLayer.jsx`（新檔）**：目前 props 是 `clip` + `durationInFrames`，內部呼叫 `resolveTextOverlay(clip)`，只做垂直定位。**v2 要改成吃 `overlay`（已填好的物件）+ 加水平定位**。
- **`frontend/src/components/RemotionPlayer/MainTimeline.jsx`**：目前在**每個 clip 的 `<Sequence>` 內**渲染 `<TextOverlayLayer clip={clip} durationInFrames={durationInFrames}/>`。**v2 要移除這個 per-clip 渲染，改成在 clip 之外另外 map `text_overlays` 成獨立 Sequence**。
- **`frontend/src/remotion.index.jsx`**：已加 `import './utils/fonts';`。**v2 不用改。**
- **`frontend/src/components/Editor/Inspector/ClipInspector.jsx`**：v1 在「字幕」section 加了 TextAreaRow + 垂直 SliderRow + 5 個 SelectRow + `TEXT_*_OPTIONS`/`VPOS_*` 常數 + `resolveTextOverlay`/`DEFAULT_OVERLAY` import + `overlay/ov/setOverlay`。**v2 要把這整段字幕 section 拔掉**（字幕不再屬 clip，移到獨立 Inspector）。
- **`frontend/src/components/Editor/Timeline/ClipBlock.jsx`**：v1 加了 `resolveTextOverlay(clip)?.text` 顯示 💬 摘要。**v2 要移除**（clip 不再帶字幕）。

---

## 4. v2 目標架構

### 4.1 資料模型
```
DirectorBlueprint
├── bgm_track            (既有；track_id/beats 由後端 post-LLM 注入)
├── timeline: [Clip]     (既有；clip 移除 text_overlay 欄位)
├── text_overlays: [TextOverlay]   ← 新增；LLM 產出；獨立於 timeline
└── global_settings      (post-LLM 由 director_facade 注入；非 schema 欄位)

TextOverlay
├── text: str
├── start_at: float      ← 新增；絕對時間軸秒數
├── end_at: float        ← 新增；絕對時間軸秒數
├── vertical_position:   float 0-100 (預設 85)
├── horizontal_position: float 0-100 (預設 50)   ← 新增
├── size / color / outline / background / animation  (enum，沿用 v1)
```

### 4.2 渲染（Remotion）
`MainTimeline` 在現有 clip 的 `.map()`（各包一個 `<Sequence>`）**之外**，另外 `.map()` `text_overlays`，每條字幕包成自己的 `<Sequence from={start*fps} durationInFrames={(end-start)*fps}>`，內含 `<TextOverlayLayer overlay={...} durationInFrames={...}/>`。
- 重疊的 Sequence Remotion 原生會同時渲染 → **同框多字幕**自然成立。
- 進出場動畫 key 在字幕**自己的** clip-relative frame（`useCurrentFrame()` 在各自 Sequence 內歸零）→ 跨 clip 不再於切點閃爍。
- Player 預覽與 SSR composition 皆 1080×1920（`VideoPlayer.jsx` 的 `compositionWidth/Height` 與 `remotion.index.jsx` 的 Composition 一致），故字幕字級用「合成空間 px」（`SUBTITLE_SIZE_MAP`）兩邊一致。

### 4.3 編輯
- **選取**：`selection` 增加 `'text'` 型別與索引（見 §6 store）。
- **時間軸字幕軌**：`TimelinePanel` 新增一條「字幕」lane，字幕方塊 `left=start_at*pxPerSecond / width=(end-start)*pxPerSecond`，**自由浮動**（與 clip 的 gapless/ripple 不同——可有間隙、可重疊、不 repack）。重疊字幕做 **lane-stacking**（貪婪分層）讓每條都點得到。可拖移（改 start/end 同步平移）、拉左右邊（各自改 start/end）、點選。
- **Inspector**：新 `TextOverlayInspector`（文字 / 起訖時間 / 垂直 / 水平 / 5 樣式 / 刪除）。

### 4.4 導演（LLM）
prompt 改成輸出 top-level `text_overlays` 陣列：各帶絕對 `start_at/end_at`，用 transcript chunk 時間戳**跨切點對齊語音**，依主體 bbox 用 vertical+horizontal 避主體，整支樣式一致，允許跨素材與同框多字幕。

---

## 5. 關鍵設計細節與陷阱（讀完再動手）

1. **text_overlays 進 `response_schema`，不是 post-LLM 注入**。對照：`bgm_track.beats`/`global_settings` 是 post-LLM 在 `director_service._run_workflow_inner` / `director_facade` 注入的（LLM 不決策）；但字幕內容/時間/樣式**是導演要決策的**，故 `text_overlays` 放進 `DirectorBlueprint` pydantic（Gemini response_schema + Qwen `schema_to_text` 兩條路徑都會自動同步，**勿手抄欄位**）。
2. **blueprint 解析不過 pydantic re-validation**：`director_agent/states/scheduling_state.py` 用 `json.loads` 解 LLM 輸出（非 `model_validate`），所以 dict 上的額外欄位都會保留；`backend/services/render_service.py` 也是把 blueprint dict **原樣**寫進 props.json 給 SSR。意義：你不必擔心 text_overlays 被 strip；但也代表**沒有後端自動補預設**，前端要容錯填預設。
3. **位置用 clamp 不用 remap**：`position`（0-100）= 畫面 % 直接夾進安全帶。垂直夾進 `[TOP_PCT, 100-BOTTOM_PCT]`；水平夾進 `[LEFT_PCT, 100-RIGHT_PCT]`，**水平 safe margin 不對稱**（右側留大，避 TikTok 右側讚/留言/分享按鈕列，建議 `LEFT_PCT≈6 / RIGHT_PCT≈14`）。預設 50→正中、85→下三分之一。（v1 的 `resolveVerticalCenterPct` 目前是 remap，要改成 clamp。）
4. **字幕軌是自由浮動，clip 軌是 ripple**：clip 的拖曳走 `repack`（首尾相接、無縫）；字幕**絕不可 repack**——拖移只改自身 `start_at/end_at`、clamp 到 `[0, total]`、`end_at>start_at+MIN`。這是兩套不同的拖曳模型，別套用 clip 的 `repack/reorder`。
5. **lane-stacking**：時間軸上重疊的字幕要分層顯示才都點得到。用貪婪法：依 start_at 排序，逐條塞進第一條「結束時間 ≤ 本條 start」的 lane，否則開新 lane。字幕軌高度 = `max(1, laneCount) * 列高`。**注意 lane 只是編輯顯示用，與渲染的 z-order / 畫面位置無關**。
6. **legacy 遷移**：既有專案 / 快照的 blueprint 可能是 (a) v1 的 per-clip `clip.text_overlay`，或 (b) 更舊的 `clip.overlay_text` 字串。要在 blueprint 進 store 時用 `migrateBlueprintTextOverlays(bp)` 一次性轉成 top-level `text_overlays`（每條的 `start_at/end_at` 取該 clip 的），並清掉 clip 上的舊欄位，讓**編輯器與渲染器一致**（否則預覽顯示字幕但字幕軌空的）。渲染器的 `resolveTimelineTextOverlays` 也要容錯：有 `text_overlays`（即使空陣列）就用它、否則才回退 legacy。
7. **字型外網風險**：`@remotion/google-fonts` 在 `npx remotion render` 當下會抓 Google Fonts。Leibniz 共用機若無外網會失敗 → 屆時需改自帶字型檔（`public/` + `@font-face`/`@remotion/fonts`）。本次照使用者決策用 google-fonts。
8. **Undo**：所有改 blueprint 的操作走 `editorSlice` 的 `mutateBlueprint`（會 pushHistory）。拖曳期間用 `commitSnapshot()` 在拖拽起點記**一次**快照，拖曳中走 transient 更新（不洗版 Undo），比照 clip 的 `trimClipTransient`。

---

## 6. 逐檔實作規格（v1 → v2 的 delta）

### 後端

**`prompt_manager/schemas.py`**
- `TextOverlay` 加兩個絕對時間欄位與水平位置（附 docstring/description、用具名常數）：
  - `start_at: float = Field(default=0.0, description="字幕在總時間軸上的開始秒數")`
  - `end_at: float = Field(default=0.0, description="字幕在總時間軸上的結束秒數")`
  - `horizontal_position: float = Field(default=50.0, ge=0, le=100, description="水平錨點：0=左、100=右、50=置中；依主體 bbox 避主體，系統會夾進 safe-area")`（新增模組常數 `_TEXT_HPOS_*`）。
- **移除** `Clip.text_overlay` 欄位。
- `DirectorBlueprint` 加 `text_overlays: list[TextOverlay] = Field(default_factory=list, description="畫面字幕清單（獨立於片段，可跨片段、可同時多條）")`。
- 確認 `schema_to_text` 仍能展開（它會遞迴 BaseModel + enum；`list[TextOverlay]` 會描述成「陣列，每項為 物件{...}」）。

**`prompt_manager/default_prompt_manager.py`**（`get_director_blueprint_prompt`）
- 把工具箱裡 v1 的 per-clip `text_overlay` 多行說明**移除**。
- 新增一個獨立段落（例如放在「工具箱」後、「配樂」前），說明 `text_overlays` 是**與 timeline 平行的頂層陣列**：每條含 `text`、絕對 `start_at/end_at`（用 `audio.transcript.chunks` 時間戳對齊講話時段、可跨多個片段）、`vertical_position`/`horizontal_position`（依主體 bbox 避主體、水平自動參考置中）、size/color/outline/background/animation（整支一致）。允許同一時段多條。**不要手寫 enum 值**（由 schema 注入）。

**`backend/services/director_service.py`**（約 line 464）
- `subtitles=False` 提示改成：「(注意：本影片不需要任何字幕，請讓 text_overlays 保持為空陣列 [])」。

**驗證**：
```bash
python3 -c "from prompt_manager.schemas import DirectorBlueprint, Clip, schema_to_text; \
print('text_overlay' in Clip.model_fields, 'text_overlays' in DirectorBlueprint.model_fields); \
print(schema_to_text(DirectorBlueprint))"
# 期望：False True；輸出含 text_overlays 陣列且每項含 start_at/end_at/horizontal_position 與各 enum
```

### 前端 —— 資料 / 渲染

**`frontend/src/components/RemotionPlayer/constants.js`**
- `SAFE_AREA` 加 `LEFT_PCT: 6, RIGHT_PCT: 14`（水平不對稱，右大）。
- 新增字幕軌常數：列高（如 `TEXT_LANE_H: 30`）、新字幕預設時長（如 `NEW_TEXT_DEFAULT_SEC: 2`）、最短字幕時長（可重用 `MIN_CLIP_DURATION`）。

**`frontend/src/utils/textOverlay.js`**
- `DEFAULT_OVERLAY` 加 `horizontal_position: 50`。
- `resolveVerticalCenterPct`：改成 **clamp**：`clamp(v, SAFE_AREA.TOP_PCT, 100-SAFE_AREA.BOTTOM_PCT)`。
- 新增 `resolveHorizontalCenterPct(h)`：`clamp(h, SAFE_AREA.LEFT_PCT, 100-SAFE_AREA.RIGHT_PCT)`。
- 新增 `fillOverlayDefaults(ov)`：`{ ...DEFAULT_OVERLAY, ...ov }`（補預設、確保樣式欄位齊全）。
- 新增 `resolveTimelineTextOverlays(blueprint)`（**渲染用**）：
  - 若 `Array.isArray(bp.text_overlays)` → `bp.text_overlays.map(fillOverlayDefaults)`（即使空陣列也用它，不回退 legacy）。
  - 否則（legacy）→ 從 `bp.timeline` 收集有字幕的 clip，產 `{ ...fillOverlayDefaults(clip.text_overlay 或 {text:clip.overlay_text}), start_at: clip.start_at, end_at: clip.end_at }`。
- 新增 `migrateBlueprintTextOverlays(blueprint)`（**載入用**，回傳新 blueprint，不可變）：
  - 若已有 `Array.isArray(bp.text_overlays)` → 原樣回傳。
  - 否則由 legacy（per-clip text_overlay / overlay_text）建出 `text_overlays` 陣列（start/end 取各 clip），並把 clip 上的 `text_overlay`/`overlay_text` 刪除，回傳 `{ ...bp, text_overlays, timeline: 清過的 clips }`。
- 舊的 per-clip `resolveTextOverlay(clip)` 對外用法移除（ClipBlock/ClipInspector 不再用它）。`buildSubtitleCssStyle`/`computeTextAnimationStyle`/`buildOutlineShadow` 不動。

**`frontend/src/components/RemotionPlayer/TextOverlayLayer.jsx`**
- props 改成 `{ overlay, durationInFrames }`（`overlay` 已是填好預設的物件，不再從 clip resolve）。
- 定位：`top = resolveVerticalCenterPct(overlay.vertical_position)%`、`left = resolveHorizontalCenterPct(overlay.horizontal_position)%`、`transform: translate(-50%,-50%)`（定位層）；動畫層套 `computeTextAnimationStyle` 的 opacity/transform（與定位 transform 分兩層，勿互蓋）。其餘（buildSubtitleCssStyle、z-index、pointer-events-none）沿用。

**`frontend/src/components/RemotionPlayer/MainTimeline.jsx`**
- **移除** clip Sequence 內的 `<TextOverlayLayer clip=.../>`。
- 在 `blueprint.timeline.map(...)` 之外（同一 `<AbsoluteFill>` 內、clip 區塊之後）新增：
  ```jsx
  {resolveTimelineTextOverlays(blueprint).map((ov, i) => {
    const from = Math.round((ov.start_at ?? 0) * fps);
    const to = Math.round((ov.end_at ?? 0) * fps);
    const dur = to - from;
    if (dur <= 0) return null;
    return (
      <Sequence key={`text-${i}`} from={from} durationInFrames={dur}>
        <TextOverlayLayer overlay={ov} durationInFrames={dur} />
      </Sequence>
    );
  })}
  ```
- import `resolveTimelineTextOverlays`。

### 前端 —— store

**`frontend/src/store/blueprint/history.js`**
- `EMPTY_SELECTION` 改成 `{ type: null, clipIndex: null, textIndex: null }`。

**`frontend/src/store/blueprint/editorSlice.js`**
- `selectText(index)`：`set({ selection: { type: 'text', clipIndex: null, textIndex: index } })`。
- `addTextOverlay(partial)`：`mutateBlueprint` 把一條新 overlay push 進 `bp.text_overlays`（補 `DEFAULT_OVERLAY` + 預設 start/end，例如 start=目前 playhead、end=start+`NEW_TEXT_DEFAULT_SEC`，clamp 到影片總長）；回傳新 blueprint。新增後可順手 `selectText(新索引)`。
- `updateTextOverlayField(index, key, value)`：`mutateBlueprint` 改 `bp.text_overlays[index][key]`（immutable map）。
- `updateTextOverlayTransient(index, { startAt, endAt })`：拖曳用，**直接 set 不 push history**（基準已由 `commitSnapshot` 在拖拽起點記），immutable 更新該 overlay 的 start/end。
- `removeTextOverlay(index)`：`mutateBlueprint` 過濾掉該條；同步修正 selection（選到被刪者→清空）。
- ⚠️ 字幕 CRUD **不要 repack**（自由浮動）。

**`frontend/src/store/blueprint/generationSlice.js`（3 處）與 `snapshotSlice.js`（1 處）**
- blueprint 進 store 前過 `migrateBlueprintTextOverlays`。位置：generationSlice 約 line 68（生成）、174（微調）、222（載入）；snapshotSlice 約 line 45（還原）。例：`blueprint: migrateBlueprintTextOverlays(result.blueprint)`。

### 前端 —— Inspector

**新 `frontend/src/components/Editor/Inspector/TextOverlayInspector.jsx`**
- 讀 `selection.textIndex` 對應的 overlay；用 `./controls` 的元件：
  - `TextAreaRow`（文字）、兩個 `NumberRow`（起 / 訖秒，step 0.1，min 0）、兩個 `SliderRow`（垂直 / 水平 0–100）、5 個 `SelectRow`（size/color/outline/background/animation，選項陣列照 v1 ClipInspector 拔下來的 `TEXT_*_OPTIONS`）、刪除按鈕（呼叫 `removeTextOverlay`）。
- 每次改值呼叫 `updateTextOverlayField(textIndex, key, value)`。

**`frontend/src/components/Editor/Inspector/index.jsx`**
- 路由加：`selectionType === 'text' ? <TextOverlayInspector /> : ...`。

**`frontend/src/components/Editor/Inspector/ClipInspector.jsx`**
- **移除** v1 加的「字幕」section（TextAreaRow + 垂直 SliderRow + 5 SelectRow）、`overlay/ov/setOverlay`、`TEXT_*_OPTIONS`/`VPOS_*` 常數、`resolveTextOverlay`/`DEFAULT_OVERLAY` import。（這些 `TEXT_*_OPTIONS` 可搬去 TextOverlayInspector。）

### 前端 —— 時間軸字幕軌

**新 `frontend/src/components/Editor/Timeline/TextBlock.jsx`**
- 比照 `ClipBlock.jsx`：純呈現 + 回報事件。body（拖移/點選）、左右邊把手（縮放）。props：`overlay`、`index`、`leftPx`、`widthPx`、`topPx`（lane 疊放用）、`isSelected`、`onBodyDown(index,e)`、`onEdgeDown(index,'left'|'right',e)`。顯示字幕文字摘要（truncate）。

**`frontend/src/components/Editor/Timeline/TimelinePanel.jsx`**
- 左側 label 欄加「字幕」列（仿「影片」「配樂」的 `FaFilm`/`FaMusic`，可用 `FaFont`/`FaClosedCaptioning`）。
- 軌道區新增字幕 lane（建議放「影片」與「配樂」之間或之下）：
  - 用 `useBlueprintStore` 取 `blueprint.text_overlays`。
  - 計算 lane-stacking（§5.5）得每條的 `laneIndex`；lane 高 = `laneCount * TEXT_LANE_H`。
  - 每條算 `leftPx = start_at*pxPerSecond`、`widthPx = (end_at-start_at)*pxPerSecond`、`topPx = laneIndex*TEXT_LANE_H`，渲染 `<TextBlock/>`，`isSelected = selection.type==='text' && selection.textIndex===i`。
  - 「＋新增字幕」按鈕（在字幕軌 label 或軌上）→ `addTextOverlay()`（start=playhead）。
- dragRef 擴充兩個模式（沿用既有 document mousemove/mouseup + RAF + `commitSnapshot` 機制）：
  - `text-move`：body 按下記 `{mode:'text-move', index, startX, origStart, origEnd}`；move 時 `deltaSec=(x-startX)/px`，`updateTextOverlayTransient(index,{ startAt: clamp(origStart+deltaSec,0,total-(origEnd-origStart)), endAt: 對應 })`。
  - `text-trim`：邊把手記 `{mode:'text-trim', index, edge, startX, origStart, origEnd}`；左邊改 start（clamp `0..origEnd-MIN`）、右邊改 end（clamp `origStart+MIN..total`）。
  - mouseup：若未超過 `DRAG_THRESHOLD_PX` 視為點選 → `selectText(index)` + seek 到 `start_at`。
- ⚠️ 字幕拖曳**不 repack**、不影響 clip 軌。

**`frontend/src/components/Editor/Timeline/ClipBlock.jsx`**
- 移除 v1 的 `resolveTextOverlay(clip)?.text` 與 💬 摘要 span 及其 import。

---

## 7. 可復用既有資產（路徑）

- **拖曳框架**：`Timeline/TimelinePanel.jsx` 的 `dragRef` + document `mousemove/mouseup` + `requestAnimationFrame` + `commitSnapshot`（拖拽起點記一次 Undo）+ `trimClipTransient` 模式；px↔秒 = `seconds * pxPerSecond`。字幕軌照抄這套，只是換成自由定位。
- **樣式/動畫/字型**（v1 已寫好，直接用）：`utils/textOverlay.js` 的 `buildSubtitleCssStyle`/`computeTextAnimationStyle`/`buildOutlineShadow`；`RemotionPlayer/constants.js` 的 `SUBTITLE_*` 對應表；`utils/fonts.js` 的 `SUBTITLE_FONT_FAMILY`。
- **Inspector 控制元件**：`Inspector/controls.jsx` 的 `SliderRow`/`SelectRow`/`NumberRow`/`TextAreaRow`/`InspectorSection`。
- **Undo / 就地編輯**：`store/blueprint/editorSlice.js` 的 `mutateBlueprint`/`commitSnapshot`/`updateClipField`（仿其寫字幕版）。
- **巢狀 schema 範式**：`schemas.py` 的 `PipVideo`（`Optional[巢狀]+Enum`）；`schema_to_text` 自動序列化 Qwen 路徑。
- **渲染骨架**：`RemotionPlayer/MainTimeline.jsx`（多個 `<Sequence>` 疊放）、`VideoPlayer.jsx`（Player 1080×1920）、`remotion.index.jsx`（SSR Composition）。

---

## 8. 驗證計畫

1. **Schema**（見 §6 後端驗證指令）：`Clip` 無 `text_overlay`、`DirectorBlueprint` 有 `text_overlays`，序列化含 `start_at/end_at/horizontal_position` 與所有 enum。
2. **建置 / lint**：`cd frontend && npm run build && npx eslint <你改動的檔>`。（注意：`vite.config.js` 有個**既有**的 `'process' is not defined` lint error，與本工作無關，別被誤導。）
3. **預覽**（`npm run dev` 進編輯器）：
   - 舊專案（per-clip / 更舊 overlay_text）載入後字幕仍正常顯示（migration 生效），且字幕軌上看得到對應方塊。
   - 字幕軌可拖移 / 拉左右邊 / 點選；同框多條字幕重疊顯示且都可點；跨多個 clip 的字幕在切點**不閃爍**。
   - Inspector 改文字 / 起訖 / 垂直 / 水平 / 樣式即時更新；把垂直或水平拉到極端值，字幕仍**不超出 safe-area**（clamp 生效）。
   - 「＋新增字幕」可在 playhead 建立字幕。
4. **導演**（需 Leibniz / GPU）：跑一次完整生成，落地 blueprint 含 top-level `text_overlays`，時間大致對齊語音；`subtitles=False` 時為 `[]`。
5. **匯出**：`render_service` 原樣寫 props.json → SSR 字幕位置 / 樣式 / 字型正確（⚠️ Google 字型需外網）。

---

## 9. 不在本次範圍（完整版，日後再做）

- **卡拉OK逐字高亮**：需 (a) `model/managers/whisper_model_manager.py` 的 `_TRANSCRIBE_KWARGS` 加 `word_timestamps=True`、(b) 擴充 schema 存逐字時間、(c) 既有素材重跑感知分析、(d) post-LLM 把逐字時間注入字幕。目前 Whisper **只存句級** chunks（`{text, timestamp:(start,end)}`），無逐字。
- 既有結構（解耦字幕軌）已為卡拉OK鋪好路：一條 `TextOverlay` 之後加 `words: [{text,start,end}]`（post-LLM 注入，比照 beats），`TextOverlayLayer` 依 `useCurrentFrame` 逐字高亮即可。

---

## 10. 相關檔案速查（給快速定位）

- 路線圖：`docs/editing_capability_roadmap.md`（§4 為方向二）
- Schema SSOT：`prompt_manager/schemas.py`、序列化 `schema_to_text`
- 導演 prompt：`prompt_manager/default_prompt_manager.py` `get_director_blueprint_prompt`
- 生成流程：`backend/services/director_service.py` `_run_workflow_inner`；`director_agent/director_facade.py`；`director_agent/states/scheduling_state.py`（`json.loads` 解析）
- 渲染：`frontend/src/components/RemotionPlayer/{MainTimeline,TextOverlayLayer,ClipComponent,constants}.jsx`、`remotion.index.jsx`、`utils/{textOverlay,fonts,motion,timeline}.js`
- 編輯器：`frontend/src/components/Editor/{Inspector/*,Timeline/*,Workbench.jsx}`、`store/blueprint/{editorSlice,generationSlice,snapshotSlice,history}.js`
- SSR 匯出：`backend/services/render_service.py`、`remotion_adapter.py`、API `backend/api/director.py` `/render_mp4`
