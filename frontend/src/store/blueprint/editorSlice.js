import { apiService } from '../../services/api.service';
import { extractErrorMessage } from '../../utils/errorMessage';
import { removeAt, reorder, repack } from '../../utils/timeline';
import { EMPTY_SELECTION, HISTORY_LIMIT, pushHistory, remapIndexAfterMove } from './history';

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

    // --- 編輯器互動狀態 ---
    // 目前選取對象：type 為 'clip'|'bgm'|'project'|null；clipIndex 僅在 type==='clip' 時有效
    // 以「陣列索引」識別片段，因 clip_id 是素材 relpath、同一素材可重複出現於多段而不唯一
    selection: { type: null, clipIndex: null },
    // 預覽 seek 請求：時間軸點片段時請求播放器跳轉；nonce 確保即使秒數相同也能再次觸發
    seekRequest: { seconds: 0, nonce: 0 },
    // 播放頭目前秒數：由 VideoPlayer 監聽 Remotion frameupdate 回寫，時間軸 Playhead 據此定位
    playheadSeconds: 0,
    // Undo/Redo 快照堆疊：past 為歷史版本、future 為被 undo 出去、可再 redo 的版本
    history: { past: [], future: [] },

    // ── 編輯器：選取 ───────────────────────────────────────────────────────────

    // 設定目前選取對象；右側檢視器依此切換顯示 Clip / Bgm / Project 面板
    select: (type, clipIndex = null) => set({ selection: { type, clipIndex } }),
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
        set({ isChangingMusic: false });
        return true;
      } catch (error) {
        alert(`換曲失敗：${extractErrorMessage(error)}`);
        set({ isChangingMusic: false });
        return false;
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
