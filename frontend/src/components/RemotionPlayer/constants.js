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
