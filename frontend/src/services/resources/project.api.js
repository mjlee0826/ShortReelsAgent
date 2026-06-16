import { apiClient } from '../apiClient';

/**
 * 專案 API：清單、建立（Google Drive 來源）、同步、進度查詢與刪除。
 */
export const projectApi = {
  async fetchProjects() {
    const response = await apiClient.get('/api/projects');
    return response.data;
  },

  // 以 Google Drive 公開資料夾連結建立雲端來源專案，後端會於背景啟動首次同步（下載素材 + Phase 1）
  async createProjectFromDrive(displayName, sourceUrl) {
    const response = await apiClient.post('/api/projects/from-drive', {
      display_name: displayName,
      source_url: sourceUrl,
    });
    return response.data;
  },

  // 以本機資料夾建立「本機來源」專案：multipart 上傳整夾媒體，後端存入 raw/ 並依設定背景跑 Phase 1
  async createProjectFromFolder(displayName, files) {
    const form = new FormData();
    form.append('display_name', displayName);
    // 每個檔案以同一欄位名 files 附加（後端收成 list[UploadFile]）；保留原檔名供去重
    files.forEach((file) => form.append('files', file, file.name));
    // 傳 FormData 時 axios 會自動帶 multipart/form-data 與 boundary，無需手動設 Content-Type
    const response = await apiClient.post('/api/projects/from-folder', form);
    return response.data;
  },

  // 手動觸發一次雲端同步（阻塞：下載新素材 + 增量 Phase 1），回傳 SyncReport
  async syncProject(projectName) {
    const response = await apiClient.post(`/api/projects/${projectName}/sync`);
    return response.data;
  },

  // 查詢專案 Phase 1 進度狀態與進行中 job_id（素材頁掛載時據此訂閱 WS 看背景同步的即時進度）
  // 回傳 { phase1_status, active_job_id }；無進行中 job（或後端重啟孤兒）時 active_job_id 為 null
  async fetchPhase1Progress(projectName) {
    const response = await apiClient.get(`/api/projects/${projectName}/phase1-progress`);
    return response.data;
  },

  // 查詢專案進行中的 blueprint 生成 job_id（編輯頁掛載 / 重整後據此訂閱 WS 接回即時進度）
  // 回傳 { active_job_id }；無進行中 job（或後端重啟孤兒）時為 null，呼叫端改載已落地的磁碟藍圖
  async fetchGenerationProgress(projectName) {
    const response = await apiClient.get(`/api/projects/${projectName}/generation-progress`);
    return response.data;
  },

  async deleteProject(projectName) {
    await apiClient.delete(`/api/projects/${projectName}`);
  },
};
