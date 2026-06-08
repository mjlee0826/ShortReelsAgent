/**
 * 時間軸純函式工具（Functional / 無副作用）。
 *
 * 對應設計文件 docs/editor_redesign.md §7：單軌、無縫接合 (gapless ripple)。
 * 所有結構性變更（裁切 / 重排 / 刪除）後都呼叫 `repack` 重算 start_at / end_at，
 * 確保片段永遠首尾相接、無空隙、不重疊。函式皆回傳新陣列 / 新物件，不修改輸入。
 */

// 浮點修整位數：避免多次運算累積誤差讓秒數出現 0.30000000004
const TIME_DECIMALS = 3;
// 片段最短顯示秒數：裁切時的下限，避免出現 0 長度片段
export const MIN_CLIP_DURATION = 0.1;

/**
 * 將秒數修整到固定小數位，消除浮點累積誤差。
 * @param {number} seconds 原始秒數
 * @returns {number} 修整後秒數
 */
function roundTime(seconds) {
  const factor = 10 ** TIME_DECIMALS;
  return Math.round(seconds * factor) / factor;
}

/**
 * 取得片段在時間軸上的顯示時長。
 * @param {object} clip 時間軸片段
 * @returns {number} 顯示時長（秒）
 */
export function clipDuration(clip) {
  return roundTime((clip.end_at ?? 0) - (clip.start_at ?? 0));
}

/**
 * 無縫接合：保持每段顯示時長，依現有順序由 0 起逐段重算 start_at / end_at。
 * 用於重排 / 刪除 / 裁切後，確保時間軸無空隙、不重疊（ripple 模型）。
 * @param {Array<object>} clips 時間軸片段陣列
 * @returns {Array<object>} 重算後的新片段陣列（不修改輸入）
 */
export function repack(clips) {
  let cursor = 0;
  return clips.map((clip) => {
    const duration = Math.max(MIN_CLIP_DURATION, clipDuration(clip));
    const start = roundTime(cursor);
    const end = roundTime(cursor + duration);
    cursor = end;
    return { ...clip, start_at: start, end_at: end };
  });
}

/**
 * 重排：把片段從 fromIndex 移到 toIndex，並重新接合。
 * @param {Array<object>} clips 時間軸片段陣列
 * @param {number} fromIndex 來源索引
 * @param {number} toIndex 目標索引
 * @returns {Array<object>} 重排並接合後的新片段陣列
 */
export function reorder(clips, fromIndex, toIndex) {
  if (fromIndex === toIndex) return clips;
  const next = [...clips];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return repack(next);
}

/**
 * 刪除：移除指定索引的片段，並重新接合。
 * 以索引（非 clip_id）為鍵，因 clip_id 是素材 relpath、同一素材可重複出現於多段。
 * @param {Array<object>} clips 時間軸片段陣列
 * @param {number} index 欲刪除片段的索引
 * @returns {Array<object>} 刪除並接合後的新片段陣列
 */
export function removeAt(clips, index) {
  return repack(clips.filter((_, i) => i !== index));
}
