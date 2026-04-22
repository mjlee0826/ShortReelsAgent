import { create } from 'zustand';
import { apiService } from '../services/api.service';

const useBlueprintStore = create((set, get) => ({
    // --- 1. 新增 videoStrategy 狀態 ---
    assetFolderName: '',
    userPrompt: '',
    templateSource: '',
    enableSubtitles: true,
    enableFilters: true,
    videoStrategy: '2',    // 預設值為 '2' (全部一般影片)

    blueprint: null,
    assetsRootUrl: '',
    isProcessing: false,
    errorMsg: '',

    updateForm: (key, value) => set({ [key]: value }),

    submitPrompt: async (isRefinement = false, refinementPrompt = "") => {
        set({ isProcessing: true, errorMsg: '' });
        
        try {
        const state = get();
        
        // --- 2. 在 Payload 中加入 video_strategy ---
        const payload = {
            asset_folder_name: state.assetFolderName,
            user_prompt: isRefinement ? refinementPrompt : state.userPrompt,
            template_source: state.templateSource || null,
            enable_subtitles: state.enableSubtitles,
            enable_filters: state.enableFilters,
            video_strategy: state.videoStrategy, // 將前端選擇傳給後端
            previous_timeline: isRefinement && state.blueprint ? state.blueprint.timeline : null
        };

        const result = await apiService.generateTimeline(payload);
        
        set({ 
            blueprint: result.blueprint,
            assetsRootUrl: result.assets_root_url,
            isProcessing: false 
        });
        
        } catch (error) {
        set({ 
            errorMsg: '生成失敗，請檢查後端伺服器與 API Key。' + error,
            isProcessing: false 
        });
        }
    }
}));

export default useBlueprintStore;