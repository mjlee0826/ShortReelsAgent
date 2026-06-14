/**
 * 素材清單統計的純領域工具（純函式 / 具名常數，無副作用）。
 *
 * 集中「照片數 / 影片數 / 影片總時長」的計算與顯示格式化，供 AssetSummaryBar 與頁面使用，
 * 避免統計邏輯與 magic string 散落在 JSX 內（風格對齊 assetMeta.js）。
 */

// 素材媒體種類（對齊後端 AssetView.media_kind，避免 magic string）
export const MEDIA_KIND = { IMAGE: 'image', VIDEO: 'video' };

// 時長格式化用具名常數（避免 magic number）
const SECONDS_PER_MINUTE = 60;

/**
 * 統計素材清單：照片數、影片數、影片總時長（秒）。
 *
 * 影片時長取自各素材的 duration（僅 success 影片有值，由後端 AssetView 帶入）；
 * 缺值（未分析 / rejected / error 影片）以 0 計入，不影響張數統計。
 *
 * @param {Array<{media_kind:string, duration?:number}>} assets 素材清單
 * @returns {{imageCount:number, videoCount:number, totalVideoDuration:number}}
 */
export function summarizeAssets(assets) {
  return assets.reduce(
    (acc, asset) => {
      if (asset.media_kind === MEDIA_KIND.VIDEO) {
        acc.videoCount += 1;
        acc.totalVideoDuration += Number(asset.duration) || 0;
      } else {
        acc.imageCount += 1;
      }
      return acc;
    },
    { imageCount: 0, videoCount: 0, totalVideoDuration: 0 },
  );
}

/**
 * 影片總時長（秒）→ 中文友善字串。
 * 不足一分鐘顯示「N 秒」；超過則顯示「M 分」或「M 分 S 秒」（整分時省略秒）。
 *
 * @param {number} seconds 總秒數
 * @returns {string}
 */
export function formatTotalDuration(seconds) {
  const total = Math.round(Number(seconds) || 0);
  if (total < SECONDS_PER_MINUTE) return `${total} 秒`;
  const minutes = Math.floor(total / SECONDS_PER_MINUTE);
  const rest = total % SECONDS_PER_MINUTE;
  return rest === 0 ? `${minutes} 分` : `${minutes} 分 ${rest} 秒`;
}
