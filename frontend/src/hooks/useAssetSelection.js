import { useCallback, useState } from 'react';

/**
 * useAssetSelection：素材選取狀態 hook（單一職責）。
 *
 * 管理「選取集合（relpath 身分）」與「選取模式」。刻意不依賴素材清單本身——
 * selectAll 由呼叫端帶入要全選的 path 清單，以與 useProjectAssets 解耦、避免循環依賴。
 */
export default function useAssetSelection() {
  // 選取集合一律存素材 relpath 身分（asset.path）
  const [selected, setSelected] = useState(new Set());
  // 選取模式：開啟後卡片才顯示勾選框、整卡可點選（與 selected 為獨立關注點）
  const [selectionMode, setSelectionMode] = useState(false);

  /** 切換單一素材的選取狀態。 */
  const toggleSelect = useCallback((path) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  /** 全選給定的 path 清單。 */
  const selectAll = useCallback((paths) => setSelected(new Set(paths)), []);

  /** 清空選取（保留選取模式）。 */
  const clearSelection = useCallback(() => setSelected(new Set()), []);

  /** 進入選取模式（詳情彈窗的關閉由頁面負責，保持本 hook 純粹）。 */
  const enterSelection = useCallback(() => setSelectionMode(true), []);

  /** 離開選取模式並清空選取（亦用於分析 job 啟動時重置選取狀態）。 */
  const exitSelection = useCallback(() => {
    setSelectionMode(false);
    setSelected(new Set());
  }, []);

  return {
    selected,
    selectionMode,
    toggleSelect,
    selectAll,
    clearSelection,
    enterSelection,
    exitSelection,
  };
}
