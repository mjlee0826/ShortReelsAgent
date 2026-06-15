import { apiService } from '../../services/api.service';
import { extractErrorMessage } from '../../utils/errorMessage';
import { PROGRESS_EVENT } from '../../constants/events';
import { migrateBlueprintTextOverlays } from '../../utils/textOverlay';
import { EMPTY_SELECTION, pushHistory } from './history';

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
 * 生成生命週期 slice：生成 / 重新生成的提交、進行中狀態、WS 進度事件處理與對話歷史。
 * @param {Function} set zustand set
 * @param {Function} get zustand get
 * @returns {object} slice 片段
 */
export function createGenerationSlice(set, get) {
  return {
    // --- 生成結果狀態 ---
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
    // 導演 agentic loop 即時思考串流（累積；每次新工具動作清空）；無則空字串
    liveThinking: '',
    // 導演 ask_user 待回答（{ question, options }）；非 null 時聊天框送出走 resume（B2）
    pendingClarification: null,

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
        const loaded = migrateBlueprintTextOverlays(result.blueprint);
        set({
          // 載入時把 legacy per-clip 字幕一次遷移成獨立字幕軌（與渲染 / 編輯一致）
          blueprint: loaded,
          // 剛從磁碟讀回即落地版，設為 autosave 去重基準（避免載入後立刻回寫同份）
          persistedBlueprint: loaded,
          assetsRootUrl: result.assets_root_url,
          selection: { ...EMPTY_SELECTION },
          history: { past: [], future: [] },
          isLoadingBlueprint: false,
        });
      } catch (error) {
        // 404 = 尚未生成過，保持 SetupView；其餘錯誤留下可見軌跡
        if (error.response?.status !== 404) {
          console.warn('[Editor] 載入既有藍圖失敗：', extractErrorMessage(error));
        }
        set({ isLoadingBlueprint: false });
      }
    },

    // 跳轉素材頁後清掉旗標，避免重複導航
    clearAssetsRedirect: () => set({ redirectToAssetsProject: null }),

    submitPrompt: async (isRefinement = false, refinementPrompt = '') => {
      set({ isProcessing: true, errorMsg: '', generationStage: null });

      const state = get();

      // 從 useProjectStore 取得當前專案名稱（避免 store 循環依賴，以 getState 直接讀取）
      const { default: useProjectStore } = await import('../useProjectStore');
      const currentProject = useProjectStore.getState().currentProject;
      const folderName = currentProject?.name || '';

      if (!folderName) {
        set({ isProcessing: false, errorMsg: '請先選定一個專案再生成影片。' });
        return;
      }

      // 初始生成的指令：優先用聊天輸入（對話式入口），否則用表單 userPrompt
      const initialPrompt = refinementPrompt || state.userPrompt;

      // 管理對話紀錄
      if (isRefinement && refinementPrompt) {
        set((prev) => ({
          chatHistory: [...prev.chatHistory, { role: 'user', content: refinementPrompt }]
        }));
      } else if (!isRefinement) {
        set({
          chatHistory: [{ role: 'user', content: `🎬 初始指令：\n${initialPrompt}` }]
        });
      }

      try {
        const payload = {
          asset_folder_name: folderName,
          user_prompt: isRefinement ? refinementPrompt : initialPrompt,
          template_source: state.templateSource || null,
          enable_subtitles: state.enableSubtitles,
          enable_filters: state.enableFilters,
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
        // 其餘錯誤：統一抽出可讀訊息（detail 可能是字串或 { code, message } 物件）
        const backendError = extractErrorMessage(error);
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
     * B2：使用者回答導演的提問（ask_user）→ 打 /generate/resume 續跑，附掛新 job 的 WS。
     * @param {string} answer 使用者的回答
     */
    submitClarificationAnswer: async (answer) => {
      if (!answer || !answer.trim()) return;
      const { default: useProjectStore } = await import('../useProjectStore');
      const folderName = useProjectStore.getState().currentProject?.name || '';
      if (!folderName) return;
      set((prev) => ({
        pendingClarification: null,
        isProcessing: true,
        errorMsg: '',
        chatHistory: [...prev.chatHistory, { role: 'user', content: `📝 ${answer}` }],
      }));
      try {
        const { job_id: jobId } = await apiService.resumeGeneration(folderName, answer);
        set({ generationJobId: jobId });
      } catch (error) {
        const backendError = extractErrorMessage(error);
        set((prev) => ({
          isProcessing: false,
          errorMsg: `續跑失敗：${backendError}`,
          chatHistory: [...prev.chatHistory, { role: 'error', content: `❌ 續跑失敗：${backendError}` }],
        }));
      }
    },

    /**
     * WS 進度事件處理（Observer 回呼）：stage 事件更新階段文案；終端事件套用結果 / 報錯並收尾。
     * 結果直接取自 job_finished 的 payload.result（run_workflow 回傳）；重連時 replay buffer 亦補送此事件。
     * @param {object} event 後端 ProgressEvent（event_type / asset_id / stage_name / payload / error）
     */
    onGenerationEvent: (event) => {
      const type = event?.event_type;
      if (type === PROGRESS_EVENT.JOB_FINISHED) {
        const result = event?.payload?.result || {};
        // B2：導演中途提問 → job 結束但無藍圖（status=awaiting_input）；保留 pendingClarification
        //（由 CLARIFICATION_NEEDED 事件設好），等使用者於聊天框回答後走 resume。
        if (result.status === 'awaiting_input') {
          set({ isProcessing: false, generationJobId: null, generationStage: null, liveThinking: '' });
          return;
        }
        // AI 結果推進 Undo 快照（可一鍵還原，政策 C 安全網）；時間軸結構可能整個改變，故清空選取避免錯位
        set((prev) => {
          const nextBlueprint = result.blueprint
            ? migrateBlueprintTextOverlays(result.blueprint)
            : prev.blueprint;
          return {
            blueprint: nextBlueprint,
            // run_workflow 已把這份結果寫入 PHASE4，設為 autosave 去重基準（避免生成完又回寫同份）
            persistedBlueprint: result.blueprint ? nextBlueprint : prev.persistedBlueprint,
            assetsRootUrl: result.assets_root_url ?? prev.assetsRootUrl,
            isProcessing: false,
            generationJobId: null,
            generationStage: null,
            liveThinking: '',
            pendingClarification: null,
            history: result.blueprint ? pushHistory(prev.history, prev.blueprint) : prev.history,
            selection: { ...EMPTY_SELECTION },
            chatHistory: [
              ...prev.chatHistory,
              { role: 'system', content: '✅ 導演已更新劇本與時間軸！請查看左側預覽。' }
            ]
          };
        });
        return;
      }
      if (type === PROGRESS_EVENT.JOB_ERROR) {
        const msg = event?.error || event?.payload?.error || '生成過程發生錯誤';
        set((prev) => ({
          isProcessing: false,
          generationJobId: null,
          generationStage: null,
          liveThinking: '',
          pendingClarification: null,
          errorMsg: `生成失敗：${msg}`,
          chatHistory: [
            ...prev.chatHistory,
            { role: 'error', content: `❌ 哎呀，生成失敗了：${msg}` }
          ]
        }));
        return;
      }
      // 導演 agentic loop：思考串流（累積成「思考中」泡泡）
      if (type === PROGRESS_EVENT.DIRECTOR_THINKING_DELTA) {
        const delta = event?.payload?.thinking || '';
        if (delta) set((prev) => ({ liveThinking: prev.liveThinking + delta }));
        return;
      }
      // 導演 agentic loop：工具呼叫旁白 → 清空 thinking、把「導演做了什麼」記進對話軌跡
      if (type === PROGRESS_EVENT.DIRECTOR_TOOL_CALL) {
        const summary = event?.payload?.summary || event?.payload?.tool_name || '';
        set((prev) => ({
          liveThinking: '',
          chatHistory: summary
            ? [...prev.chatHistory, { role: 'tool', content: `🔧 ${summary}` }]
            : prev.chatHistory,
        }));
        return;
      }
      // 導演 agentic loop：中途提問（ask_user）→ 設待回答、把問題顯示在對話
      if (type === PROGRESS_EVENT.DIRECTOR_CLARIFICATION_NEEDED) {
        const question = event?.payload?.question || '';
        const options = event?.payload?.options || [];
        set((prev) => ({
          liveThinking: '',
          pendingClarification: { question, options },
          chatHistory: [...prev.chatHistory, { role: 'clarification', content: question, options }],
        }));
        return;
      }
      // 非終端：以最近一個 stage 起點更新階段文案（兩分支交錯到達屬正常）
      if (type === PROGRESS_EVENT.STAGE_START) {
        const label = stageLabel(event);
        if (label) set({ generationStage: label });
      }
    },

    /**
     * WS 在「未收到終端事件」下異常斷線（如後端重啟）：清處理中旗標，並退回讀已落地的磁碟藍圖兜結果
     * （worker thread 不受 client 斷線影響，仍會跑完落地；見 docs §10.9）。
     */
    onGenerationClosed: async () => {
      const { default: useProjectStore } = await import('../useProjectStore');
      const folderName = useProjectStore.getState().currentProject?.name;
      set({ isProcessing: false, generationJobId: null, generationStage: null });
      if (!folderName) return;
      try {
        const data = await apiService.fetchBlueprint(folderName);
        if (data?.blueprint) {
          const recovered = migrateBlueprintTextOverlays(data.blueprint);
          set((prev) => ({
            blueprint: recovered,
            // 從磁碟兜回即落地版，設為 autosave 去重基準
            persistedBlueprint: recovered,
            assetsRootUrl: data.assets_root_url ?? prev.assetsRootUrl,
          }));
        }
      } catch {
        // 尚未落地 / 404：維持現狀（SetupView），不報錯
      }
    },
  };
}
