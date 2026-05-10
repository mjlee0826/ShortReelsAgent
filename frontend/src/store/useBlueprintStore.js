import { create } from 'zustand';
import { apiService } from '../services/api.service';

const useBlueprintStore = create((set, get) => ({
    // --- 表單狀態 ---
    assetFolderName: '',
    userPrompt: '',
    templateSource: '',
    enableSubtitles: true,
    enableFilters: true,
    videoStrategy: '1',
    musicStrategy: 'search_copyright',  // 配樂策略：由使用者在表單明確選擇

    // --- 音訊上傳狀態 ---
    uploadedMusicFile: null,    // 已上傳至 assets 資料夾的音訊檔名
    isUploadingMusic: false,    // 音訊上傳中的 loading 狀態

    // --- 生成結果狀態 ---
    blueprint: null,
    assetsRootUrl: '',
    isProcessing: false,
    errorMsg: '',

    // --- 對話歷史紀錄 ---
    chatHistory: [],

    updateForm: (key, value) => set({ [key]: value }),

    // 上傳自訂 BGM 至素材資料夾，成功後記錄檔名
    uploadMusic: async (folderName, file) => {
        if (!folderName) {
            alert('請先填寫素材資料夾名稱，再上傳音樂。');
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

    // 清除已上傳的音訊，讓下次生成改回搜尋策略
    clearUploadedMusic: () => set({ uploadedMusicFile: null }),

    submitPrompt: async (isRefinement = false, refinementPrompt = "") => {
        set({ isProcessing: true, errorMsg: '' });

        const state = get();

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
                asset_folder_name: state.assetFolderName,
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
