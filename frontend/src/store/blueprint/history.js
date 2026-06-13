/**
 * 藍圖 Undo/Redo 與選取相關的純 helper 與常數（供 blueprint 各 slice 共用）。
 *
 * 全為無副作用的純函式與具名常數，自 useBlueprintStore 主檔抽出，避免 slice 間重複。
 */

/** Undo/Redo 快照保留上限，避免記憶體無限成長（具名常數，禁 magic number）。 */
export const HISTORY_LIMIT = 50;

/** 無選取時的初始選取狀態。 */
export const EMPTY_SELECTION = { type: null, clipIndex: null, textIndex: null };

/**
 * 推進一筆 Undo 快照：把舊 blueprint 推入 past（超過上限則丟最舊），並清空 future。
 * 任何「會改變 blueprint 的操作」（手動就地編輯 / AI 微調）都應呼叫，確保可被 Undo。
 * @param {object} history 目前的 { past, future }
 * @param {object|null} prevBlueprint 變更前的 blueprint（null 代表首次生成，不推快照）
 * @returns {object} 新的 { past, future }
 */
export function pushHistory(history, prevBlueprint) {
  if (!prevBlueprint) return { past: history.past, future: [] };
  return { past: [...history.past, prevBlueprint].slice(-HISTORY_LIMIT), future: [] };
}

/**
 * 計算「陣列元素由 from 移到 to」後，某個舊索引對應的新索引。
 * 用於重排後把選取狀態映射到正確的片段（避免選取錯位）。
 * @param {number} i 變更前的索引
 * @param {number} from 被移動元素的原索引
 * @param {number} to 被移動元素的新索引
 * @returns {number} 變更後的索引
 */
export function remapIndexAfterMove(i, from, to) {
  if (i === from) return to;                 // 被移動者本身
  if (from < i && i <= to) return i - 1;     // 落在 (from, to] 的元素前移一格
  if (to <= i && i < from) return i + 1;     // 落在 [to, from) 的元素後移一格
  return i;                                  // 其餘不受影響
}
