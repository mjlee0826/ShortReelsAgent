import { apiService } from '../../services/api.service';
import { extractErrorMessage } from '../../utils/errorMessage';
import { removeAt, reorder, repack, MIN_CLIP_DURATION } from '../../utils/timeline';
import { DEFAULT_OVERLAY } from '../../utils/textOverlay';
import { NEW_TEXT_DEFAULT_SEC } from '../../components/RemotionPlayer/constants';
import { EMPTY_SELECTION, HISTORY_LIMIT, pushHistory, remapIndexAfterMove } from './history';

/** 夾在 [lo, hi] 區間（純工具）。 */
const clampNum = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/**
 * 編輯器就地編輯 slice：藍圖本體、選取與預覽互動、就地編輯與 Undo/Redo。
 *
 * 藍圖本體（blueprint / assetsRootUrl / history）由本 slice 持有並初始化，
 * 其餘 slice（生成 / 快照）透過共用的 set/get 讀寫，屬 slice pattern 正常用法。
 * @param {Function} set zustand set
 * @param {Function} get zustand get
 * @returns {object} slice 片段
 */
export function createEditorSlice(set, get) {
  return {
    // --- 生成結果中與編輯相關的核心狀態 ---
    blueprint: null,
    assetsRootUrl: '',
    // music-only 換曲進行中（配樂引擎抓取較久，用於彈窗 loading）
    isChangingMusic: false,
    // 已落地到後端 PHASE4 的 blueprint「物件參照」：autosave 去重基準。
    // 由 server-sourced 路徑（載入 / 生成結果）與 persistBlueprint 成功後設定；
    // 當前 blueprint 與此參照相同時代表磁碟已是最新，autosave 直接 no-op（見 persistBlueprint）。
    persistedBlueprint: null,

    // --- 編輯器互動狀態 ---
    // 目前選取對象：type 為 'clip'|'bgm'|'text'|'project'|null；clipIndex 僅在 type==='clip'、
    // textIndex 僅在 type==='text' 時有效。以「陣列索引」識別，因 clip_id 是素材 relpath、同一素材
    // 可重複出現於多段而不唯一；字幕亦以 text_overlays 陣列索引識別。
    selection: { type: null, clipIndex: null, textIndex: null },
    // 預覽 seek 請求：時間軸點片段時請求播放器跳轉；nonce 確保即使秒數相同也能再次觸發
    seekRequest: { seconds: 0, nonce: 0 },
    // 播放頭目前秒數：由 VideoPlayer 監聽 Remotion frameupdate 回寫，時間軸 Playhead 據此定位
    playheadSeconds: 0,
    // Undo/Redo 快照堆疊：past 為歷史版本、future 為被 undo 出去、可再 redo 的版本
    history: { past: [], future: [] },

    // ── 編輯器：選取 ───────────────────────────────────────────────────────────

    // 設定目前選取對象；右側檢視器依此切換顯示 Clip / Bgm / Project 面板。
    // 以 EMPTY_SELECTION 打底重置 textIndex，避免選 clip 時殘留上次的字幕索引。
    select: (type, clipIndex = null) => set({ selection: { ...EMPTY_SELECTION, type, clipIndex } }),
    // 選取某條字幕（時間軸字幕軌 / 字幕 Inspector 用）；打底重置 clipIndex。
    selectText: (index) => set({ selection: { ...EMPTY_SELECTION, type: 'text', textIndex: index } }),
    clearSelection: () => set({ selection: { ...EMPTY_SELECTION } }),

    // 請求預覽播放器跳轉到指定秒數（VideoPlayer 監聽 nonce 後換算成 frame 並 seekTo）
    seekTo: (seconds) => set((state) => ({ seekRequest: { seconds, nonce: state.seekRequest.nonce + 1 } })),

    // 由 VideoPlayer 回寫目前播放頭秒數（不進 Undo / 不影響 blueprint）
    setPlayhead: (seconds) => set({ playheadSeconds: seconds }),

    // ── 編輯器：就地編輯（直接改前端 blueprint，即時預覽，不打後端）───────────────

    /**
     * 就地編輯核心：以 producer 產生新 blueprint，並推進 Undo 快照。
     * producer 必須是純函式 (blueprint) => newBlueprint（immutable，不修改輸入）。
     * @param {(bp: object) => object} producer 由舊 blueprint 算出新 blueprint
     */
    mutateBlueprint: (producer) => set((state) => {
      if (!state.blueprint) return {};
      const next = producer(state.blueprint);
      if (!next || next === state.blueprint) return {};
      return { blueprint: next, history: pushHistory(state.history, state.blueprint) };
    }),

    // 更新某片段的單一欄位（字幕 / 濾鏡 / 縮放 / 轉場 / 音量 / 裁切數值），不重排
    updateClipField: (index, key, value) => get().mutateBlueprint((bp) => ({
      ...bp,
      timeline: bp.timeline.map((clip, i) => (i === index ? { ...clip, [key]: value } : clip)),
    })),

    // 拖拽期間用：先存一筆 Undo 快照當基準（整段拖拽只記一次，避免洗版 Undo 堆疊）
    commitSnapshot: () => set((state) => (
      state.blueprint ? { history: pushHistory(state.history, state.blueprint) } : {}
    )),

    // 拖邊裁切（時間軸）：設片段時長與來源 in/out 後 ripple 接合；不推快照（基準已於拖拽起點存好）。
    // duration 必填；sourceStart / sourceEnd 僅 video 傳入（image 無來源窗）。
    trimClipTransient: (index, { duration, sourceStart, sourceEnd }) => set((state) => {
      if (!state.blueprint) return {};
      const timeline = state.blueprint.timeline.map((clip, i) => {
        if (i !== index) return clip;
        // 以目前 start_at + duration 設 end_at 決定時長；repack 隨後重算全軌 start_at/end_at
        const next = { ...clip, end_at: (clip.start_at ?? 0) + duration };
        if (sourceStart !== undefined) next.source_start = sourceStart;
        if (sourceEnd !== undefined) next.source_end = sourceEnd;
        return next;
      });
      return { blueprint: { ...state.blueprint, timeline: repack(timeline) } };
    }),

    // 更新配樂軌欄位（音量 / 起播點）；bgm_track 不存在時補成空物件再寫入
    updateBgmField: (key, value) => get().mutateBlueprint((bp) => ({
      ...bp,
      bgm_track: { ...(bp.bgm_track || {}), [key]: value },
    })),

    // 更新全域設定欄位（自動運鏡 / 卡點等 render-time 視覺旗標）；即時改 blueprint，預覽立即重算、免重新生成。
    // 走 mutateBlueprint 故會推進 Undo、並隨快照持久化；global_settings 不存在時補成空物件再寫入。
    updateGlobalSettingField: (key, value) => get().mutateBlueprint((bp) => ({
      ...bp,
      global_settings: { ...(bp.global_settings || {}), [key]: value },
    })),

    // music-only 換曲：只重挑配樂、保留時間軸；成功後就地套用新 bgm_track（推進 Undo，可還原）
    changeMusic: async (folderName, { musicStrategy, userMusicFile, userPrompt }) => {
      if (!folderName || !get().blueprint) return;
      set({ isChangingMusic: true });
      try {
        const result = await apiService.changeMusic({
          asset_folder_name: folderName,
          music_strategy: musicStrategy,
          user_music_file: userMusicFile || null,
          user_prompt: userPrompt || null,
          previous_bgm_track: get().blueprint?.bgm_track ?? null,
        });
        get().mutateBlueprint((bp) => ({ ...bp, bgm_track: result.bgm_track }));
        // 換曲是明確 apply 動作：立即落地（不等 autosave debounce），杜絕「換完秒重整就消失」
        await get().persistBlueprint(folderName);
        set({ isChangingMusic: false });
        return true;
      } catch (error) {
        alert(`換曲失敗：${extractErrorMessage(error)}`);
        set({ isChangingMusic: false });
        return false;
      }
    },

    // 編輯器自動儲存：把當前 blueprint 落地後端 PHASE4，讓重整後 loadSavedBlueprint 能還原。
    // 以 persistedBlueprint 參照去重：當前 blueprint 即上次落地版（剛載入 / 剛生成完）時直接 no-op，
    // 避免「載入即回寫」與冗餘寫。失敗只記 console（沿用就地編輯不阻斷 UX 的風格，不彈 alert）。
    persistBlueprint: async (folderName) => {
      const bp = get().blueprint;
      if (!folderName || !bp) return;
      if (bp === get().persistedBlueprint) return;
      try {
        await apiService.saveBlueprint(folderName, bp);
        set({ persistedBlueprint: bp });
      } catch (error) {
        console.warn('[Editor] 自動儲存藍圖失敗：', extractErrorMessage(error));
      }
    },

    // 刪除片段並 ripple 接合；同步修正選取索引（刪到選取者則清空、刪在其前則前移）
    removeClip: (index) => {
      get().mutateBlueprint((bp) => ({ ...bp, timeline: removeAt(bp.timeline, index) }));
      set((state) => {
        const sel = state.selection;
        if (sel.type !== 'clip') return {};
        if (sel.clipIndex === index) return { selection: { ...EMPTY_SELECTION } };
        if (sel.clipIndex > index) return { selection: { ...sel, clipIndex: sel.clipIndex - 1 } };
        return {};
      });
    },

    // 重排片段並 ripple 接合；同步把選取索引映射到重排後的新位置
    reorderClips: (fromIndex, toIndex) => {
      if (fromIndex === toIndex) return;
      get().mutateBlueprint((bp) => ({ ...bp, timeline: reorder(bp.timeline, fromIndex, toIndex) }));
      set((state) => {
        const sel = state.selection;
        if (sel.type !== 'clip') return {};
        return { selection: { ...sel, clipIndex: remapIndexAfterMove(sel.clipIndex, fromIndex, toIndex) } };
      });
    },

    // ── 編輯器：字幕軌 CRUD（獨立於片段、自由浮動；一律不 repack）──────────────────

    /**
     * 新增一條字幕：起點取目前播放頭、終點 = 起點 + 預設時長（夾進影片總長）。新增後選取它。
     * @param {object} partial 可覆寫的初始欄位（如 text）
     */
    addTextOverlay: (partial = {}) => {
      const state = get();
      if (!state.blueprint) return;
      // 影片總長 = 各片段 end_at 的最大值（片段已 gapless，等同末段終點）
      const total = (state.blueprint.timeline || []).reduce((m, c) => Math.max(m, c.end_at ?? 0), 0);
      const start = clampNum(state.playheadSeconds ?? 0, 0, Math.max(0, total - MIN_CLIP_DURATION));
      const end = Math.min(start + NEW_TEXT_DEFAULT_SEC, total || start + NEW_TEXT_DEFAULT_SEC);
      const overlay = { ...DEFAULT_OVERLAY, text: '', start_at: start, end_at: end, ...partial };
      let newIndex = 0;
      get().mutateBlueprint((bp) => {
        const list = Array.isArray(bp.text_overlays) ? bp.text_overlays : [];
        newIndex = list.length;
        return { ...bp, text_overlays: [...list, overlay] };
      });
      get().selectText(newIndex);
    },

    // 更新某條字幕的單一欄位（文字 / 位置 / 樣式 / 起訖）；immutable map，推進 Undo
    updateTextOverlayField: (index, key, value) => get().mutateBlueprint((bp) => ({
      ...bp,
      text_overlays: (bp.text_overlays || []).map((ov, i) => (i === index ? { ...ov, [key]: value } : ov)),
    })),

    // 拖曳期間用：更新某條字幕的起訖秒數，直接 set 不推快照（基準已於拖拽起點由 commitSnapshot 存好）
    updateTextOverlayTransient: (index, { startAt, endAt }) => set((state) => {
      if (!state.blueprint) return {};
      const text_overlays = (state.blueprint.text_overlays || []).map((ov, i) => {
        if (i !== index) return ov;
        const next = { ...ov };
        if (startAt !== undefined) next.start_at = startAt;
        if (endAt !== undefined) next.end_at = endAt;
        return next;
      });
      return { blueprint: { ...state.blueprint, text_overlays } };
    }),

    // 刪除某條字幕；同步修正選取索引（刪到選取者則清空、刪在其前則前移）
    removeTextOverlay: (index) => {
      get().mutateBlueprint((bp) => ({
        ...bp,
        text_overlays: (bp.text_overlays || []).filter((_, i) => i !== index),
      }));
      set((state) => {
        const sel = state.selection;
        if (sel.type !== 'text') return {};
        if (sel.textIndex === index) return { selection: { ...EMPTY_SELECTION } };
        if (sel.textIndex > index) return { selection: { ...sel, textIndex: sel.textIndex - 1 } };
        return {};
      });
    },

    // ── 編輯器：Undo / Redo（手動編輯與 AI 微調共用同一快照堆疊）─────────────────

    undo: () => set((state) => {
      if (state.history.past.length === 0) return {};
      const past = [...state.history.past];
      const restored = past.pop();
      const future = state.blueprint ? [state.blueprint, ...state.history.future] : state.history.future;
      return { blueprint: restored, history: { past, future }, selection: { ...EMPTY_SELECTION } };
    }),

    redo: () => set((state) => {
      if (state.history.future.length === 0) return {};
      const [restored, ...future] = state.history.future;
      const past = state.blueprint
        ? [...state.history.past, state.blueprint].slice(-HISTORY_LIMIT)
        : state.history.past;
      return { blueprint: restored, history: { past, future }, selection: { ...EMPTY_SELECTION } };
    }),
  };
}
