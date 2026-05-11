/**
 * Observer Pattern (Zustand)：影片藍圖狀態管理
 *
 * 管理目前開啟專案的生成表單、藍圖輸出與對話歷史紀錄。
 * 素材資料夾名稱改由 useProjectStore.currentProject.name 提供，
 * 不再由此 store 持有。
 */
import { create } from 'zustand';
import { apiService } from '../services/api.service';

const useBlueprintStore = create((set, get) => ({
  // --- 表單狀態 ---
  userPrompt: '',
  templateSource: '',
  enableSubtitles: true,
  enableFilters: true,
  videoStrategy: '1',
  musicStrategy: 'search_copyright',

  // --- 音訊上傳狀態 ---
  uploadedMusicFile: null,
  isUploadingMusic: false,

  // --- 生成結果狀態 ---
  blueprint: null,
  assetsRootUrl: '',
  isProcessing: false,
  errorMsg: '',

  // --- 對話歷史紀錄 ---
  chatHistory: [],

  updateForm: (key, value) => set({ [key]: value }),

  // 重置所有輸出狀態（切換專案時由 useProjectStore 觸發）
  reset: () => set({
    blueprint: null,
    assetsRootUrl: '',
    isProcessing: false,
    errorMsg: '',
    chatHistory: [],
    uploadedMusicFile: null,
    userPrompt: '',
    templateSource: '',
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
        video_strategy: state.videoStrategy,
        previous_timeline: isRefinement && state.blueprint ? state.blueprint : null,
        music_strategy: state.musicStrategy,
        user_music_file: state.uploadedMusicFile || null,
      };

      const result = await apiService.generateTimeline(payload);

      set((prev) => ({
        blueprint: result.blueprint,
        assetsRootUrl: result.assets_root_url,
        isProcessing: false,
        chatHistory: [
          ...prev.chatHistory,
          { role: 'system', content: '✅ 導演已更新劇本與時間軸！請查看左側預覽。' }
        ]
      }));

    } catch (error) {
      const backendError = error.response?.data?.detail || error.message || String(error);
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
