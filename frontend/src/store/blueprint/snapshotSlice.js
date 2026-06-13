import { apiService } from '../../services/api.service';
import { extractErrorMessage } from '../../utils/errorMessage';
import { migrateBlueprintTextOverlays } from '../../utils/textOverlay';
import { EMPTY_SELECTION, pushHistory } from './history';

/**
 * 持久化具名快照 slice（版本檢查點，存後端、可跨重整還原）。
 * @param {Function} set zustand set
 * @param {Function} get zustand get
 * @returns {object} slice 片段
 */
export function createSnapshotSlice(set, get) {
  return {
    // 持久化具名快照 meta 列表（[{ id, label, created_at }]，由後端讀寫；blueprint 不在此）
    snapshots: [],

    // 載入專案的快照清單（左欄版本列表）
    loadSnapshots: async (folderName) => {
      if (!folderName) return;
      try {
        const snapshots = await apiService.listSnapshots(folderName);
        set({ snapshots });
      } catch (error) {
        console.warn('[Editor] 載入快照清單失敗：', extractErrorMessage(error));
      }
    },

    // 把當前 blueprint 存成具名快照；成功後把新 meta 置頂加入清單
    saveSnapshot: async (folderName, label) => {
      const blueprint = get().blueprint;
      if (!folderName || !blueprint) return;
      try {
        const meta = await apiService.saveSnapshot(folderName, label, blueprint);
        set((state) => ({ snapshots: [meta, ...state.snapshots] }));
      } catch (error) {
        alert(`儲存版本失敗：${extractErrorMessage(error)}`);
      }
    },

    // 還原快照：取回該版 blueprint，先把當前推進 Undo 堆疊（還原本身可 Undo），再替換
    restoreSnapshot: async (folderName, snapshotId) => {
      if (!folderName) return;
      try {
        const result = await apiService.getSnapshot(folderName, snapshotId);
        set((state) => ({
          blueprint: migrateBlueprintTextOverlays(result.blueprint),
          assetsRootUrl: result.assets_root_url,
          history: pushHistory(state.history, state.blueprint),
          selection: { ...EMPTY_SELECTION },
        }));
      } catch (error) {
        alert(`還原版本失敗：${extractErrorMessage(error)}`);
      }
    },

    // 刪除快照並從清單移除
    deleteSnapshot: async (folderName, snapshotId) => {
      if (!folderName) return;
      try {
        await apiService.deleteSnapshot(folderName, snapshotId);
        set((state) => ({ snapshots: state.snapshots.filter((s) => s.id !== snapshotId) }));
      } catch (error) {
        alert(`刪除版本失敗：${extractErrorMessage(error)}`);
      }
    },
  };
}
