/**
 * Observer Pattern (Zustand)：影片藍圖狀態管理
 *
 * 管理目前開啟專案的生成表單、藍圖輸出與對話歷史紀錄。
 * 素材資料夾名稱改由 useProjectStore.currentProject.name 提供，
 * 不再由此 store 持有。
 */
import { create } from 'zustand';
import { apiService } from '../services/api.service';
import { removeAt, reorder } from '../utils/timeline';

// Undo/Redo 快照保留上限，避免記憶體無限成長（具名常數，禁 magic number）
const HISTORY_LIMIT = 50;
// 無選取時的初始選取狀態
const EMPTY_SELECTION = { type: null, clipIndex: null };

/**
 * 推進一筆 Undo 快照：把舊 blueprint 推入 past（超過上限則丟最舊），並清空 future。
 * 任何「會改變 blueprint 的操作」（手動就地編輯 / AI 微調）都應呼叫，確保可被 Undo。
 * @param {object} history 目前的 { past, future }
 * @param {object|null} prevBlueprint 變更前的 blueprint（null 代表首次生成，不推快照）
 * @returns {object} 新的 { past, future }
 */
function pushHistory(history, prevBlueprint) {
  if (!prevBlueprint) return { past: history.past, future: [] };
  return { past: [...history.past, prevBlueprint].slice(-HISTORY_LIMIT), future: [] };
}

/**
 * 計算「陣列元素由 from 移到 to」後，某個舊索引對應的新索引。
 * 用於重排後把選取狀態映射到正確的片段（避免選取錯位）。
 * @param {number} i 變更前的索引
 * @param {number} from 被移動元素的原索引
 * @param {number} to 被移動元素的新索引
 * @returns {number} 變更後的索引
 */
function remapIndexAfterMove(i, from, to) {
  if (i === from) return to;                 // 被移動者本身
  if (from < i && i <= to) return i - 1;     // 落在 (from, to] 的元素前移一格
  if (to <= i && i < from) return i + 1;     // 落在 [to, from) 的元素後移一格
  return i;                                  // 其餘不受影響
}

const useBlueprintStore = create((set, get) => ({
  // --- 表單狀態 ---
  userPrompt: '',
  templateSource: '',
  enableSubtitles: true,
  enableFilters: true,
  musicStrategy: 'search_copyright',

  // --- 音訊上傳狀態 ---
  uploadedMusicFile: null,
  isUploadingMusic: false,

  // --- 生成結果狀態 ---
  blueprint: null,
  assetsRootUrl: '',
  isProcessing: false,
  // 重新進入編輯器時，向後端讀回既有藍圖的載入中旗標（避免閃過 SetupView）
  isLoadingBlueprint: false,
  errorMsg: '',
  // 生成因素材未分析失敗時設為該專案名稱：EditorPage 據此跳轉素材頁，跳轉後清空
  redirectToAssetsProject: null,

  // --- 對話歷史紀錄 ---
  chatHistory: [],

  // --- 編輯器互動狀態 ---
  // 目前選取對象：type 為 'clip'|'bgm'|'project'|null；clipIndex 僅在 type==='clip' 時有效
  // 以「陣列索引」識別片段，因 clip_id 是素材 relpath、同一素材可重複出現於多段而不唯一
  selection: { type: null, clipIndex: null },
  // Undo/Redo 快照堆疊：past 為歷史版本、future 為被 undo 出去、可再 redo 的版本
  history: { past: [], future: [] },

  updateForm: (key, value) => set({ [key]: value }),

  // 重置所有輸出狀態（切換專案時由 useProjectStore 觸發）
  reset: () => set({
    blueprint: null,
    assetsRootUrl: '',
    isProcessing: false,
    isLoadingBlueprint: false,
    errorMsg: '',
    redirectToAssetsProject: null,
    chatHistory: [],
    uploadedMusicFile: null,
    userPrompt: '',
    templateSource: '',
    selection: { type: null, clipIndex: null },
    history: { past: [], future: [] },
  }),

  // ── 編輯器：選取 ───────────────────────────────────────────────────────────

  // 設定目前選取對象；右側檢視器依此切換顯示 Clip / Bgm / Project 面板
  select: (type, clipIndex = null) => set({ selection: { type, clipIndex } }),
  clearSelection: () => set({ selection: { ...EMPTY_SELECTION } }),

  // ── 編輯器：自動載入既有藍圖 ───────────────────────────────────────────────

  /**
   * 重新進入編輯器時，向後端讀回該專案先前生成的藍圖。
   * 已有 blueprint（記憶體仍在 / 正在生成）或正在載入時略過，避免覆蓋當前編輯。
   * 後端 404（尚未生成過）屬正常情況，靜默維持 SetupView。
   * @param {string} folderName 專案資料夾名稱
   */
  loadSavedBlueprint: async (folderName) => {
    if (!folderName || get().blueprint || get().isLoadingBlueprint) return;
    set({ isLoadingBlueprint: true });
    try {
      const result = await apiService.fetchBlueprint(folderName);
      // 視為「初始載入」：重置選取與 Undo 堆疊（這份藍圖即新的起點）
      set({
        blueprint: result.blueprint,
        assetsRootUrl: result.assets_root_url,
        selection: { ...EMPTY_SELECTION },
        history: { past: [], future: [] },
        isLoadingBlueprint: false,
      });
    } catch (error) {
      // 404 = 尚未生成過，保持 SetupView；其餘錯誤留下可見軌跡
      if (error.response?.status !== 404) {
        console.warn('[Editor] 載入既有藍圖失敗：', error.response?.data?.detail || error.message);
      }
      set({ isLoadingBlueprint: false });
    }
  },

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

  // 更新配樂軌欄位（音量 / 起播點）；bgm_track 不存在時補成空物件再寫入
  updateBgmField: (key, value) => get().mutateBlueprint((bp) => ({
    ...bp,
    bgm_track: { ...(bp.bgm_track || {}), [key]: value },
  })),

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

  // 上傳自訂 BGM 至素材資料夾，成功後記錄檔名
  uploadMusic: async (folderName, file) => {
    if (!folderName) {
      alert('無法取得專案資料夾名稱，請確認已選定專案。');
      return;
    }
    set({ isUploadingMusic: true });
    try {
      const result = await apiService.uploadMusic(folderName, file);
      set({ uploadedMusicFile: result.filename, isUploadingMusic: false });
    } catch (error) {
      const msg = error.response?.data?.detail || error.message || String(error);
      alert(`音訊上傳失敗：${msg}`);
      set({ isUploadingMusic: false });
    }
  },

  clearUploadedMusic: () => set({ uploadedMusicFile: null }),

  // 跳轉素材頁後清掉旗標，避免重複導航
  clearAssetsRedirect: () => set({ redirectToAssetsProject: null }),

  submitPrompt: async (isRefinement = false, refinementPrompt = '') => {
    set({ isProcessing: true, errorMsg: '' });

    const state = get();

    // 從 useProjectStore 取得當前專案名稱（避免 store 循環依賴，以 getState 直接讀取）
    const { default: useProjectStore } = await import('./useProjectStore');
    const currentProject = useProjectStore.getState().currentProject;
    const folderName = currentProject?.name || '';

    if (!folderName) {
      set({ isProcessing: false, errorMsg: '請先選定一個專案再生成影片。' });
      return;
    }

    // 管理對話紀錄
    if (isRefinement && refinementPrompt) {
      set((prev) => ({
        chatHistory: [...prev.chatHistory, { role: 'user', content: refinementPrompt }]
      }));
    } else if (!isRefinement) {
      set({
        chatHistory: [{ role: 'user', content: `🎬 初始指令：\n${state.userPrompt}` }]
      });
    }

    try {
      const payload = {
        asset_folder_name: folderName,
        user_prompt: isRefinement ? refinementPrompt : state.userPrompt,
        template_source: state.templateSource || null,
        enable_subtitles: state.enableSubtitles,
        enable_filters: state.enableFilters,
        previous_timeline: isRefinement && state.blueprint ? state.blueprint : null,
        music_strategy: state.musicStrategy,
        user_music_file: state.uploadedMusicFile || null,
      };

      const result = await apiService.generateTimeline(payload);

      // AI 微調結果也推進 Undo 快照（讓使用者能一鍵還原 AI 的改動，政策 C 安全網）；
      // 時間軸結構可能整個改變，故清空選取避免索引錯位
      set((prev) => ({
        blueprint: result.blueprint,
        assetsRootUrl: result.assets_root_url,
        isProcessing: false,
        history: pushHistory(prev.history, prev.blueprint),
        selection: { ...EMPTY_SELECTION },
        chatHistory: [
          ...prev.chatHistory,
          { role: 'system', content: '✅ 導演已更新劇本與時間軸！請查看左側預覽。' }
        ]
      }));

    } catch (error) {
      const detail = error.response?.data?.detail;
      // 後端回 409 + code=ASSETS_NOT_ANALYZED：素材尚未分析，設旗標讓 EditorPage 跳轉素材頁
      if (error.response?.status === 409 && detail?.code === 'ASSETS_NOT_ANALYZED') {
        set((prev) => ({
          isProcessing: false,
          redirectToAssetsProject: folderName,
          chatHistory: [
            ...prev.chatHistory,
            { role: 'error', content: `⚠️ ${detail.message}` }
          ]
        }));
        return;
      }
      // 其餘錯誤：detail 可能是字串（一般 HTTPException）或物件，取出可讀訊息
      const backendError =
        (typeof detail === 'string' ? detail : detail?.message) || error.message || String(error);
      set((prev) => ({
        errorMsg: `生成失敗：${backendError}`,
        isProcessing: false,
        chatHistory: [
          ...prev.chatHistory,
          { role: 'error', content: `❌ 哎呀，修改失敗了：${backendError}` }
        ]
      }));
    }
  }
}));

export default useBlueprintStore;
