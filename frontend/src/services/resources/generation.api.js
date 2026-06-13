import { apiClient } from '../apiClient';

/**
 * 生成相關 API：劇本生成、讀回藍圖、雲端算圖、換曲與自訂 BGM 上傳。
 * 所有方法皆為薄包裝（送請求 → 回 response.data）；錯誤由 interceptor 與呼叫端負責。
 */
export const generationApi = {
  async generateTimeline(payload) {
    const response = await apiClient.post('/api/generate', payload);
    return response.data;
  },

  // 讀回專案先前生成並落地的最終藍圖，回傳 { blueprint, assets_root_url }。
  // 尚未生成過時後端回 404，呼叫端應視為「無已存結果」而非錯誤。
  async fetchBlueprint(projectName) {
    const response = await apiClient.get(`/api/projects/${projectName}/blueprint`);
    return response.data;
  },

  // 送出藍圖至後端雲端算圖，回傳 MP4 Blob。
  // 刻意走 apiClient（axios）而非裸 fetch：interceptor 會自動附上 Authorization token，
  // 修掉先前裸 fetch 缺 token 導致 render_mp4 被 verify_token 擋下的問題。
  async renderMp4(blueprint, assetsRootUrl) {
    const response = await apiClient.post(
      '/api/render_mp4',
      { blueprint, assets_root_url: assetsRootUrl },
      { responseType: 'blob' }
    );
    return response.data;
  },

  // music-only 換曲：只重挑配樂、保留時間軸，回傳 { bgm_track }
  async changeMusic(payload) {
    const response = await apiClient.post('/api/change_music', payload);
    return response.data;
  },

  // 上傳自訂 BGM 至指定素材資料夾，回傳 { filename: "..." }
  async uploadMusic(folderName, file) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post(
      `/api/upload_music/${folderName}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
    return response.data;
  },
};
