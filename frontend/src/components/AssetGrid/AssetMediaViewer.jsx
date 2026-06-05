import React, { useState } from 'react';
import { FaImage, FaVideo, FaExclamationTriangle } from 'react-icons/fa';

/**
 * AssetMediaViewer：詳情彈窗的媒體檢視區。
 *
 * 呈現未裁切的完整原圖 / 可播放的完整影片（皆 object-contain 不裁切）。圖片以 inline-block 外框
 * 承載 phase1 主體保留框疊層——外框會縮到圖片實際渲染尺寸，故 subject_bbox 的百分比座標可直接
 * 映射，免去 object-contain 的 letterbox 換算。HEIC 原圖瀏覽器無法直顯、影片 codec 不支援、
 * 或載入失敗時，一律退回 JPEG 縮圖並附提示。
 */

const MEDIA_MAX_HEIGHT = 'max-h-[60vh]'; // 媒體最大高度，避免超過視窗
const HEIC_MIMES = ['image/heic', 'image/heif']; // 瀏覽器無法直接顯示的圖片 MIME

/**
 * @param {string} mediaUrl 原始媒體 /static URL
 * @param {?string} mediaMime 媒體 MIME（判斷 HEIC 後備）
 * @param {boolean} isVideo 是否為影片
 * @param {?string} thumbnailUrl 縮圖 URL（後備顯示用）
 * @param {?object} subjectBbox phase1 主體保留框（百分比座標，僅圖片疊層）
 * @param {string} filename 檔名（img alt）
 */
export default function AssetMediaViewer({ mediaUrl, mediaMime, isVideo, thumbnailUrl, subjectBbox, filename }) {
  // 原始媒體無法呈現時退回縮圖；換素材時由呼叫端以 key={mediaUrl} 強制重掛以重置此旗標
  const [failed, setFailed] = useState(false);

  const isHeic = HEIC_MIMES.includes(mediaMime);

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

  // 影片：直接由 /static 串流播放（StaticFiles 原生支援 range request）；codec 不支援退回縮圖
  if (isVideo) {
    if (failed) return renderFallback('此影片格式瀏覽器無法播放，以下為代表幀縮圖');
    return (
      <video
        src={mediaUrl}
        controls
        onError={() => setFailed(true)}
        className={`${MEDIA_MAX_HEIGHT} max-w-full w-full rounded-xl bg-black object-contain`}
      />
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
      {subjectBbox && (
        <div
          className="absolute border-2 border-accent bg-accent/10 rounded pointer-events-none"
          style={{
            left: `${subjectBbox.x1}%`,
            top: `${subjectBbox.y1}%`,
            width: `${subjectBbox.x2 - subjectBbox.x1}%`,
            height: `${subjectBbox.y2 - subjectBbox.y1}%`,
          }}
        >
          <span className="absolute top-0 left-0 -translate-y-full text-[10px] px-1 rounded bg-accent text-white">主體</span>
        </div>
      )}
    </div>
  );
}
