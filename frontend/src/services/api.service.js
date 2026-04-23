import axios from 'axios';

// 指向你的 FastAPI 後端
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5174';

class DirectorApiService {
  async generateTimeline(payload) {
    try {
      // payload 包含 folder, prompt, template, toggles 等
      const response = await axios.post(`${BACKEND_URL}/generate`, payload);
      return response.data; 
    } catch (error) {
      console.error("[API Error] 劇本生成失敗:", error);
      throw error;
    }
  }
}

export const apiService = new DirectorApiService();