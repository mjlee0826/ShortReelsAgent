import axios from 'axios';

// 指向你的 FastAPI 後端
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5174';

class DirectorApiService {
  async generateTimeline(payload) {
    try {
      const response = await axios.post(`${BACKEND_URL}/api/generate`, payload);
      return response.data;
    } catch (error) {
      console.error("[API Error] 劇本生成失敗:", error);
      throw error;
    }
  }

  // 上傳自訂 BGM 至指定素材資料夾，回傳 { filename: "..." }
  async uploadMusic(folderName, file) {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await axios.post(
        `${BACKEND_URL}/api/upload_music/${folderName}`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );
      return response.data;
    } catch (error) {
      console.error("[API Error] 音訊上傳失敗:", error);
      throw error;
    }
  }
}

export const apiService = new DirectorApiService();