/**
 * Observer Pattern (Zustand)：使用者全域設定狀態管理
 *
 * 管理設定頁的讀取與部分更新（建立後是否自動分析、素材預設策略）。
 * 採「變更即存」：updateSetting 直接送 PATCH，並以後端回傳的完整設定回填 store，
 * 確保前端狀態與後端持久化結果一致。
 */
import { create } from 'zustand';
import { apiService } from '../services/api.service';
import { extractErrorMessage } from '../utils/errorMessage';

// 設定預設值（與後端 UserSettings 預設對齊；後端缺檔時亦回這組值）
const DEFAULT_SETTINGS = {
  auto_analyze_on_create: false,
  default_asset_strategy: 'simple',
  preference_capture_enabled: true,
};

const useSettingsStore = create((set, get) => ({
  // --- 狀態 ---
  settings: DEFAULT_SETTINGS,
  isLoading: false,
  isSaving: false,
  errorMsg: '',

  // --- 操作 ---

  // 從後端載入使用者全域設定
  fetchSettings: async () => {
    set({ isLoading: true, errorMsg: '' });
    try {
      const settings = await apiService.fetchSettings();
      set({ settings, isLoading: false });
    } catch (error) {
      const msg = extractErrorMessage(error);
      set({ errorMsg: `載入設定失敗：${msg}`, isLoading: false });
    }
  },

  // 部分更新設定（patch 只含變更欄位）；以後端回傳的完整設定回填，避免前後端不一致
  updateSetting: async (patch) => {
    set({ isSaving: true, errorMsg: '' });
    // 樂觀更新：先本地反映，讓開關 / 下拉立即回饋；失敗時於 catch 還原
    const prev = get().settings;
    set({ settings: { ...prev, ...patch } });
    try {
      const settings = await apiService.updateSettings(patch);
      set({ settings, isSaving: false });
    } catch (error) {
      const msg = extractErrorMessage(error);
      set({ settings: prev, isSaving: false, errorMsg: `儲存設定失敗：${msg}` });
    }
  },

  clearError: () => set({ errorMsg: '' }),
}));

export default useSettingsStore;
