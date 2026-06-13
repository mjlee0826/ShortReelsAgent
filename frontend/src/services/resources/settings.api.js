import { apiClient } from '../apiClient';

/**
 * 全域使用者設定（Settings）API。
 */
export const settingsApi = {
  // 讀取目前登入使用者的全域設定（自動分析開關 / 預設策略），缺檔時後端回安全預設
  async fetchSettings() {
    const response = await apiClient.get('/api/settings');
    return response.data;
  },

  // 部分更新全域設定（只送有變更的欄位），回傳更新後的完整設定
  async updateSettings(partial) {
    const response = await apiClient.patch('/api/settings', partial);
    return response.data;
  },
};
