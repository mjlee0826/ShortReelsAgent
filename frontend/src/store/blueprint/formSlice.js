import { apiService } from '../../services/api.service';
import { extractErrorMessage } from '../../utils/errorMessage';
import { MUSIC_STRATEGY_DEFAULT } from '../../constants/music';

/**
 * 表單與音訊上傳 slice：生成表單欄位與自訂 BGM 上傳狀態 / 動作。
 * @param {Function} set zustand set
 * @returns {object} slice 片段
 */
export function createFormSlice(set) {
  return {
    // --- 表單狀態 ---
    userPrompt: '',
    templateSource: '',
    enableSubtitles: true,
    enableFilters: true,
    musicStrategy: MUSIC_STRATEGY_DEFAULT,

    // --- 音訊上傳狀態 ---
    uploadedMusicFile: null,
    isUploadingMusic: false,

    updateForm: (key, value) => set({ [key]: value }),

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
        const msg = extractErrorMessage(error);
        alert(`音訊上傳失敗：${msg}`);
        set({ isUploadingMusic: false });
      }
    },

    clearUploadedMusic: () => set({ uploadedMusicFile: null }),
  };
}
