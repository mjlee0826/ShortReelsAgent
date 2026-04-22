import axios from 'axios';

// 指向你的 FastAPI 後端
const API_BASE_URL = 'http://localhost:8000/api';

class DirectorApiService {
  async generateTimeline(payload) {
    try {
      // payload 包含 folder, prompt, template, toggles 等
      const response = await axios.post(`${API_BASE_URL}/generate`, payload);
      return response.data; 
    } catch (error) {
      console.error("[API Error] 劇本生成失敗:", error);
      throw error;
    }
  }
}

export const apiService = new DirectorApiService();