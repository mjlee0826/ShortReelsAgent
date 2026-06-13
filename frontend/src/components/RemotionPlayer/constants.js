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

/**
 * 片段「提前掛載」的前置秒數（實際幀數 = 此值 × fps）。
 *
 * 讓下一段的 <video> 在切換到它之前就先掛載、載入並 seek 到起始幀（此期間隱形且靜音），
 * 待播放頭抵達交界時已就緒 → 消除即時 mount/decode/seek 造成的交界卡頓。
 * 注意：值越大、同時掛載的 <video> 越多（快速剪輯時尤甚），會增加瀏覽器解碼負擔；1 秒為平衡點。
 */
export const PREMOUNT_LEAD_SECONDS = 1;

/** LLM 輸出的語意濾鏡名稱 → 合法 CSS filter 值（集中管理，避免散落於元件）。 */
export const FILTER_MAP = {
  cinematic: 'contrast(1.1) saturate(0.85) brightness(0.9)',
  grayscale: 'grayscale(1)',
  blur: 'blur(4px)',
  none: 'none',
};

/** 畫中畫（PiP）子畫面的版面常數（避免散落 magic number 於 inline style）。 */
export const PIP_STYLE = {
  WIDTH: '35%',
  BORDER_RADIUS: '16px',
  BORDER: '3px solid white',
  BOX_SHADOW: '0 10px 25px rgba(0,0,0,0.5)',
  Z_INDEX: 20,
  EDGE_OFFSET: '3%', // 距畫面邊緣的內縮量（四角共用）
};

// ──────────────────────────────────────────────────────────────────────────────
// 字幕（TextOverlay）相關常數：集中管理，渲染端只做機械式組裝（比照 FILTER_MAP）。
// ──────────────────────────────────────────────────────────────────────────────

/**
 * 平台 UI 安全區（佔畫面高度的百分比）：字幕垂直錨點會被線性映進 [TOP_PCT, 100-BOTTOM_PCT]，
 * 確保任何 vertical_position 都不壓到 IG/TikTok 上方狀態列與下方說明 / 互動按鈕。
 */
export const SAFE_AREA = {
  TOP_PCT: 12, // 頂部保留：狀態列 / 帳號資訊
  BOTTOM_PCT: 18, // 底部保留：說明文字 / 互動按鈕列
};

/** 字幕 z 軸（疊在主畫面與 PiP 之上）。 */
export const SUBTITLE_Z_INDEX = 50;

/** 字級分級 → 合成空間（1080×1920）的字體大小（px）。 */
export const SUBTITLE_SIZE_MAP = {
  s: 48,
  m: 64,
  l: 84,
  xl: 110,
};

/** 字幕顏色 enum → 實際色碼（accent 與 index.css 的 --color-accent 同步）。 */
export const SUBTITLE_COLOR_MAP = {
  white: '#ffffff',
  black: '#141414',
  yellow: '#ffe14d',
  accent: '#6d5efc',
};

/** 各字幕顏色對應的『描邊對比色』：淺字配深邊、深字配淺邊，確保描邊真的拉開對比。 */
export const SUBTITLE_OUTLINE_CONTRAST = {
  white: '#000000',
  black: '#ffffff',
  yellow: '#000000',
  accent: '#000000',
};

/** 描邊粗細（合成空間 px）。 */
export const SUBTITLE_OUTLINE_WIDTH_PX = 2;

/** 柔和投影字串（shadow / outline_shadow 用）。 */
export const SUBTITLE_DROP_SHADOW = '0 4px 14px rgba(0,0,0,0.55)';

/** 底框 enum → 樣式片段（none 為空；其餘墊底以保可讀性）。 */
export const SUBTITLE_BG_MAP = {
  none: {},
  solid: { backgroundColor: 'rgba(0,0,0,0.55)' },
  blur: { backgroundColor: 'rgba(0,0,0,0.30)', backdropFilter: 'blur(8px)' },
  pill: { backgroundColor: 'rgba(0,0,0,0.55)', borderRadius: '9999px' },
};

/** 有底框時的內距（合成空間 px；none 不套用）。 */
export const SUBTITLE_BOX_PADDING = '14px 28px';

/** 文字塊相對畫面寬度的最大寬度（%）：避免長句頂到左右邊。 */
export const SUBTITLE_MAX_WIDTH_PCT = 86;

/** 字幕進出場動畫的幀數（進場 attack / 出場 decay 共用；約 0.27s@30fps）。 */
export const SUBTITLE_ANIM_FRAMES = 8;
