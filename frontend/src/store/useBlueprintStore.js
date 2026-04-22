import { create } from 'zustand';
import { apiService } from '../services/api.service';

const useBlueprintStore = create((set, get) => ({
    // --- 表單與狀態 ---
    assetFolderName: '',
    userPrompt: '',
    templateSource: '',
    enableSubtitles: true,
    enableFilters: true,
    
    // --- 產出結果 ---
    blueprint: null,       // AI 產出的劇本 JSON
    assetsRootUrl: '',     // 後端靜態檔案的路徑
    isProcessing: false,   // 讀取狀態
    errorMsg: '',

    // --- 更新表單的方法 ---
    updateForm: (key, value) => set({ [key]: value }),

    // --- 核心方法：發送指令給大腦 ---
    submitPrompt: async (isRefinement = false, refinementPrompt = "") => {
        set({ isProcessing: true, errorMsg: '' });
        
        try {
        const state = get();
        
        // 組合 API 請求格式 (對齊 FastAPI 的 GenerateRequest)
        const payload = {
            asset_folder_name: state.assetFolderName,
            // 如果是微調，就用微調的 prompt；否則用原本表單的 prompt
            user_prompt: isRefinement ? refinementPrompt : state.userPrompt,
            template_source: state.templateSource || null,
            enable_subtitles: state.enableSubtitles,
            enable_filters: state.enableFilters,
            // 如果是微調，把當前的劇本傳回去當作參考
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
                errorMsg: '生成失敗，請檢查後端伺服器是否正常運作。' + error,
                isProcessing: false 
            });
        }
    }
    }));

export default useBlueprintStore;