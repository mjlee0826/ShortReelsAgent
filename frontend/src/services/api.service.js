/**
 * Facade Pattern：後端 API 存取層
 *
 * 以單一 axios 實例統一管理基礎 URL 與認證 header。
 *
 * 認證 interceptor 在「模組載入時」即註冊（而非 React effect 內），
 * 杜絕「子元件 effect 早於父元件 effect」的競態 —— 否則 ProjectDashboard 的
 * fetchProjects 可能在 interceptor 尚未掛上時就送出，導致請求缺少 Authorization
 * header 而被後端 401。
 *
 * interceptor 需要 Logto 的 getAccessToken / signOut，但它們由 React hook 提供，
 * 無法在 React context 之外直接取得。因此以 Auth Bridge（Adapter Pattern）橋接：
 * AuthInterceptorSetup 於 render 階段呼叫 setAuthBridge 注入這兩個方法。
 */
import axios from 'axios';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5174';
// 換取 access token 時指定的 API resource（須與後端 LOGTO_AUDIENCE 對應）
const API_RESOURCE = import.meta.env.VITE_LOGTO_API_RESOURCE;

// 所有 API 呼叫共用的 axios 實例
export const apiClient = axios.create({ baseURL: BACKEND_URL });

/**
 * Auth Bridge（Adapter Pattern）：
 * 讓模組層級的 axios interceptor 能取得 React context 內的 Logto 方法。
 * 由 AuthInterceptorSetup 在 render 階段注入，確保早於任何元件的資料請求。
 */
const _authBridge = {
  getAccessToken: null, // (resource: string) => Promise<string | undefined>
  signOut: null,        // (redirectUri: string) => Promise<void>
};

/** 由 AuthInterceptorSetup 在 render 階段呼叫，注入最新的 Logto 方法。 */
export function setAuthBridge({ getAccessToken, signOut }) {
  _authBridge.getAccessToken = getAccessToken;
  _authBridge.signOut = signOut;
}

// ── Request interceptor：有 token 就附上 ──────────────────────────────────────
apiClient.interceptors.request.use(async (config) => {
  // Bridge 尚未注入（極早期請求 / 未登入）：照常送出，交由後端決定
  if (!_authBridge.getAccessToken) return config;
  try {
    const token = await _authBridge.getAccessToken(API_RESOURCE);
    if (token) config.headers.Authorization = `Bearer ${token}`;
  } catch (err) {
    // 換不到 token（未登入 / refresh token 過期）：不再靜默吞掉，留下可見軌跡，
    // 方便辨別「請求缺 token」與「token 被後端拒」兩種 401 成因
    console.warn('[Auth] 取得 access token 失敗，請求將以未認證狀態送出：', err?.message || err);
  }
  return config;
});

// ── Response interceptor：401 換新 token 重打，refresh 也失效則登出 ───────────
apiClient.interceptors.response.use(
  (res) => res,
  async (error) => {
    const canRetry =
      error.response?.status === 401 &&
      !error.config?._retry &&
      _authBridge.getAccessToken;

    if (canRetry) {
      error.config._retry = true;
      try {
        const token = await _authBridge.getAccessToken(API_RESOURCE);
        error.config.headers.Authorization = `Bearer ${token}`;
        return apiClient(error.config);
      } catch (err) {
        // refresh token 過期：強制登出並導向登入頁，避免使用者卡在持續 401
        console.warn('[Auth] refresh token 失效，將登出並導向登入頁：', err?.message || err);
        if (_authBridge.signOut) {
          await _authBridge.signOut(`${window.location.origin}/login`);
        }
      }
    }
    return Promise.reject(error);
  }
);

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
