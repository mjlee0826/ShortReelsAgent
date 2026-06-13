import { apiClient } from '../apiClient';

/**
 * 素材管理（Asset Management UI）API。
 */
export const assetApi = {
  // 列出某專案的所有素材檢視（狀態 / 策略 / dirty / 縮圖 URL）
  async fetchAssets(projectName) {
    const response = await apiClient.get(`/api/projects/${projectName}/assets`);
    return response.data;
  },

  // 取得單一素材的完整詳情（AssetView + 原始媒體 URL + Phase 1 完整感知 metadata），供詳情彈窗使用
  // 素材身分為含 / 的 relpath，故以 query 參數 path 傳遞（避免 path param 的 %2F 坑）
  async fetchAssetDetail(projectName, path) {
    const response = await apiClient.get(
      `/api/projects/${projectName}/asset-detail`,
      { params: { path } }
    );
    return response.data;
  },

  // 更新單一素材（以 relpath path 識別）的 Simple/Complex 策略並標記 dirty，回傳更新後的素材檢視
  async setAssetStrategy(projectName, path, strategy) {
    const response = await apiClient.patch(
      `/api/projects/${projectName}/asset-strategy`,
      { path, strategy }
    );
    return response.data;
  },

  // 強制重跑 Phase 1（assetIds=null 代表全部），回傳 { job_id } 供訂閱 WebSocket 進度
  async reanalyzeAssets(projectName, assetIds = null) {
    const response = await apiClient.post(
      `/api/projects/${projectName}/reanalyze`,
      { asset_ids: assetIds }
    );
    return response.data;
  },

  // 開始生成：套用逐檔策略後只重跑 dirty+未處理素材的 Phase 1，回傳 { job_id }
  async startAssetGenerate(projectName, assetStrategies = null) {
    const response = await apiClient.post(
      `/api/projects/${projectName}/generate`,
      { asset_strategies: assetStrategies }
    );
    return response.data;
  },
};
