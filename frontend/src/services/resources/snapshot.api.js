import { apiClient } from '../apiClient';

/**
 * 編輯器具名快照（版本檢查點）API。
 */
export const snapshotApi = {
  // 列出專案的所有快照 meta（不含 blueprint），回傳 [{ id, label, created_at }]
  async listSnapshots(projectName) {
    const response = await apiClient.get(`/api/projects/${projectName}/snapshots`);
    return response.data;
  },

  // 把當前 blueprint 存成具名快照，回傳新快照 meta
  async saveSnapshot(projectName, label, blueprint) {
    const response = await apiClient.post(`/api/projects/${projectName}/snapshots`, { label, blueprint });
    return response.data;
  },

  // 以 id 取回快照供還原，回傳 { blueprint, assets_root_url }
  async getSnapshot(projectName, snapshotId) {
    const response = await apiClient.get(`/api/projects/${projectName}/snapshots/${snapshotId}`);
    return response.data;
  },

  // 刪除指定快照
  async deleteSnapshot(projectName, snapshotId) {
    await apiClient.delete(`/api/projects/${projectName}/snapshots/${snapshotId}`);
  },
};
