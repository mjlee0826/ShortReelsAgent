import React, { useMemo, useState } from 'react';
import { FaImage, FaVideo, FaExclamationTriangle } from 'react-icons/fa';

/**
 * AssetMediaViewer：詳情彈窗的媒體檢視區。
 *
 * 呈現未裁切的完整原圖 / 可播放的完整影片。圖片與影片皆以 inline-block 外框承載 phase1 主體保留框
 * 疊層——外框會縮到媒體實際渲染尺寸，故 subject_bbox 的百分比座標可直接映射，免去 object-contain
 * 的 letterbox 換算（解決舊版影片 w-full + object-contain 的對位不準）。HEIC 原圖瀏覽器無法直顯、
 * 影片 codec 不支援、或載入失敗時，一律退回 JPEG 縮圖並附提示。
 */

const MEDIA_MAX_HEIGHT = 'max-h-[60vh]'; // 媒體最大高度，避免超過視窗
const HEIC_MIMES = ['image/heic', 'image/heif']; // 瀏覽器無法直接顯示的圖片 MIME

/**
 * SubjectBboxOverlay：phase1 主體保留框疊層（圖片 / 影片共用，DRY）。
 *
 * 百分比座標直接映射到「已縮到媒體渲染尺寸」的 inline-block 外框，免 letterbox 換算；
 * pointer-events-none 確保不擋影片控制列。bbox 為 falsy（無框 / 事件空檔）時不渲染。
 * 加上 left/top/width/height 過渡：Complex 影片切換 event 框時平滑移動（如 pan），靜態圖片無影響。
 * @param {?object} bbox 主體框（x1,y1,x2,y2 百分比座標）
 */
function SubjectBboxOverlay({ bbox }) {
  if (!bbox) return null;
  return (
    <div
      className="absolute border-2 border-accent bg-accent/10 rounded pointer-events-none transition-[left,top,width,height] duration-150 ease-out"
      style={{
        left: `${bbox.x1}%`,
        top: `${bbox.y1}%`,
        width: `${bbox.x2 - bbox.x1}%`,
        height: `${bbox.y2 - bbox.y1}%`,
      }}
    >
      <span className="absolute top-0 left-0 -translate-y-full text-[10px] px-1 rounded bg-accent text-white">主體</span>
    </div>
  );
}

/**
 * 依播放秒數挑出當前所在 event 的主體框（Complex 影片逐 event 動態框）。
 *
 * 取 ``start_time ≤ t ≤ end_time`` 且帶 subject_bbox 的第一筆事件;事件清單為連續區塊，
 * 故邊界相接無空隙。落在任何事件外（或無有效框）回 null → 疊層自動隱藏。
 * @param {Array} events multimodal_event_index 事件清單
 * @param {number} t 當前播放秒數
 * @returns {?object} 該 event 的 subject_bbox（百分比座標）或 null
 */
function findActiveEventBbox(events, t) {
  const active = events.find(
    (event) =>
      typeof event?.start_time === 'number' &&
      typeof event?.end_time === 'number' &&
      t >= event.start_time &&
      t <= event.end_time &&
      event.subject_bbox,
  );
  return active?.subject_bbox || null;
}

/**
 * @param {string} mediaUrl 原始媒體 /static URL
 * @param {?string} mediaMime 媒體 MIME（判斷 HEIC 後備）
 * @param {boolean} isVideo 是否為影片
 * @param {?string} thumbnailUrl 縮圖 URL（後備顯示用）
 * @param {?object} subjectBbox phase1 主體保留框（百分比座標，圖片 / Simple 影片的單一框）
 * @param {?Array} events Complex 影片的 multimodal_event_index（逐 event 動態框用；其他型別免傳）
 * @param {string} filename 檔名（img alt）
 */
export default function AssetMediaViewer({ mediaUrl, mediaMime, isVideo, thumbnailUrl, subjectBbox, events, filename }) {
  // 原始媒體無法呈現時退回縮圖；換素材時由呼叫端以 key={mediaUrl} 強制重掛以重置此旗標
  const [failed, setFailed] = useState(false);
  // 影片播放秒數（由 <video> onTimeUpdate 更新）—— 驅動 Complex 逐 event 動態框
  const [currentTime, setCurrentTime] = useState(0);

  const isHeic = HEIC_MIMES.includes(mediaMime);

  // Complex 影片:依當前秒數挑 event 框（動態）;Simple 影片 / 無事件則用靜態 subjectBbox
  const hasEvents = Array.isArray(events) && events.length > 0;
  const activeEventBbox = useMemo(
    () => (hasEvents ? findActiveEventBbox(events, currentTime) : null),
    [hasEvents, events, currentTime],
  );
  const videoBbox = hasEvents ? activeEventBbox : subjectBbox;

  /** 後備呈現：縮圖（或佔位 icon）+ 一行說明。 */
  const renderFallback = (message) => (
    <div className="flex flex-col items-center gap-3 w-full">
      {thumbnailUrl ? (
        <img src={thumbnailUrl} alt={filename} className={`${MEDIA_MAX_HEIGHT} max-w-full rounded-xl object-contain`} />
      ) : (
        <div className="py-16 text-4xl text-ink-faint">{isVideo ? <FaVideo /> : <FaImage />}</div>
      )}
      <p className="flex items-center gap-2 text-xs text-ink-faint text-center">
        <FaExclamationTriangle className="shrink-0" /> {message}
      </p>
    </div>
  );

  // 影片：直接由 /static 串流播放（StaticFiles 原生支援 range request）；codec 不支援退回縮圖。
  // 以 inline-block 外框承載主體框疊層——不設 w-full，讓 <video> 依原始長寬比縮到 max 範圍內，
  // 外框即縮到影片渲染尺寸，subject_bbox 百分比座標可直接對位（與圖片同一套機制）。
  if (isVideo) {
    if (failed) return renderFallback('此影片格式瀏覽器無法播放，以下為代表幀縮圖');
    return (
      <div className="relative inline-block">
        <video
          src={mediaUrl}
          controls
          onError={() => setFailed(true)}
          onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
          className={`${MEDIA_MAX_HEIGHT} max-w-full rounded-xl bg-black object-contain`}
        />
        <SubjectBboxOverlay bbox={videoBbox} />
      </div>
    );
  }

  // HEIC / HEIF：瀏覽器無法直接顯示原圖 → 直接退回 JPEG 縮圖
  if (isHeic) return renderFallback('原檔為 HEIC，瀏覽器無法預覽完整原圖，以下為縮圖');

  // 一般圖片：載入失敗退回縮圖；成功則以 inline-block 外框承載主體框疊層
  if (failed) return renderFallback('原圖載入失敗，以下為縮圖');
  return (
    <div className="relative inline-block">
      <img
        src={mediaUrl}
        alt={filename}
        onError={() => setFailed(true)}
        className={`${MEDIA_MAX_HEIGHT} max-w-full rounded-xl object-contain`}
      />
      {/* phase1 主體保留框：百分比座標直接映射到圖片渲染框（外框已縮到圖片大小，免 letterbox 換算）*/}
      <SubjectBboxOverlay bbox={subjectBbox} />
    </div>
  );
}
