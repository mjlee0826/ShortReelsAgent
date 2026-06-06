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

/**
 * 強制重新登入：refresh token 失效時清除登入狀態並導回 /login。
 *
 * 以 module-level flag 防止多個並發請求重複觸發 signOut。
 * **刻意放在模組層而非 React component / useEffect** —— 先前在 AuthGuard 內以
 * useEffect 依賴 Logto 方法（每次 render 都是新 reference）導致無限 render +
 * 狂送請求；模組層 interceptor 沒有 render cycle，從根本上杜絕該迴圈。
 */
let _reLoginInFlight = false;

async function forceReLogin() {
  if (_reLoginInFlight) return;
  _reLoginInFlight = true;
  console.warn('[Auth] 登入已失效，清除狀態並導回登入頁');
  try {
    if (_authBridge.signOut) {
      // signOut 會清掉 localStorage 內殘留的 token 並導向 /login
      await _authBridge.signOut(`${window.location.origin}/login`);
    } else {
      window.location.assign('/login');
    }
  } catch {
    // signOut 端點失敗（離線 / refresh token 已撤銷）也要保證離開受保護頁面
    window.location.assign('/login');
  }
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

// ── Response interceptor：換新 token 重打一次，refresh 失效則強制重登 ─────────
apiClient.interceptors.response.use(
  (res) => res,
  async (error) => {
    const status = error.response?.status;
    // 401：送出的 token 無效/過期（被 verify_token 拒）
    // 403：完全沒帶 token，被 FastAPI HTTPBearer 擋下（getAccessToken 先前已拋錯）
    // 本後端僅在「未認證」時回這兩碼，故都視為認證失敗、嘗試補救
    const isAuthError = status === 401 || status === 403;

    if (isAuthError && !error.config?._retry && _authBridge.getAccessToken) {
      error.config._retry = true;
      try {
        // 再換一次 token 重打：可化解「access token 剛好過期」「早期競態」等暫時性失敗
        const token = await _authBridge.getAccessToken(API_RESOURCE);
        if (!token) throw new Error('getAccessToken 回傳空值');
        error.config.headers.Authorization = `Bearer ${token}`;
        return apiClient(error.config);
      } catch (err) {
        // 重換仍失敗 → refresh token 確實失效 → 強制重新登入（清狀態 + 導向 /login）
        console.warn('[Auth] refresh token 失效：', err?.message || err);
        await forceReLogin();
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

  // 以 Google Drive 公開資料夾連結建立雲端來源專案，後端會於背景啟動首次同步（下載素材 + Phase 1）
  async createProjectFromDrive(displayName, sourceUrl) {
    const response = await apiClient.post('/api/projects/from-drive', {
      display_name: displayName,
      source_url: sourceUrl,
    });
    return response.data;
  }

  // 手動觸發一次雲端同步（阻塞：下載新素材 + 增量 Phase 1），回傳 SyncReport
  async syncProject(projectName) {
    const response = await apiClient.post(`/api/projects/${projectName}/sync`);
    return response.data;
  }

  async deleteProject(projectName) {
    await apiClient.delete(`/api/projects/${projectName}`);
  }

  // ── 素材管理（Asset Management UI）─────────────────────────────────────────

  // 列出某專案的所有素材檢視（狀態 / 策略 / dirty / 縮圖 URL）
  async fetchAssets(projectName) {
    const response = await apiClient.get(`/api/projects/${projectName}/assets`);
    return response.data;
  }

  // 取得單一素材的完整詳情（AssetView + 原始媒體 URL + Phase 1 完整感知 metadata），供詳情彈窗使用
  // 素材身分為含 / 的 relpath，故以 query 參數 path 傳遞（避免 path param 的 %2F 坑）
  async fetchAssetDetail(projectName, path) {
    const response = await apiClient.get(
      `/api/projects/${projectName}/asset-detail`,
      { params: { path } }
    );
    return response.data;
  }

  // 更新單一素材（以 relpath path 識別）的 Simple/Complex 策略並標記 dirty，回傳更新後的素材檢視
  async setAssetStrategy(projectName, path, strategy) {
    const response = await apiClient.patch(
      `/api/projects/${projectName}/asset-strategy`,
      { path, strategy }
    );
    return response.data;
  }

  // 強制重跑 Phase 1（assetIds=null 代表全部），回傳 { job_id } 供訂閱 WebSocket 進度
  async reanalyzeAssets(projectName, assetIds = null) {
    const response = await apiClient.post(
      `/api/projects/${projectName}/reanalyze`,
      { asset_ids: assetIds }
    );
    return response.data;
  }

  // 開始生成：套用逐檔策略後只重跑 dirty+未處理素材的 Phase 1，回傳 { job_id }
  async startAssetGenerate(projectName, assetStrategies = null) {
    const response = await apiClient.post(
      `/api/projects/${projectName}/generate`,
      { asset_strategies: assetStrategies }
    );
    return response.data;
  }

  // ── 全域使用者設定（Settings）──────────────────────────────────────────────

  // 讀取目前登入使用者的全域設定（自動分析開關 / 預設策略），缺檔時後端回安全預設
  async fetchSettings() {
    const response = await apiClient.get('/api/settings');
    return response.data;
  }

  // 部分更新全域設定（只送有變更的欄位），回傳更新後的完整設定
  async updateSettings(partial) {
    const response = await apiClient.patch('/api/settings', partial);
    return response.data;
  }
}

export const apiService = new DirectorApiService();
