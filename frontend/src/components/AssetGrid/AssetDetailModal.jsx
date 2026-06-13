import React, { useEffect, useState } from 'react';
import { FaExclamationCircle } from 'react-icons/fa';
import { Modal, Spinner, Badge } from '../ui';
import { apiService } from '../../services/api.service';
import { extractErrorMessage } from '../../utils/errorMessage';
import { hasValue, formatScore } from './assetMeta';
import AssetMediaViewer from './AssetMediaViewer';
import AssetMetaPanel from './AssetMetaPanel';

/**
 * AssetDetailModal：素材詳情彈窗（Container）。
 *
 * 接專案名 + 檔名，自抓單一素材完整詳情（AssetView + 原始媒體 URL + Phase 1 metadata），
 * 以 Modal 呈現「媒體檢視區 + Phase 1 資訊分區」。success 素材顯示完整分區；rejected /
 * error / unprocessed 無 metadata，改顯示狀態說明。資料自抓於本元件內，使列表頁只需管「哪張開著」。
 */

const MODAL_MAX_WIDTH = 'max-w-4xl'; // 給媒體較大的呈現空間

// 無 metadata 各狀態的說明（這些素材本就沒有 success metadata）
const STATUS_NOTICE = {
  rejected: { tone: 'warning', title: '此素材未通過品質篩選' },
  error: { tone: 'danger', title: '此素材處理時發生錯誤' },
  unprocessed: { tone: 'neutral', title: '此素材尚未經 Phase 1 分析' },
};
const DEFAULT_NOTICE_TEXT = '尚無分析資訊。設定策略後執行「重新分析」或「開始生成」即可產生。';

/** 無 metadata 時的狀態說明（拒絕 reason / 失敗 error / 未處理提示 + 技術分）。 */
function StatusNotice({ asset }) {
  const notice = STATUS_NOTICE[asset.status] || STATUS_NOTICE.unprocessed;
  const detailText = asset.reason || asset.error || DEFAULT_NOTICE_TEXT;
  return (
    <div className="bg-surface border border-border rounded-xl p-5 flex flex-col gap-3">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge tone={notice.tone}>{notice.title}</Badge>
        {hasValue(asset.technical_score) && (
          <span className="text-xs text-ink-faint">技術分 {formatScore(asset.technical_score)}</span>
        )}
      </div>
      <p className="text-sm text-ink-muted leading-relaxed">{detailText}</p>
    </div>
  );
}

/**
 * @param {string} projectName 專案名（slug）
 * @param {string} path 素材身分 relpath（如 raw/photo.jpg）—— 用於抓詳情
 * @param {string} filename 素材顯示檔名（basename）—— 用於標題 / alt
 * @param {?string} thumbnailUrl 縮圖 URL（HEIC / 影片後備用）
 * @param {()=>void} onClose 關閉回呼
 */
export default function AssetDetailModal({ projectName, path, filename, thumbnailUrl, onClose }) {
  const [detail, setDetail] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');

  // 開啟時自抓詳情;active 旗標避免請求未回前元件已卸載仍 setState。
  // 彈窗每次開啟皆重新掛載(path null↔值),故初始 isLoading=true 已涵蓋載入態,
  // 毋須在 effect 同步 setState(避免 react-hooks/set-state-in-effect 的串聯重繪);
  // 所有 setState 僅落在 then/catch/finally 非同步回呼,與本專案既有 fetch effect 慣例一致。
  useEffect(() => {
    let active = true;
    apiService.fetchAssetDetail(projectName, path)
      .then((data) => { if (active) { setDetail(data); setErrorMsg(''); } })
      .catch((error) => {
        if (active) setErrorMsg(extractErrorMessage(error));
      })
      .finally(() => { if (active) setIsLoading(false); });
    return () => { active = false; };
  }, [projectName, path]);

  const asset = detail?.asset;
  const metadata = detail?.metadata;
  // metadata_kind 缺(無 metadata)時退回 AssetView.media_kind 判斷影片
  const isVideo = (detail?.metadata_kind || asset?.media_kind) === 'video';
  // 圖片與 Simple 影片:subject_bbox 為最佳框、subject_candidates 為 top-N 候選 → 疊靜態候選框群
  const overlayBbox = metadata?.subject_bbox;
  const overlayCandidates = metadata?.subject_candidates;
  // Complex 影片的逐 event 動態框來源:有 multimodal_event_index 時交給 viewer 依播放秒數切換
  const eventIndex = metadata?.multimodal_event_index;

  return (
    <Modal title={filename} onClose={onClose} maxWidth={MODAL_MAX_WIDTH}>
      {isLoading ? (
        <div className="flex flex-col items-center gap-3 py-16 text-ink-faint">
          <Spinner />
          <p className="text-sm">載入素材詳情中...</p>
        </div>
      ) : errorMsg ? (
        <div className="flex items-center gap-2 py-10 px-4 text-danger text-sm">
          <FaExclamationCircle className="shrink-0" />
          <span>載入詳情失敗：{errorMsg}</span>
        </div>
      ) : (
        <div className="flex flex-col gap-5 max-h-[75vh] overflow-y-auto pr-1">
          {/* 媒體檢視區:未裁切全圖 / 完整影片(圖片疊 phase1 主體框) */}
          <div className="flex justify-center bg-canvas rounded-xl p-3">
            <AssetMediaViewer
              key={detail.media_url}
              mediaUrl={detail.media_url}
              mediaMime={detail.media_mime}
              isVideo={isVideo}
              thumbnailUrl={thumbnailUrl || asset?.thumbnail_url}
              subjectBbox={overlayBbox}
              subjectCandidates={overlayCandidates}
              events={eventIndex}
              filename={filename}
            />
          </div>
          {/* Phase 1 資訊區:有 metadata 分區渲染,否則顯示狀態說明 */}
          {metadata ? <AssetMetaPanel metadata={metadata} /> : <StatusNotice asset={asset} />}
        </div>
      )}
    </Modal>
  );
}
