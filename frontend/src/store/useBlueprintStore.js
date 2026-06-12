/**
 * Observer Pattern (Zustand)：影片藍圖狀態管理
 *
 * 管理目前開啟專案的生成表單、藍圖輸出與對話歷史紀錄。
 * 素材資料夾名稱改由 useProjectStore.currentProject.name 提供，
 * 不再由此 store 持有。
 */
import { create } from 'zustand';
import { apiService } from '../services/api.service';
import { removeAt, reorder, repack } from '../utils/timeline';

// Undo/Redo 快照保留上限，避免記憶體無限成長（具名常數，禁 magic number）
const HISTORY_LIMIT = 50;
// 無選取時的初始選取狀態
const EMPTY_SELECTION = { type: null, clipIndex: null };

// 生成 stage_name → 進度面板使用者面向文案（template 走 pipeline 各 stage + music 分支三步，
// 兩分支事件交錯到達；未列出者退回原始 stage 名，禁 magic string 散落各處）
const GENERATION_STAGE_LABELS = {
  // template 分支（pipeline complex 影片 DAG）
  decode: '解析範本影格',
  semantic: '範本語意分析',
  scene: '偵測鏡頭切點',
  whisper: '範本語音聽寫',
  audio_env: '範本環境音分析',
  vad: '範本人聲偵測',
  assembly: '彙整範本特徵',
  // music 分支
  music_download: '下載配樂',
  music_beats: '分析配樂節拍',
  music_lyrics: '配樂歌詞聽寫',
};

/** 由 WS 進度事件取出階段文案；無 stage_name 回 null，未知 stage 退回原始名稱。 */
function stageLabel(event) {
  const name = event?.stage_name;
  if (!name) return null;
  return GENERATION_STAGE_LABELS[name] || name;
}

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
  // 是否啟用自動運鏡（Ken Burns + 卡點）：送 enable_motion，後端寫進 global_settings.auto_motion
  enableMotion: true,
  musicStrategy: 'search_copyright',

  // --- 音訊上傳狀態 ---
  uploadedMusicFile: null,
  isUploadingMusic: false,
  // music-only 換曲進行中（配樂引擎抓取較久，用於彈窗 loading）
  isChangingMusic: false,

  // --- 生成結果狀態 ---
  blueprint: null,
  assetsRootUrl: '',
  isProcessing: false,
  // 進行中生成的背景 job_id：EditorPage 據此訂閱 WS 看 template ∥ music 兩分支即時進度；無則 null
  generationJobId: null,
  // 目前生成階段標籤（由 WS STAGE_* 事件即時更新，供進度面板顯示「下載中 / 聽寫中…」）；閒置為 null
  generationStage: null,
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
  // 預覽 seek 請求：時間軸點片段時請求播放器跳轉；nonce 確保即使秒數相同也能再次觸發
  seekRequest: { seconds: 0, nonce: 0 },
  // 播放頭目前秒數：由 VideoPlayer 監聽 Remotion frameupdate 回寫，時間軸 Playhead 據此定位
  playheadSeconds: 0,
  // Undo/Redo 快照堆疊：past 為歷史版本、future 為被 undo 出去、可再 redo 的版本
  history: { past: [], future: [] },
  // 持久化具名快照 meta 列表（[{ id, label, created_at }]，由後端讀寫；blueprint 不在此）
  snapshots: [],

  updateForm: (key, value) => set({ [key]: value }),

  // 重置所有輸出狀態（切換專案時由 useProjectStore 觸發）
  reset: () => set({
    blueprint: null,
    assetsRootUrl: '',
    isProcessing: false,
    generationJobId: null,
    generationStage: null,
    isLoadingBlueprint: false,
    errorMsg: '',
    redirectToAssetsProject: null,
    chatHistory: [],
    uploadedMusicFile: null,
    isChangingMusic: false,
    userPrompt: '',
    templateSource: '',
    selection: { type: null, clipIndex: null },
    seekRequest: { seconds: 0, nonce: 0 },
    playheadSeconds: 0,
    history: { past: [], future: [] },
    snapshots: [],
  }),

  // ── 編輯器：選取 ───────────────────────────────────────────────────────────

  // 設定目前選取對象；右側檢視器依此切換顯示 Clip / Bgm / Project 面板
  select: (type, clipIndex = null) => set({ selection: { type, clipIndex } }),
  clearSelection: () => set({ selection: { ...EMPTY_SELECTION } }),

  // 請求預覽播放器跳轉到指定秒數（VideoPlayer 監聽 nonce 後換算成 frame 並 seekTo）
  seekTo: (seconds) => set((state) => ({ seekRequest: { seconds, nonce: state.seekRequest.nonce + 1 } })),

  // 由 VideoPlayer 回寫目前播放頭秒數（不進 Undo / 不影響 blueprint）
  setPlayhead: (seconds) => set({ playheadSeconds: seconds }),

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

  // ── 編輯器：持久化具名快照（版本檢查點，存後端、可跨重整還原）─────────────────

  // 載入專案的快照清單（左欄版本列表）
  loadSnapshots: async (folderName) => {
    if (!folderName) return;
    try {
      const snapshots = await apiService.listSnapshots(folderName);
      set({ snapshots });
    } catch (error) {
      console.warn('[Editor] 載入快照清單失敗：', error.response?.data?.detail || error.message);
    }
  },

  // 把當前 blueprint 存成具名快照；成功後把新 meta 置頂加入清單
  saveSnapshot: async (folderName, label) => {
    const blueprint = get().blueprint;
    if (!folderName || !blueprint) return;
    try {
      const meta = await apiService.saveSnapshot(folderName, label, blueprint);
      set((state) => ({ snapshots: [meta, ...state.snapshots] }));
    } catch (error) {
      alert(`儲存版本失敗：${error.response?.data?.detail || error.message}`);
    }
  },

  // 還原快照：取回該版 blueprint，先把當前推進 Undo 堆疊（還原本身可 Undo），再替換
  restoreSnapshot: async (folderName, snapshotId) => {
    if (!folderName) return;
    try {
      const result = await apiService.getSnapshot(folderName, snapshotId);
      set((state) => ({
        blueprint: result.blueprint,
        assetsRootUrl: result.assets_root_url,
        history: pushHistory(state.history, state.blueprint),
        selection: { ...EMPTY_SELECTION },
      }));
    } catch (error) {
      alert(`還原版本失敗：${error.response?.data?.detail || error.message}`);
    }
  },

  // 刪除快照並從清單移除
  deleteSnapshot: async (folderName, snapshotId) => {
    if (!folderName) return;
    try {
      await apiService.deleteSnapshot(folderName, snapshotId);
      set((state) => ({ snapshots: state.snapshots.filter((s) => s.id !== snapshotId) }));
    } catch (error) {
      alert(`刪除版本失敗：${error.response?.data?.detail || error.message}`);
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
      alert(`換曲失敗：${error.response?.data?.detail || error.message}`);
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
    set({ isProcessing: true, errorMsg: '', generationStage: null });

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
        enable_motion: state.enableMotion,
        previous_timeline: isRefinement && state.blueprint ? state.blueprint : null,
        music_strategy: state.musicStrategy,
        user_music_file: state.uploadedMusicFile || null,
        // 對話微調不重抓配樂（沿用上一版 bgm_track）；初始生成 / 重新生成才重挑配樂
        regenerate_music: !isRefinement,
        previous_bgm_track: isRefinement ? (state.blueprint?.bgm_track ?? null) : null,
      };

      // 改 async job：POST 立即回 { job_id }，不等生成跑完。設 generationJobId 觸發 EditorPage
      // 訂閱 WS 看 template ∥ music 兩分支即時進度；isProcessing 維持 true 直到 WS 終端事件。
      // 後端偵測到「已在生成中」會回既有 job_id（already_running），照樣附掛即可。
      const { job_id: jobId } = await apiService.generateTimeline(payload);
      set({ generationJobId: jobId });

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
          { role: 'error', content: `❌ 哎呀，生成失敗了：${backendError}` }
        ]
      }));
    }
  },

  // 接回進行中生成 job（EditorPage 重整 / 換專案掛載時用）：設 job_id 觸發 WS 訂閱，並標記處理中
  attachGeneration: (jobId) => set({ generationJobId: jobId, isProcessing: true, errorMsg: '' }),

  /**
   * WS 進度事件處理（Observer 回呼）：stage 事件更新階段文案；終端事件套用結果 / 報錯並收尾。
   * 結果直接取自 job_finished 的 payload.result（run_workflow 回傳）；重連時 replay buffer 亦補送此事件。
   * @param {object} event 後端 ProgressEvent（event_type / asset_id / stage_name / payload / error）
   */
  onGenerationEvent: (event) => {
    const type = event?.event_type;
    if (type === 'job_finished') {
      const result = event?.payload?.result || {};
      // AI 結果推進 Undo 快照（可一鍵還原，政策 C 安全網）；時間軸結構可能整個改變，故清空選取避免錯位
      set((prev) => ({
        blueprint: result.blueprint ?? prev.blueprint,
        assetsRootUrl: result.assets_root_url ?? prev.assetsRootUrl,
        isProcessing: false,
        generationJobId: null,
        generationStage: null,
        history: result.blueprint ? pushHistory(prev.history, prev.blueprint) : prev.history,
        selection: { ...EMPTY_SELECTION },
        chatHistory: [
          ...prev.chatHistory,
          { role: 'system', content: '✅ 導演已更新劇本與時間軸！請查看左側預覽。' }
        ]
      }));
      return;
    }
    if (type === 'job_error') {
      const msg = event?.error || event?.payload?.error || '生成過程發生錯誤';
      set((prev) => ({
        isProcessing: false,
        generationJobId: null,
        generationStage: null,
        errorMsg: `生成失敗：${msg}`,
        chatHistory: [
          ...prev.chatHistory,
          { role: 'error', content: `❌ 哎呀，生成失敗了：${msg}` }
        ]
      }));
      return;
    }
    // 非終端：以最近一個 stage 起點更新階段文案（兩分支交錯到達屬正常）
    if (type === 'stage_start') {
      const label = stageLabel(event);
      if (label) set({ generationStage: label });
    }
  },

  /**
   * WS 在「未收到終端事件」下異常斷線（如後端重啟）：清處理中旗標，並退回讀已落地的磁碟藍圖兜結果
   * （worker thread 不受 client 斷線影響，仍會跑完落地；見 docs §10.9）。
   */
  onGenerationClosed: async () => {
    const { default: useProjectStore } = await import('./useProjectStore');
    const folderName = useProjectStore.getState().currentProject?.name;
    set({ isProcessing: false, generationJobId: null, generationStage: null });
    if (!folderName) return;
    try {
      const data = await apiService.fetchBlueprint(folderName);
      if (data?.blueprint) {
        set((prev) => ({
          blueprint: data.blueprint,
          assetsRootUrl: data.assets_root_url ?? prev.assetsRootUrl,
        }));
      }
    } catch {
      // 尚未落地 / 404：維持現狀（SetupView），不報錯
    }
  }
}));

export default useBlueprintStore;
