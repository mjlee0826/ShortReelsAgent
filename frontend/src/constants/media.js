/**
 * 本機上傳媒體的共用常數（SSOT）。
 *
 * 「哪些副檔名算受支援媒體」需與後端 config/media_formats.py 的 MEDIA_EXTENSIONS 對齊；
 * 集中於此供「空白專案」的資料夾上傳做客端過濾與 <input accept>，避免 magic string 散落。
 */

/** 受支援媒體副檔名（含點、全小寫；與後端 MEDIA_EXTENSIONS = 圖片∪影片∪音訊 對齊）。 */
export const ACCEPTED_MEDIA_EXTENSIONS = [
  // 圖片
  '.jpg', '.jpeg', '.png', '.heic', '.heif',
  // 影片
  '.mp4', '.mov',
  // 音訊
  '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg',
];

/** 給 <input accept> 用的字串（逗號分隔的副檔名）。 */
export const ACCEPTED_MEDIA_ACCEPT = ACCEPTED_MEDIA_EXTENSIONS.join(',');

// 過濾用查找集合（建一次即可）
const _ACCEPTED_SET = new Set(ACCEPTED_MEDIA_EXTENSIONS);

/** 取檔名副檔名（含點、全小寫）；無副檔名回空字串。 */
function extensionOf(filename) {
  const dotIndex = filename.lastIndexOf('.');
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : '';
}

/**
 * 從 FileList／陣列中濾出受支援媒體檔（webkitdirectory 會連同非媒體雜檔一併帶入）。
 * @param {File[]} files
 * @returns {File[]} 僅保留受支援媒體
 */
export function filterMediaFiles(files) {
  return files.filter((file) => _ACCEPTED_SET.has(extensionOf(file.name)));
}
