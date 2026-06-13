/**
 * Facade Pattern：後端 API 存取層（彙整各資源模組）。
 *
 * 基礎建設（apiClient.js：共用 axios 實例與認證 interceptor）與各領域資源方法分離，
 * 此處把資源模組組合成單一扁平 facade `apiService`，對外呼叫點維持 apiService.xxx() 不變。
 * import 本模組即會載入 apiClient.js，於模組載入時註冊認證 interceptor（早於任何資料請求）。
 */
import { setAuthBridge } from './apiClient';
import { generationApi } from './resources/generation.api';
import { projectApi } from './resources/project.api';
import { snapshotApi } from './resources/snapshot.api';
import { assetApi } from './resources/asset.api';
import { settingsApi } from './resources/settings.api';

// 重新匯出，讓 AuthInterceptorSetup 仍可由本模組取得（維持既有 import 路徑）
export { setAuthBridge };

// 扁平 facade：把各資源方法攤平到單一物件，呼叫端沿用 apiService.fetchProjects() 等既有用法
export const apiService = {
  ...generationApi,
  ...projectApi,
  ...snapshotApi,
  ...assetApi,
  ...settingsApi,
};
