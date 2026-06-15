# 偏好資料飛輪：把使用者編輯變成訓練資料

> 本文件記錄「資料飛輪」的構想、可行性與落地步驟。
> 一句話：**因為我們的輸出是結構化、可編輯的藍圖，使用者每一次編輯都能被捕捉成一筆「AI 排 X → 人改成 Y」的偏好資料；累積後用來訓練我們自己的開源導演模型。**
> 狀態（更新於 2026-06-15）：✅ T0–T2 已實作。T0 後端捕捉（AI 原版檔 + `preference_events.json`，best-effort、受全域 opt-out `user_settings.preference_capture_enabled` 控管）；T1 離線資料集 / 評測報告（`tools/preference_flywheel/`）；T2 few-shot 注入導演 prompt（`prompt_manager/preference_few_shot.py`，預設關、待人工策展 `config/preference_few_shot_examples.json`）。

---

## 1. 為什麼這件事可行（而且便宜）

導演 LLM 產出的不是一支烤死的影片，而是一份**結構化 JSON 藍圖**（`timeline` / `text_overlays` / `bgm_track`，見 `prompt_manager/schemas.py` 的 `DirectorBlueprint`）。使用者在編輯器裡的兩個動作——

1. **手動編輯**：選片段、調裁切 / 調色 / 字幕位置、換配樂（`frontend/src/store/blueprint/editorSlice.js`）。
2. **對話微調**：請 agent 改某部分（`generationSlice.submitPrompt` 的 refinement 路徑）。

——最終都會落到「一份改過的藍圖」。把它與「AI 原始藍圖」做欄位級 diff，就是一筆**機器可讀的偏好標註**：導演原本怎麼決定、人類怎麼修正。

**這就是護城河本身**：競品輸出 MP4，使用者就算不滿意去別處重剪，也產生不出這種結構化 diff——他們的飛輪轉不起來。

---

## 2. 現況與唯一缺口

- AI 藍圖在生成時會原子寫進 `phase4_blueprint.json`（`PHASE4_BLUEPRINT_FILENAME`，見 `backend/services/director_service.py` 的 `_dump_blueprint`）。
- **問題**：使用者一編輯，autosave（`save_blueprint`）就用編輯後版本**覆蓋同一個檔**（`editorSlice.persistBlueprint` → `save_blueprint`）。→ **AI 原始版當場被蓋掉、丟失。這是目前收不到資料的唯一原因。**
- 既有的 `editor_snapshots.json`（`SnapshotStore`）是**使用者手動存的檢查點**，不是自動的「AI 原版 vs 最終版」配對。
- 前端 undo `history` 在 `JOB_FINISHED` 時其實保留了 AI 原版，但**只在記憶體、重整即失**。

---

## 3. 落地步驟（分三層）

### T0 — 現在就做：別再丟資料（約 0.5–1 天）
1. 在 `config/project_artifacts.py` 新增一個產物常數，如 `PHASE4_BLUEPRINT_AI_ORIGINAL_FILENAME = "phase4_blueprint_ai_original.json"`。
2. 生成時（`run_workflow` 尾端 `_dump_blueprint` 旁）**多寫一份不可變的 AI 原版**，且 **autosave 永遠不碰它**。
3. 對話微調路徑：把 `{prompt, before(old_timeline), after(final_blueprint)}` 記成一筆 log（指令↔修正配對）。

→ 之後「AI 原版檔」對「PHASE4 最終版」即一組 X→Y；對話微調另成 指令↔修正 配對。**幾乎免費。**

### T1 — 變成乾淨的偏好資料（約數天，離線）
- 寫離線 diff 腳本，逐 clip / text_overlay / bgm 比對哪些欄位被改（順序、`object_position`、`color`、`source_start`、字幕位置…）。藍圖是結構化 JSON，欄位級 diff 直接。**屬資料處理，非產品程式。**

### T2 — 拿來用
- **近期（資料極少也行）**：① 當導演 prompt 的 **few-shot 範例**；② 當**評測訊號**——統計「哪種欄位最常被改」，直接指出導演哪裡最弱。
- **長線（需要量）**：微調**自有開源模型**（見下節）成為「我們自己的導演」。

---

## 4. 用什麼模型訓練：不是 Claude，是自有開源模型

- **Claude 不開放微調**：整個 Claude API 沒有 fine-tune 端點，客製化只能靠 prompt / 結構化輸出 / tool use / skills，**不是改權重**。
- **所以飛輪的訓練對象是我們自架的開源模型**（如 Phase 1 已在用的 Qwen）。這讓「自有導演模型」同時強化**成本護城河**（自己卡上跑、邊際成本低）與**資料護城河**（別人拿不到的偏好資料）。
- 現況：Phase 4 導演用 Claude（`DIRECTOR_PROVIDER` 可切 Gemini）。飛輪成熟後，可逐步把導演從「租用 Claude」換成「自有微調模型」。

---

## 5. 誠實面對的限制

1. **訊號有雜訊**：人改 X→Y 可能是個人口味、不一定是 AI 錯；也有人完全不改（選擇偏差）。
2. **量**：使用者少時短期湊不到訓練一個模型的量。**所以近期價值是評測 + few-shot + 證明飛輪會轉，不是立刻 fine-tune。**

對外說法要誠實分清「現在 vs 未來」：**「我們正在累積這批競品拿不到的偏好資料（現在）；用它訓練自己的導演模型是隨用量長出來的下一步（未來）。」**
