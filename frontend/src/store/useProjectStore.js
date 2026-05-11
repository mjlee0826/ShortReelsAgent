/**
 * Observer Pattern (Zustand)：使用者專案狀態管理
 *
 * 管理專案清單的讀取、建立、刪除，以及當前選定的專案。
 * 切換專案時自動清除 blueprint store，確保編輯器不顯示舊資料。
 */
import { create } from 'zustand';
import { apiService } from '../services/api.service';

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
      const msg = error.response?.data?.detail || error.message || String(error);
      set({ errorMsg: `載入專案失敗：${msg}`, isLoading: false });
    }
  },

  // 建立新專案並重新載入清單
  createProject: async (displayName) => {
    set({ isLoading: true, errorMsg: '' });
    try {
      await apiService.createProject(displayName);
      await get().fetchProjects();
    } catch (error) {
      const msg = error.response?.data?.detail || error.message || String(error);
      set({ errorMsg: `建立專案失敗：${msg}`, isLoading: false });
      throw error;
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
      const msg = error.response?.data?.detail || error.message || String(error);
      set({ errorMsg: `刪除專案失敗：${msg}`, isLoading: false });
      throw error;
    }
  },

  // 選定專案（由元件負責導向 /editor）；同時清除 blueprint store 防止顯示舊資料
  selectProject: (project) => {
    // 動態引入避免循環依賴
    import('./useBlueprintStore').then(({ default: useBlueprintStore }) => {
      useBlueprintStore.getState().reset();
    });
    set({ currentProject: project });
  },

  clearError: () => set({ errorMsg: '' }),
}));

export default useProjectStore;
