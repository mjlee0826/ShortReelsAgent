/**
 * Facade Pattern：後端 API 存取層
 *
 * 以單一 axios 實例統一管理基礎 URL 與認證 header。
 * auth interceptor 由 AuthInterceptorSetup 元件在 React tree 初始化時注入，
 * 讓 Zustand store 可在 React context 外直接使用此 service。
 */
import axios from 'axios';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5174';

// 所有 API 呼叫共用的 axios 實例
export const apiClient = axios.create({ baseURL: BACKEND_URL });

class DirectorApiService {
  async generateTimeline(payload) {
    try {
      const response = await apiClient.post('/api/generate', payload);
      return response.data;
    } catch (error) {
      console.error('[API Error] 劇本生成失敗:', error);
      throw error;
    }
  }

  // 上傳自訂 BGM 至指定素材資料夾，回傳 { filename: "..." }
  async uploadMusic(folderName, file) {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await apiClient.post(
        `/api/upload_music/${folderName}`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );
      return response.data;
    } catch (error) {
      console.error('[API Error] 音訊上傳失敗:', error);
      throw error;
    }
  }

  async fetchProjects() {
    const response = await apiClient.get('/api/projects');
    return response.data;
  }

  async createProject(displayName) {
    const response = await apiClient.post('/api/projects', { display_name: displayName });
    return response.data;
  }

  async deleteProject(projectName) {
    await apiClient.delete(`/api/projects/${projectName}`);
  }
}

export const apiService = new DirectorApiService();
