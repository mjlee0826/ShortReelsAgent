/**
 * Remotion 影片合成的轉場相關常數（集中管理，避免散落於各元件的 magic number）。
 *
 * 設計重點：TRANSITION_FRAMES 同時是「前一段為交叉轉場而往後延伸的幀數」與
 * 「下一段淡入動畫的幀數」——兩者必須是同一個值，交叉淡入才會精準對齊；
 * 故統一由此匯出，杜絕兩處各自寫死而失準。
 */

/** 交叉轉場的重疊 / 淡入幀數（前段延伸量 == 後段淡入長度）。 */
export const TRANSITION_FRAMES = 15;

/** 判定兩片段是否相鄰的秒數門檻：間距小於此值才視為相鄰、才允許做交叉轉場（避免非相鄰片段殘影）。 */
export const ADJACENCY_THRESHOLD_SECONDS = 0.1;

/**
 * 片段「提前掛載」的前置秒數（實際幀數 = 此值 × fps）。
 *
 * 讓下一段的 <video> 在切換到它之前就先掛載、載入並 seek 到起始幀（此期間隱形且靜音），
 * 待播放頭抵達交界時已就緒 → 消除即時 mount/decode/seek 造成的交界卡頓。
 * 注意：值越大、同時掛載的 <video> 越多（快速剪輯時尤甚），會增加瀏覽器解碼負擔；1 秒為平衡點。
 */
export const PREMOUNT_LEAD_SECONDS = 1;
