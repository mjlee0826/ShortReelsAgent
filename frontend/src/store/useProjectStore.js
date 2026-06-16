/**
 * Observer Pattern (Zustand)：使用者專案狀態管理
 *
 * 管理專案清單的讀取、建立、刪除，以及當前選定的專案。
 * 切換專案時自動清除 blueprint store，確保編輯器不顯示舊資料。
 */
import { create } from 'zustand';
import { apiService } from '../services/api.service';
import { extractErrorMessage } from '../utils/errorMessage';

const useProjectStore = create((set, get) => ({
  // --- 狀態 ---
  projects: [],
  currentProject: null,
  isLoading: false,
  errorMsg: '',

  // --- 操作 ---

  // 從後端載入使用者的所有專案
  fetchProjects: async () => {
    set({ isLoading: true, errorMsg: '' });
    try {
      const projects = await apiService.fetchProjects();
      set({ projects, isLoading: false });
    } catch (error) {
      const msg = extractErrorMessage(error);
      set({ errorMsg: `載入專案失敗：${msg}`, isLoading: false });
    }
  },

  // 以 Google Drive 資料夾連結建立雲端來源專案並重新載入清單（素材於背景同步下載）
  createProjectFromDrive: async (displayName, sourceUrl) => {
    set({ isLoading: true, errorMsg: '' });
    try {
      await apiService.createProjectFromDrive(displayName, sourceUrl);
      await get().fetchProjects();
    } catch (error) {
      const msg = extractErrorMessage(error);
      set({ errorMsg: `建立專案失敗：${msg}`, isLoading: false });
      throw error;
    }
  },

  // 以本機資料夾建立「本機來源」專案並重新載入清單（檔案上傳後於背景標準化／分析）
  createProjectFromFolder: async (displayName, files) => {
    set({ isLoading: true, errorMsg: '' });
    try {
      await apiService.createProjectFromFolder(displayName, files);
      await get().fetchProjects();
    } catch (error) {
      const msg = extractErrorMessage(error);
      set({ errorMsg: `建立專案失敗：${msg}`, isLoading: false });
      throw error;
    }
  },

  // 手動觸發一次雲端同步（下載新素材 + 增量 Phase 1），完成後重抓刷新 sync_status / 素材數。
  // 刻意不切換全域 isLoading（避免整個網格翻 spinner）；按鈕的「同步中」狀態由 ProjectCard 本地管理。
  syncProject: async (projectName) => {
    set({ errorMsg: '' });
    try {
      await apiService.syncProject(projectName);
      await get().fetchProjects();
    } catch (error) {
      const msg = extractErrorMessage(error);
      set({ errorMsg: `同步失敗：${msg}` });
      throw error; // 讓呼叫端（卡片）得知失敗以還原按鈕狀態
    }
  },

  // 刪除指定專案並重新載入清單
  deleteProject: async (projectName) => {
    set({ isLoading: true, errorMsg: '' });
    try {
      await apiService.deleteProject(projectName);
      // 若刪除的是當前選定的專案，清除選定狀態
      if (get().currentProject?.name === projectName) {
        set({ currentProject: null });
      }
      await get().fetchProjects();
    } catch (error) {
      const msg = extractErrorMessage(error);
      set({ errorMsg: `刪除專案失敗：${msg}`, isLoading: false });
      throw error;
    }
  },

  // 選定專案（由元件負責導向 /projects/:projectId/editor）；同時清除 blueprint store 防止顯示舊資料
  selectProject: (project) => {
    // 動態引入避免循環依賴
    import('./useBlueprintStore').then(({ default: useBlueprintStore }) => {
      useBlueprintStore.getState().reset();
    });
    set({ currentProject: project });
  },

  // 清除當前選定專案（返回首頁時呼叫，讓頂部麵包屑不停留在舊專案 —— 需求 5）
  clearCurrentProject: () => set({ currentProject: null }),

  clearError: () => set({ errorMsg: '' }),
}));

export default useProjectStore;
