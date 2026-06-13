/**
 * Observer Pattern (Zustand)：影片藍圖狀態管理（Slice Pattern 組合）。
 *
 * 管理目前開啟專案的生成表單、藍圖輸出與對話歷史紀錄。
 * 素材資料夾名稱改由 useProjectStore.currentProject.name 提供，不再由此 store 持有。
 *
 * 原本 500+ 行的單一 store 依領域拆成可組合 slice（表單 / 編輯 / 生成 / 快照），
 * 各 slice 共用同一個 set/get（故跨領域讀寫藍圖屬正常用法），對外公開介面完全不變。
 */
import { create } from 'zustand';
import { EMPTY_SELECTION } from './blueprint/history';
import { createFormSlice } from './blueprint/formSlice';
import { createEditorSlice } from './blueprint/editorSlice';
import { createGenerationSlice } from './blueprint/generationSlice';
import { createSnapshotSlice } from './blueprint/snapshotSlice';

const useBlueprintStore = create((set, get) => ({
  ...createFormSlice(set, get),
  ...createEditorSlice(set, get),
  ...createGenerationSlice(set, get),
  ...createSnapshotSlice(set, get),

  // 重置所有輸出狀態（切換專案時由 useProjectStore 觸發）；
  // 刻意保留 enableSubtitles / enableFilters / musicStrategy 等使用者偏好不清。
  reset: () => set({
    blueprint: null,
    assetsRootUrl: '',
    isProcessing: false,
    generationJobId: null,
    generationStage: null,
    isLoadingBlueprint: false,
    errorMsg: '',
    redirectToAssetsProject: null,
    chatHistory: [],
    uploadedMusicFile: null,
    isChangingMusic: false,
    userPrompt: '',
    templateSource: '',
    selection: { ...EMPTY_SELECTION },
    seekRequest: { seconds: 0, nonce: 0 },
    playheadSeconds: 0,
    history: { past: [], future: [] },
    snapshots: [],
  }),
}));

export default useBlueprintStore;
