/**
 * 專案儀表板的純領域工具（Strategy / lookup-map）。
 *
 * 集中管理：多維狀態 → 單一主狀態的收斂、確定性漸層封面、排序選項。
 * 全部為無副作用的純函式與具名常數，供 ProjectCard / ProjectToolbar / ProjectDashboard 共用，
 * 避免狀態判斷與 magic string 散落各處。
 */

// --- 後端欄位的字串常數（對應 backend/api/projects.py 與 ingestion_engine.models）---

/** 雲端來源識別字串（與後端 SOURCE_GDRIVE 對應）。 */
export const SOURCE_GDRIVE = 'gdrive';

/** Phase 1 背景預跑狀態。 */
const PHASE1_STATUS = {
  PENDING: 'pending',
  // 正在下載 / 標準化素材（尚未進入感知分析）；呈現「處理素材中」
  INGESTING: 'ingesting',
  PROCESSING: 'processing',
  DONE: 'done',
  FAILED: 'failed',
  // 已下載、依設定刻意略過自動分析，待使用者到素材頁手動觸發（與 PENDING 同呈現「等待分析」）
  SKIPPED: 'skipped',
};

/** 雲端同步狀態。 */
const SYNC_STATUS = {
  ACTIVE: 'active',
  PAUSED_AUTH_ERROR: 'paused_auth_error',
  ERROR: 'error',
};

// --- 主狀態（卡片右上唯一膠囊）---

/** 收斂後的主狀態 key（與 STATUS_META 對應）。 */
export const PROJECT_STATUS = {
  AUTH_EXPIRED: 'auth_expired',
  SYNC_FAILED: 'sync_failed',
  ANALYZE_FAILED: 'analyze_failed',
  INGESTING: 'ingesting',
  ANALYZING: 'analyzing',
  WAITING: 'waiting',
  EDITABLE: 'editable',
  READY: 'ready',
  DRAFT: 'draft',
};

/**
 * 主狀態 → 顯示樣式（tone 對應 Badge 的語意色；pulse 為是否顯示脈動點）。
 * 為唯一的狀態樣式來源，確保所有卡片以「同一個固定槽位、只變色/變字」呈現狀態差異。
 */
export const STATUS_META = {
  [PROJECT_STATUS.AUTH_EXPIRED]: { key: PROJECT_STATUS.AUTH_EXPIRED, tone: 'danger', label: '授權失效', pulse: false },
  [PROJECT_STATUS.SYNC_FAILED]: { key: PROJECT_STATUS.SYNC_FAILED, tone: 'danger', label: '同步失敗', pulse: false },
  [PROJECT_STATUS.ANALYZE_FAILED]: { key: PROJECT_STATUS.ANALYZE_FAILED, tone: 'danger', label: '分析失敗', pulse: false },
  [PROJECT_STATUS.INGESTING]: { key: PROJECT_STATUS.INGESTING, tone: 'info', label: '處理素材中', pulse: true },
  [PROJECT_STATUS.ANALYZING]: { key: PROJECT_STATUS.ANALYZING, tone: 'info', label: '分析中', pulse: true },
  [PROJECT_STATUS.WAITING]: { key: PROJECT_STATUS.WAITING, tone: 'info', label: '等待分析', pulse: false },
  [PROJECT_STATUS.EDITABLE]: { key: PROJECT_STATUS.EDITABLE, tone: 'success', label: '可編輯', pulse: false },
  [PROJECT_STATUS.READY]: { key: PROJECT_STATUS.READY, tone: 'accent', label: '待生成', pulse: false },
  [PROJECT_STATUS.DRAFT]: { key: PROJECT_STATUS.DRAFT, tone: 'neutral', label: '草稿', pulse: false },
};

/**
 * 將專案的多維狀態（source / phase1_status / sync_status / has_blueprint / last_sync_error）
 * 依優先序收斂為「單一主狀態」。命中即回傳對應的 STATUS_META 條目。
 *
 * @param {object} project ProjectMeta
 * @returns {{key:string, tone:string, label:string, pulse:boolean}}
 */
export function deriveProjectStatus(project) {
  // 1. 授權失效（同步暫停）— 最需使用者介入
  if (project.sync_status === SYNC_STATUS.PAUSED_AUTH_ERROR) return STATUS_META[PROJECT_STATUS.AUTH_EXPIRED];
  // 2. 一般同步錯誤（暫時性，會自動重試）
  if (project.last_sync_error || project.sync_status === SYNC_STATUS.ERROR) return STATUS_META[PROJECT_STATUS.SYNC_FAILED];
  // 3. Phase 1 分析失敗
  if (project.phase1_status === PHASE1_STATUS.FAILED) return STATUS_META[PROJECT_STATUS.ANALYZE_FAILED];
  // 4. 下載 / 標準化素材中（尚未進入感知分析；脈動）
  if (project.phase1_status === PHASE1_STATUS.INGESTING) return STATUS_META[PROJECT_STATUS.INGESTING];
  // 5. 分析中（脈動）
  if (project.phase1_status === PHASE1_STATUS.PROCESSING) return STATUS_META[PROJECT_STATUS.ANALYZING];
  // 6. 等待分析（已建立尚未開始，或已下載但依設定刻意略過自動分析、待手動觸發）
  if (project.phase1_status === PHASE1_STATUS.PENDING ||
      project.phase1_status === PHASE1_STATUS.SKIPPED) return STATUS_META[PROJECT_STATUS.WAITING];
  // 7. 已有藍圖 → 可進編輯器編輯
  if (project.has_blueprint) return STATUS_META[PROJECT_STATUS.EDITABLE];
  // 8. 分析完成但尚無藍圖 → 待生成
  if (project.phase1_status === PHASE1_STATUS.DONE) return STATUS_META[PROJECT_STATUS.READY];
  // 9. 其他（本地草稿）
  return STATUS_META[PROJECT_STATUS.DRAFT];
}

// --- 封面 ---

/** 封面長寬比（具名常數，便於統一調整）。 */
export const COVER_ASPECT = 'aspect-[16/10]';

// --- 排序 ---

/** 排序鍵（具名常數）。 */
export const SORT_KEY = {
  RECENT: 'recent',
  NAME: 'name',
};

/** 排序下拉選項（餵給 ui/Select 的 options=[{value,label}]）。 */
export const SORT_OPTIONS = [
  { value: SORT_KEY.RECENT, label: '最近修改' },
  { value: SORT_KEY.NAME, label: '名稱' },
];
