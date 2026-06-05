/**
 * 素材詳情 Phase 1 metadata 的純領域工具（lookup-map / 純函式）。
 *
 * 集中管理：欄位 key → 中文標籤、分區（section）定義、欄位呈現型別（kind），以及數值格式化
 * 純函式。AssetMetaPanel 以這份「資料驅動」定義渲染，三種 metadata（Image / Video /
 * ComplexVideo）以「欄位存在與否」自然適應、不在元件內硬分型別。
 *
 * 全部為無副作用的純函式與具名常數，作為「欄位呈現的唯一來源」，避免 magic number /
 * magic string 散落各處（風格對齊 assetStatus.js）。
 */

// ── 格式化用具名常數（避免 magic number）─────────────────────────────────────
const SECONDS_PER_MINUTE = 60;   // 秒 → mm:ss 換算
const SCORE_MAX = 100;           // 技術 / 美學分滿分（MUSIQ / LAION 皆 0–100）
const PERCENT_SCALE = 100;       // 0–1 比例 → 百分比
const RATIO_DECIMALS = 2;        // 長寬比顯示小數位
const BOOL_TRUE_LABEL = '是';
const BOOL_FALSE_LABEL = '否';
const EMPTY_DISPLAY = '—';       // 無值時的佔位字元

// ── 欄位呈現型別：決定 MetaPanel 用哪種 renderer ─────────────────────────────
export const FIELD_KIND = {
  TEXT: 'text',             // 一般純量（數字 / 字串），用 formatFieldValue
  TAGS: 'tags',             // 字串陣列 → Badge 串
  COLORS: 'colors',         // 色碼字串陣列 → 色塊 swatch
  BBOX: 'bbox',             // SubjectBbox 物件 → 座標列（疊框在媒體區另行處理）
  FACES: 'faces',           // FaceInfo 物件 → 數量 / 佔比
  TRANSCRIPT: 'transcript', // audio_transcript dict → 逐字稿（可摺疊分段）
  SCENE_CUTS: 'sceneCuts',  // 秒數陣列 → 時間點列
  EVENTS: 'events',         // multimodal_event_index → 逐段事件卡
};

// ── 欄位 key → 中文標籤（含巢狀子欄位）──────────────────────────────────────
export const FIELD_LABELS = {
  // 基本資訊
  width: '寬度',
  height: '高度',
  aspect_ratio: '長寬比',
  duration: '時長',
  fps: '幀率',
  creation_time: '拍攝時間',
  location_gps: 'GPS 位置',
  // 品質評分
  technical_score: '技術分',
  aesthetic_score: '美學分',
  // 語意分析
  caption: '描述',
  cinematic_critique: '電影美學評論',
  mood: '情緒',
  camera_angle: '攝影角度',
  time_of_day: '時段',
  // 標籤
  scene_tags: '場景標籤',
  action_tags: '動作標籤',
  // 視覺特徵
  brightness: '亮度',
  color_temperature: '色溫',
  motion_intensity: '動作強度',
  dominant_colors: '主色調',
  // 主體定位
  subject_bbox: '主體保留區',
  crop_feasibility: '裁切可行性',
  // 臉部
  faces: '臉部',
  face_count: '臉部數量',
  has_faces: '偵測到臉部',
  largest_face_ratio: '最大臉部佔比',
  // 音訊分析
  has_speech: '含語音',
  spoken_language: '語言',
  environmental_sounds: '環境音',
  audio_transcript: '語音逐字稿',
  // 影片結構
  scene_cuts: '場景切點',
  // 多模態事件索引
  multimodal_event_index: '多模態事件',
};

// multimodal_event_index 每筆事件的子欄位 → 中文標籤（未列出者退回原 key）
export const EVENT_FIELD_LABELS = {
  start_time: '開始',
  end_time: '結束',
  key_timestamp: '高潮時刻',
  description: '描述',
  event_type: '事件類型',
  audio_cues: '音訊線索',
  visual_intensity: '視覺強度',
  subject_bbox: '主體框',
};

// crop_feasibility 列舉值 → 中文（未列出者退回原值）
const CROP_FEASIBILITY_LABELS = {
  full: '完整可裁',
  partial: '部分可裁',
  limited: '受限',
  center_crop_9_16: '中央裁 9:16',
};

// spoken_language 常見語言碼 → 中文（未列出者退回原碼）
const LANGUAGE_LABELS = {
  zh: '中文',
  en: '英文',
  ja: '日文',
  ko: '韓文',
};

/**
 * 詳情分區定義（依顯示順序）。每區列出其欄位與呈現型別；
 * 某區內所有欄位皆無值時，MetaPanel 整區隱藏（故圖片 / 一般影片 / 複雜影片各自只顯示有資料的區）。
 */
export const META_SECTIONS = [
  {
    id: 'basic',
    title: '基本資訊',
    fields: [
      { key: 'width', kind: FIELD_KIND.TEXT },
      { key: 'height', kind: FIELD_KIND.TEXT },
      { key: 'aspect_ratio', kind: FIELD_KIND.TEXT },
      { key: 'duration', kind: FIELD_KIND.TEXT },
      { key: 'fps', kind: FIELD_KIND.TEXT },
      { key: 'creation_time', kind: FIELD_KIND.TEXT },
      { key: 'location_gps', kind: FIELD_KIND.TEXT },
    ],
  },
  {
    id: 'quality',
    title: '品質評分',
    fields: [
      { key: 'technical_score', kind: FIELD_KIND.TEXT },
      { key: 'aesthetic_score', kind: FIELD_KIND.TEXT },
    ],
  },
  {
    id: 'semantic',
    title: '語意分析',
    fields: [
      { key: 'caption', kind: FIELD_KIND.TEXT },
      { key: 'cinematic_critique', kind: FIELD_KIND.TEXT },
      { key: 'mood', kind: FIELD_KIND.TEXT },
      { key: 'camera_angle', kind: FIELD_KIND.TEXT },
      { key: 'time_of_day', kind: FIELD_KIND.TEXT },
    ],
  },
  {
    id: 'tags',
    title: '標籤',
    fields: [
      { key: 'scene_tags', kind: FIELD_KIND.TAGS },
      { key: 'action_tags', kind: FIELD_KIND.TAGS },
    ],
  },
  {
    id: 'visual',
    title: '視覺特徵',
    fields: [
      { key: 'brightness', kind: FIELD_KIND.TEXT },
      { key: 'color_temperature', kind: FIELD_KIND.TEXT },
      { key: 'motion_intensity', kind: FIELD_KIND.TEXT },
      { key: 'dominant_colors', kind: FIELD_KIND.COLORS },
    ],
  },
  {
    id: 'subject',
    title: '主體定位',
    fields: [
      { key: 'subject_bbox', kind: FIELD_KIND.BBOX },
      { key: 'crop_feasibility', kind: FIELD_KIND.TEXT },
    ],
  },
  {
    id: 'faces',
    title: '臉部',
    fields: [{ key: 'faces', kind: FIELD_KIND.FACES }],
  },
  {
    id: 'audio',
    title: '音訊分析',
    fields: [
      { key: 'has_speech', kind: FIELD_KIND.TEXT },
      { key: 'spoken_language', kind: FIELD_KIND.TEXT },
      { key: 'environmental_sounds', kind: FIELD_KIND.TAGS },
      { key: 'audio_transcript', kind: FIELD_KIND.TRANSCRIPT },
    ],
  },
  {
    id: 'structure',
    title: '影片結構',
    fields: [{ key: 'scene_cuts', kind: FIELD_KIND.SCENE_CUTS }],
  },
  {
    id: 'events',
    title: '多模態事件索引',
    fields: [{ key: 'multimodal_event_index', kind: FIELD_KIND.EVENTS }],
  },
];

// ── 純函式：存在性判斷與格式化 ───────────────────────────────────────────────

/**
 * 判斷某欄位值是否「有內容」可顯示。
 * 空字串 / 空陣列 / 空物件 / null / undefined 視為無；數字（含 0）與布林一律視為有。
 *
 * @param {*} value 欄位值
 * @returns {boolean}
 */
export function hasValue(value) {
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim() !== '';
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value).length > 0;
  return true; // number（含 0）/ boolean 皆視為有值
}

/**
 * 取欄位中文標籤；未定義者退回原 key（不致漏顯）。
 *
 * @param {string} key 欄位 key
 * @returns {string}
 */
export function fieldLabel(key) {
  return FIELD_LABELS[key] || key;
}

/** 秒數 → mm:ss（場景切點 / 影片時長 / 事件時間共用）。 */
export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / SECONDS_PER_MINUTE);
  const rest = total % SECONDS_PER_MINUTE;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}

/** 0–100 分 → 「NN / 100」。 */
export function formatScore(value) {
  return `${Math.round(Number(value) || 0)} / ${SCORE_MAX}`;
}

/** 0–1 比例 → 百分比字串。 */
export function formatPercent(ratio) {
  return `${Math.round((Number(ratio) || 0) * PERCENT_SCALE)}%`;
}

/** 布林 → 是 / 否。 */
export function formatBool(value) {
  return value ? BOOL_TRUE_LABEL : BOOL_FALSE_LABEL;
}

/**
 * 純量欄位（FIELD_KIND.TEXT）的顯示格式化：依 key 套用對應單位 / 換算 / 列舉中文化。
 * 未特別處理的 key 一律轉字串。
 *
 * @param {string} key 欄位 key
 * @param {*} value 欄位值
 * @returns {string}
 */
export function formatFieldValue(key, value) {
  if (!hasValue(value)) return EMPTY_DISPLAY;
  switch (key) {
    case 'duration':
      return formatDuration(value);
    case 'aspect_ratio':
      return Number(value).toFixed(RATIO_DECIMALS);
    case 'fps':
      return `${Math.round(Number(value))} fps`;
    case 'width':
    case 'height':
      return `${value} px`;
    case 'technical_score':
    case 'aesthetic_score':
      return formatScore(value);
    case 'brightness':
    case 'largest_face_ratio':
      return formatPercent(value);
    case 'has_speech':
    case 'has_faces':
      return formatBool(value);
    case 'spoken_language':
      return LANGUAGE_LABELS[value] || value;
    case 'crop_feasibility':
      return CROP_FEASIBILITY_LABELS[value] || value;
    default:
      return String(value);
  }
}

/**
 * 把環境音 / 事件音訊線索等「可能是字串或物件」的陣列項目正規化為可顯示字串。
 * 物件項目以其常見描述欄位或 JSON 退回，避免渲染出 [object Object]。
 *
 * @param {*} item 陣列項目
 * @returns {string}
 */
export function tagText(item) {
  if (typeof item === 'string') return item;
  if (item && typeof item === 'object') {
    return item.label || item.name || item.description || JSON.stringify(item);
  }
  return String(item);
}
