/**
 * 素材 URL 解析的單一真實來源（Single Source of Truth）。
 *
 * 預覽渲染（ClipComponent / MainTimeline）與預抓（useAssetPrefetch）必須產生
 * 「逐字相同」的 URL，prefetch 下載的內容才會命中 Remotion 的素材快取、被 <Video>/<Img>/<Audio>
 * 直接取用。故將 URL 組法集中於此，避免兩處各寫一份而漂移（亦符合去重複 / design pattern 規範）。
 */

// 影片 / 圖片判別：副檔名屬此集合者視為靜態圖（用 <Img> 而非 <Video> 渲染）
const IMAGE_EXTENSION_PATTERN = /\.(jpg|jpeg|png|heic|heif)$/i;

// BGM track_id 若以此前綴開頭，視為完整外部網址（全域快取池來的），直接使用、不再接 root
const HTTP_URL_PREFIX = 'http';

/**
 * 組出主畫面 / PiP 片段的素材 URL。
 *
 * clip_id 為素材身分 relpath（如 standardized/clip_std.mp4），直接接在 assetsRootUrl 後即命中
 * 後端 /static 的磁碟分層；不可再 split('/').pop()（那會丟掉 raw/standardized 子目錄而指錯路徑）。
 *
 * @param {string} assetsRootUrl 素材靜態根 URL（結尾含斜線）
 * @param {string} relpath 素材相對路徑（clip_id）
 * @returns {string} 可直接餵給 <Video>/<Img> 的完整 URL
 */
export function resolveClipAssetUrl(assetsRootUrl, relpath) {
  return `${assetsRootUrl}${relpath}`;
}

/**
 * 組出背景音樂（BGM）的素材 URL。
 *
 * 與既有 getBgmSrc 行為一致：track_id 為完整網址（全域快取池）則直通；否則視為舊版相容的
 * 同資料夾檔名，取檔名接在 root 後。
 *
 * @param {string} assetsRootUrl 素材靜態根 URL（結尾含斜線）
 * @param {string|undefined} trackId BGM 音軌識別（完整網址或檔名 / relpath）
 * @returns {string|null} 完整 URL；無 track_id 時回 null
 */
export function resolveBgmUrl(assetsRootUrl, trackId) {
  if (!trackId) return null;
  // 完整網址（全域快取池來的）直接回傳
  if (trackId.startsWith(HTTP_URL_PREFIX)) {
    return trackId;
  }
  // 舊版相容：同資料夾的檔名
  return `${assetsRootUrl}${trackId.split('/').pop()}`;
}

/**
 * 判別素材 relpath 是否為靜態圖片。
 *
 * @param {string} relpath 素材相對路徑（clip_id）
 * @returns {boolean} 為圖片回 true
 */
export function isImageAsset(relpath) {
  return IMAGE_EXTENSION_PATTERN.test(relpath);
}

/**
 * 蒐集藍圖內所有素材 URL（主畫面影 / 圖、PiP 子畫面、BGM）。
 *
 * 供預抓使用：以 Set 去重（同一素材跨多段重複出現時只抓一次）、濾除空值。
 * 產生的 URL 與渲染端共用同一組 resolve 函式，確保 prefetch 必命中快取。
 *
 * @param {object|null} blueprint 影片藍圖（含 timeline / bgm_track）
 * @param {string} assetsRootUrl 素材靜態根 URL
 * @returns {string[]} 去重後的素材 URL 陣列；藍圖為空時回空陣列
 */
export function collectBlueprintAssetUrls(blueprint, assetsRootUrl) {
  if (!blueprint || !Array.isArray(blueprint.timeline)) return [];

  const urls = new Set();

  // 逐段蒐集主畫面與 PiP 子畫面（圖片亦走同一 resolve，僅渲染端才區分元件）
  for (const clip of blueprint.timeline) {
    if (clip?.clip_id) {
      urls.add(resolveClipAssetUrl(assetsRootUrl, clip.clip_id));
    }
    if (clip?.pip_video?.clip_id) {
      urls.add(resolveClipAssetUrl(assetsRootUrl, clip.pip_video.clip_id));
    }
  }

  // 全域背景音樂
  const bgmUrl = resolveBgmUrl(assetsRootUrl, blueprint.bgm_track?.track_id);
  if (bgmUrl) urls.add(bgmUrl);

  return Array.from(urls);
}
