/**
 * 素材卡片的純領域工具（lookup-map / Strategy）。
 *
 * 集中管理：素材狀態 → 顯示樣式、詳情文字的收斂、策略選項、縮圖比例等具名常數。
 * 全部為無副作用的純函式與具名常數，供 AssetCard / StrategyToggle / SelectionToolbar 共用，
 * 避免狀態判斷與 magic string 散落各處，並作為「狀態樣式的唯一來源」以利各卡嚴格等高。
 */

// --- 素材狀態（後端持久化 unprocessed/success/rejected/error；processing 由 WebSocket 即時帶入）---

/** 素材狀態 key（與 STATUS_META 對應）。 */
export const ASSET_STATUS = {
  UNPROCESSED: 'unprocessed',
  PROCESSING: 'processing',
  SUCCESS: 'success',
  REJECTED: 'rejected',
  ERROR: 'error',
};

/**
 * 狀態 → 顯示樣式（tone 對應 Badge 語意色；pulse 為是否顯示脈動點）。
 * 為唯一的狀態樣式來源，確保所有卡片以「同一固定槽位、只變色/變字/脈動」呈現狀態差異。
 */
export const STATUS_META = {
  [ASSET_STATUS.UNPROCESSED]: { key: ASSET_STATUS.UNPROCESSED, tone: 'neutral', label: '未處理', pulse: false },
  [ASSET_STATUS.PROCESSING]: { key: ASSET_STATUS.PROCESSING, tone: 'info', label: '處理中', pulse: true },
  [ASSET_STATUS.SUCCESS]: { key: ASSET_STATUS.SUCCESS, tone: 'success', label: '成功', pulse: false },
  [ASSET_STATUS.REJECTED]: { key: ASSET_STATUS.REJECTED, tone: 'warning', label: '拒絕', pulse: false },
  [ASSET_STATUS.ERROR]: { key: ASSET_STATUS.ERROR, tone: 'danger', label: '失敗', pulse: false },
};

/**
 * 取狀態對應的顯示樣式；查無對應時回退為「未處理」。
 *
 * @param {string} status 生效狀態
 * @returns {{key:string, tone:string, label:string, pulse:boolean}}
 */
export function resolveStatusMeta(status) {
  return STATUS_META[status] || STATUS_META[ASSET_STATUS.UNPROCESSED];
}

// --- 卡片詳情（單行；恆回字串，空字串保留固定空行確保各卡等高）---

/** 處理中詳情前綴（具名，避免 magic string）。 */
const PROCESSING_DETAIL_PREFIX = '分析中：';

/**
 * 依狀態挑選要顯示的單行詳情文字。恆回字串：拒絕→reason、失敗→error、
 * 處理中且有 stage→「分析中：{stage}」，其餘→空字串（保留空行使資訊區等高）。
 *
 * @param {{status:string, reason?:string, error?:string, liveStage?:?string}} args
 * @returns {string}
 */
export function buildDetailText({ status, reason, error, liveStage }) {
  if (status === ASSET_STATUS.REJECTED) return reason || '';
  if (status === ASSET_STATUS.ERROR) return error || '';
  if (status === ASSET_STATUS.PROCESSING && liveStage) return `${PROCESSING_DETAIL_PREFIX}${liveStage}`;
  return '';
}

/** 詳情文字依狀態著色的 class（醒目化）；查無對應時回退為最淡的 ink-faint。 */
const DETAIL_TONE_CLASS = {
  [ASSET_STATUS.ERROR]: 'text-danger',
  [ASSET_STATUS.REJECTED]: 'text-warning',
  [ASSET_STATUS.PROCESSING]: 'text-info',
};
const DETAIL_TONE_DEFAULT = 'text-ink-faint';

/**
 * 取詳情文字的著色 class。
 *
 * @param {string} status 生效狀態
 * @returns {string} Tailwind 文字色 class
 */
export function detailTone(status) {
  return DETAIL_TONE_CLASS[status] || DETAIL_TONE_DEFAULT;
}

// --- 策略（Simple / Complex；值需與後端一致）---

/** 策略值（具名常數，避免 magic string）。 */
export const STRATEGY = {
  SIMPLE: 'simple',
  COMPLEX: 'complex',
};

/** 策略切換的顯示順序。 */
export const STRATEGY_OPTIONS = [STRATEGY.SIMPLE, STRATEGY.COMPLEX];

/** 策略值 → 顯示文字。 */
export const STRATEGY_LABEL = {
  [STRATEGY.SIMPLE]: 'Simple',
  [STRATEGY.COMPLEX]: 'Complex',
};

// --- 縮圖 ---

/** 縮圖長寬比（具名常數，便於統一調整；3:2 橫向、裁切最少）。 */
export const THUMB_ASPECT = 'aspect-[3/2]';
