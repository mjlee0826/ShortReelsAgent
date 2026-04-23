import { create } from 'zustand';
import { apiService } from '../services/api.service';

const useBlueprintStore = create((set, get) => ({
    assetFolderName: '',
    userPrompt: '',
    templateSource: '',
    enableSubtitles: true,
    enableFilters: true,
    videoStrategy: '1',    

    blueprint: null,
    assetsRootUrl: '',
    isProcessing: false,
    errorMsg: '',
    
    // 【新增】對話歷史紀錄
    chatHistory: [],

    updateForm: (key, value) => set({ [key]: value }),

    submitPrompt: async (isRefinement = false, refinementPrompt = "") => {
        set({ isProcessing: true, errorMsg: '' });
        
        const state = get();

        // --- 【新增】管理對話紀錄邏輯 ---
        if (isRefinement && refinementPrompt) {
            // 如果是微調，把使用者的話加入紀錄
            set((prev) => ({
                chatHistory: [
                    ...prev.chatHistory, 
                    { role: 'user', content: refinementPrompt }
                ]
            }));
        } else if (!isRefinement) {
            // 如果是全新生成，清空歷史紀錄，並把初始指令當作第一句話
            set({
                chatHistory: [
                    { role: 'user', content: `🎬 初始指令：\n${state.userPrompt}` }
                ]
            });
        }
        // ------------------------------

        try {
            const payload = {
                asset_folder_name: state.assetFolderName,
                user_prompt: isRefinement ? refinementPrompt : state.userPrompt,
                template_source: state.templateSource || null,
                enable_subtitles: state.enableSubtitles,
                enable_filters: state.enableFilters,
                video_strategy: state.videoStrategy,
                previous_timeline: isRefinement && state.blueprint ? state.blueprint : null
            };

            const result = await apiService.generateTimeline(payload);
            
            set((prev) => ({ 
                blueprint: result.blueprint,
                assetsRootUrl: result.assets_root_url,
                isProcessing: false,
                // 【新增】AI 成功完成任務後，給予系統回覆
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
                // 【新增】如果發生錯誤，AI 也要在對話框裡回報
                chatHistory: [
                    ...prev.chatHistory,
                    { role: 'error', content: `❌ 哎呀，修改失敗了：${backendError}` }
                ]
            }));
        }
    }
}));

export default useBlueprintStore;