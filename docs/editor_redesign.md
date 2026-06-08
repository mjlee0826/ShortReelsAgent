# EditorPage 重新設計：AI 粗剪 + 人工精修工作台

> 本文件記錄編輯器頁（`/editor`）改版的設計決策與資料模型。
> 把原本「填表生成 → 聊天微調 → 預覽 → 匯出」的純 AI 流程，
> 升級為「AI 做粗剪、人做精修」的兩階段混合工作台。
> 對應實作計畫：M1（骨架）→ M2（拖拉時間軸）→ M3（後端音樂修正）。

---

## 1. 為什麼要改

現行頁面有四個結構性問題：

1. **看不到 AI 剪出的結構**：blueprint 是一條 timeline，每段有 `filter / scale / transition_in / overlay_text / clip_volume / bgm_volume / pip_video` 等屬性，但 UI 完全沒暴露，使用者只能盲剪。
2. **精修只能靠聊天**：精準操作（裁掉某段 0.5 秒、改某段字幕）用自然語言又慢又不準。
3. **生成表單只用一次卻永久佔位**：`SidebarForm` 生成後仍佔右側上半，空間浪費。
4. **沒利用 9:16 垂直影片的版面特性**：預覽又高又窄，左右水平空間閒置。

**目標版面**：中央 9:16 預覽、底部真實時間軸、選取片段後在右側檢視器調屬性、AI 對話退居為可收合 copilot 抽屜。

---

## 2. 核心設計決策

| # | 決策 | 內容 |
|---|---|---|
| D1 | **編輯範式** | AI + 時間軸混合（中央預覽 / 底部時間軸 / 右側檢視器 / AI copilot 抽屜） |
| D2 | **階段模型** | 兩階段切換：`blueprint` 不存在 → Setup 視圖；存在 → 編輯工作台。Setup 收成 Header 的「重新生成」入口（沿用 `/editor` 單一路由，以 blueprint 是否存在條件渲染） |
| D3 | **資料同步界線** | 判準＝「需不需要 AI 重新推理」（見 §3） |
| D4 | **衝突政策（政策 C）** | blueprint＝單一真相；AI 微調靠後端 prompt「局部修改、未提及保留原樣」保護手動編輯，配 Undo 兜底（見 §4） |
| D5 | **進階欄位** | `object_position`、`playback_rate`、`pip_video` **第一版唯讀顯示**，不開放手動編輯（UI 較雜，先求快） |
| D6 | **換素材** | **第一版不做**改 `clip_id`（需素材選擇器）。連帶 **新增片段也不做**（同樣需要選素材）。第一版只能調整 AI 已選好的片段 |
| D7 | **檢視器分組** | 逐段檢視器分 5 組：來源 / 畫面 / 字幕 / 音訊 / 進階(收合) ＋ AI 決策說明(唯讀)（見 §5） |
| D8 | **時間軸行為** | 無縫接合 (gapless ripple)：裁切 / 重排 / 刪除後自動重算 `start_at / end_at`，永遠無空隙、不重疊 |
| D9 | **交付方式** | 分階段里程碑 M1 → M2 → M3 |

---

## 3. 資料同步界線（D3）

判準是**「這個操作需不需要 AI 重新推理」**。後端 AI 很貴又非即時，職責是重推理（選素材、決定切點、找音樂、產字幕內容）；一旦 blueprint 存在，改它的欄位是純前端、即時的。

| 操作 | 歸屬 |
|---|---|
| 裁切 in/out、調片段長度 | **就地編輯**（只動前端 blueprint，即時預覽） |
| 重排、刪除片段 | **就地編輯** |
| 改字幕文字、濾鏡、縮放、轉場、原音/避讓音量 | **就地編輯** |
| 配樂軌音量、起播點 | **就地編輯**（後端配套見 §6 #3） |
| 初始生成 | **重新生成**（打後端） |
| 自然語言大改（風格 / 重選素材） | **重新生成** |
| 配樂策略 / 換一首 | **重新生成** |
| 字幕總開關 / 濾鏡總開關 | **重新生成** |

音樂的雙重身分：**「策略」（要不要配樂 / 版權 / 免費 / 上傳）＝重新生成**；**「軌道微調」（音量 / 起播）＝就地編輯**。

---

## 4. 衝突政策 C（D4）

**根基**：不論手動編輯或 AI 微調，改的都是同一份 `blueprint`（single source of truth）。

- **就地編輯**：前端直接 immutable 改 blueprint，Remotion 預覽即時反映。
- **AI 微調**：把「當前 blueprint（已含手動編輯）」當 `previous_timeline` 送回後端 → AI 在此基礎上局部修改 → 回傳新版取代。

後端查核（`prompt_manager/default_prompt_manager.py:158-220`）：refinement 已送整份 `previous_timeline`，且 prompt 明寫「局部修改。若無提及的部分請保留原樣」——逐段屬性的政策 C **成立**。

**安全網**：因 blueprint 是單一真相，任何改動（手動 or AI）都只是產生新版 blueprint，故以**快照堆疊**提供 Undo / Redo；AI 微調若改壞手動成果可一鍵還原。上限以具名常數 `HISTORY_LIMIT` 控制。

---

## 5. 逐段檢視器分組（D7）

選中片段時，右側檢視器分 5 組（＋ AI 說明）：

```
〔片段 N〕
─ 來源 ──────  素材縮圖 / clip_id(唯讀)、裁切 source_start·source_end、playback_rate(唯讀)
─ 畫面 ──────  scale、object_position(唯讀)、filter、transition_in
─ 字幕 ──────  overlay_text
─ 音訊 ──────  clip_volume(原音)、bgm_volume(此段配樂避讓)
─ 進階 ▾ ────  pip_video(畫中畫)  ← 整組唯讀
─ 🤖 AI 決策說明  reason(唯讀)
```

| 欄位 | 類型 | 控制項 |
|---|---|---|
| 縮圖 + clip_id | 唯讀（D6 不換素材） | 縮圖 |
| source_start / source_end 裁切 | 就地 | 數字 / 時間軸拖邊(M2) |
| playback_rate 變速 | **唯讀(D5)** | 顯示 |
| scale 縮放 | 就地 | slider |
| object_position 定位 | **唯讀(D5)** | 顯示 |
| filter 濾鏡 | 就地 | Select(none/cinematic/grayscale/blur) |
| transition_in 轉場 | 就地 | Select(none/fade/slide) |
| overlay_text 字幕 | 就地 | textarea |
| clip_volume 原音 | 就地 | slider |
| bgm_volume 配樂避讓 | 就地 | slider |
| pip_video 畫中畫 | **唯讀(D5)** | 顯示 |
| reason AI 說明 | 唯讀 | 文字 |

**全域面板**（點配樂軌 / 空白處）：`bgm_track.volume`、`bgm_track.source_start` 為就地編輯；`fps`、`aspect_ratio` 唯讀（衍生值，見 §6 #2）；策略 / 換曲 / 總開關導向「重新生成」面板。

---

## 6. 後端配套（政策 C 的三個注意點）

| # | 發現 | 對策 |
|---|---|---|
| 1 | 逐段屬性保留只靠 LLM 遵守 prompt（非確定性） | 可接受，用 **Undo 快照**兜底 |
| 2 | `global_settings.fps` 每次從素材重算（`director_agent/director_facade.py:47-57`），不沿用前版 | **fps / 比例做唯讀衍生值**，不開放手動改，問題消失 |
| 3 | 每次 refinement 都重跑 `IntentState` 重新搜尋 / 抓配樂（`director_agent/states/intent_state.py`），會默默換掉 BGM 並蓋掉手動 bgm 設定 | **M3 後端小修**：使用者沒要求改音樂時跳過重抓、沿用上一版 `bgm_track`（`GenerateRequest` 加 `previous_bgm_track` / `regenerate_music`） |

---

## 7. 時間軸 ripple 模型（D8）

單軌、無縫接合：

- 每段顯示時長 `D = end_at - start_at`。
- **裁切**：拖右邊縮短 → 減 `source_end` 與 `D`；拖左邊 → 增 `source_start` 與 `D`（image 無 source，只改 `D`）。
- **重排 / 刪除**：保持各段 `D`，依新順序由 0 起逐段重算 `start_at / end_at`。
- 統一由純函式 `repack(clips)`（`frontend/src/utils/timeline.js`）在每次結構變更後重算，確保永遠無空隙、不重疊。

---

## 8. 里程碑

- **M1**：骨架 + 兩階段 + 檢視器即時編輯（5 組）+ 唯讀時間軸視覺化 + Undo/Redo。
- **M2**：時間軸拖拉裁切 / 重排 + playhead 雙向同步（`@remotion/player` 的 `PlayerRef`）。
- **M3**：後端音樂重抓修正（§6 #3）+ 配樂軌就地編輯落地。
