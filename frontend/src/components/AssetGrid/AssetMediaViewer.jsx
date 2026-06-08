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

// 候選框視覺樣式:best 用強調色實線、其餘候選用灰色虛線（色彩 + 線型雙重區隔，重疊時仍可辨）
const BEST_BOX_CLASS = 'border-2 border-accent bg-accent/10 z-10';
const CANDIDATE_BOX_CLASS = 'border border-dashed border-ink-faint/80 bg-ink-faint/5';
const BEST_TAG_CLASS = 'bg-accent text-white';
const CANDIDATE_TAG_CLASS = 'bg-elevated/90 text-ink-muted border border-border';
const FALLBACK_SUBJECT_LABEL = '主體'; // 無 label（臉部 fallback / 舊資料單框）時的預設標籤

/** 兩個 bbox 四座標皆相等視為同一框（用來在候選清單中標出 best;座標皆已 round 至小數一位故可精確比對）。 */
function bboxEquals(a, b) {
  return !!a && !!b && a.x1 === b.x1 && a.y1 === b.y1 && a.x2 === b.x2 && a.y2 === b.y2;
}

/**
 * 把 top-N 候選清單 + 最佳框組成可疊加的 box 陣列（每筆含 bbox/label/confidence/isBest）。
 *
 * 有候選清單時逐框畫,以座標比對標出 best(對不到則退標信心最高的第一筆,確保恰有一個 best);
 * 無候選但有單一最佳框時(臉部 fallback / 舊資料無候選欄位)畫一個並標 best;皆無則回空陣列。
 * @param {?Array} candidates [{bbox,label,confidence}] 候選清單(已依信心遞減)
 * @param {?object} bestBbox 被選為最佳的框(x1,y1,x2,y2)
 */
function buildOverlayBoxes(candidates, bestBbox) {
  if (Array.isArray(candidates) && candidates.length > 0) {
    const valid = candidates.filter((candidate) => candidate?.bbox);
    let bestIdx = valid.findIndex((candidate) => bboxEquals(candidate.bbox, bestBbox));
    if (bestIdx < 0) bestIdx = 0; // 理論上 best 必為候選之一;對不到時退標信心最高者
    return valid.map((candidate, i) => ({
      bbox: candidate.bbox,
      label: candidate.label,
      confidence: candidate.confidence,
      isBest: i === bestIdx,
    }));
  }
  if (bestBbox) return [{ bbox: bestBbox, label: '', confidence: null, isBest: true }];
  return [];
}

/**
 * SubjectCandidateBox：單一候選主體框疊層。
 *
 * 百分比座標直接映射到「已縮到媒體渲染尺寸」的 inline-block 外框,免 letterbox 換算;
 * pointer-events-none 確保不擋影片控制列。best 以強調色實線突顯、其餘候選灰色虛線,標籤標 label(+信心%)。
 * 加上 left/top/width/height 過渡:Complex 影片切換 event 框時平滑移動（如 pan）。
 */
function SubjectCandidateBox({ bbox, label, confidence, isBest }) {
  // 信心可能缺(fallback 單框)→ 省略百分比;best 前綴 ★ 以利一眼辨識
  const pct = typeof confidence === 'number' ? ` ${Math.round(confidence * 100)}%` : '';
  const tagText = `${isBest ? '★ ' : ''}${label || FALLBACK_SUBJECT_LABEL}${pct}`;
  return (
    <div
      className={`absolute rounded pointer-events-none transition-[left,top,width,height] duration-150 ease-out ${
        isBest ? BEST_BOX_CLASS : CANDIDATE_BOX_CLASS
      }`}
      style={{
        left: `${bbox.x1}%`,
        top: `${bbox.y1}%`,
        width: `${bbox.x2 - bbox.x1}%`,
        height: `${bbox.y2 - bbox.y1}%`,
      }}
    >
      <span
        className={`absolute top-0 left-0 -translate-y-full text-[10px] leading-tight px-1 rounded whitespace-nowrap ${
          isBest ? BEST_TAG_CLASS : CANDIDATE_TAG_CLASS
        }`}
      >
        {tagText}
      </span>
    </div>
  );
}

/**
 * SubjectBboxLayer：主體候選框疊層群（圖片 / 影片共用，DRY）。
 *
 * 依 boxes 畫出所有候選框;空陣列(無框 / 事件空檔)時不渲染。以 index 為 key,讓 Complex 影片
 * 切換 event 時同位置框平滑過渡;best 帶 z-10,確保重疊時其框線與標籤在最上層。
 * @param {Array} boxes buildOverlayBoxes 產出的 box 陣列
 */
function SubjectBboxLayer({ boxes }) {
  if (!boxes || boxes.length === 0) return null;
  return (
    <>
      {boxes.map((box, i) => (
        <SubjectCandidateBox
          key={i}
          bbox={box.bbox}
          label={box.label}
          confidence={box.confidence}
          isBest={box.isBest}
        />
      ))}
    </>
  );
}

/**
 * 依播放秒數挑出當前所在 event（Complex 影片逐 event 動態框）。
 *
 * 取 ``start_time ≤ t ≤ end_time`` 的第一筆事件;事件清單為連續區塊，邊界相接無空隙。
 * 落在任何事件外回 null → 疊層自動隱藏。
 * @param {Array} events multimodal_event_index 事件清單
 * @param {number} t 當前播放秒數
 * @returns {?object} 該 event 物件或 null
 */
function findActiveEvent(events, t) {
  return (
    events.find(
      (event) =>
        typeof event?.start_time === 'number' &&
        typeof event?.end_time === 'number' &&
        t >= event.start_time &&
        t <= event.end_time,
    ) || null
  );
}

/**
 * @param {string} mediaUrl 原始媒體 /static URL
 * @param {?string} mediaMime 媒體 MIME（判斷 HEIC 後備）
 * @param {boolean} isVideo 是否為影片
 * @param {?string} thumbnailUrl 縮圖 URL（後備顯示用）
 * @param {?object} subjectBbox phase1 最佳主體框（百分比座標，圖片 / Simple 影片;標記為 best）
 * @param {?Array} subjectCandidates phase1 top-N 候選主體 [{bbox,label,confidence}]（圖片 / Simple 影片）
 * @param {?Array} events Complex 影片的 multimodal_event_index（逐 event 動態候選框用；其他型別免傳）
 * @param {string} filename 檔名（img alt）
 */
export default function AssetMediaViewer({ mediaUrl, mediaMime, isVideo, thumbnailUrl, subjectBbox, subjectCandidates, events, filename }) {
  // 原始媒體無法呈現時退回縮圖；換素材時由呼叫端以 key={mediaUrl} 強制重掛以重置此旗標
  const [failed, setFailed] = useState(false);
  // 影片播放秒數（由 <video> onTimeUpdate 更新）—— 驅動 Complex 逐 event 動態框
  const [currentTime, setCurrentTime] = useState(0);

  const isHeic = HEIC_MIMES.includes(mediaMime);
  const hasEvents = Array.isArray(events) && events.length > 0;

  // 當前要疊的候選框群 + best 標記:Complex 依播放秒數取 active event 的逐 event 候選;
  // 圖片 / Simple 影片用 phase1 的靜態候選(subjectCandidates)與最佳框(subjectBbox)。
  const overlayBoxes = useMemo(() => {
    if (hasEvents) {
      const activeEvent = findActiveEvent(events, currentTime);
      return buildOverlayBoxes(activeEvent?.subject_candidates, activeEvent?.subject_bbox);
    }
    return buildOverlayBoxes(subjectCandidates, subjectBbox);
  }, [hasEvents, events, currentTime, subjectCandidates, subjectBbox]);

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
        <SubjectBboxLayer boxes={overlayBoxes} />
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
      {/* phase1 top-N 候選主體框：百分比座標直接映射到圖片渲染框（外框已縮到圖片大小，免 letterbox 換算）*/}
      <SubjectBboxLayer boxes={overlayBoxes} />
    </div>
  );
}
