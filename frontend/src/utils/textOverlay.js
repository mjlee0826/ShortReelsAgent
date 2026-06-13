/**
 * 字幕（TextOverlay）純函式集（無副作用，比照 utils/motion.js）。
 *
 * 對應 docs/text_overlay_track_handoff.md（方向二・獨立字幕軌）：字幕已從片段解耦成
 * blueprint.text_overlays 獨立軌（每條帶絕對 start_at/end_at）。本檔負責：
 * - 渲染解析：resolveTimelineTextOverlays（新模型優先、legacy/SSR 回退 per-clip）+ fillOverlayDefaults。
 * - 載入遷移：migrateBlueprintTextOverlays（把 legacy per-clip 字幕一次轉成獨立軌、並清掉舊欄位）。
 * - 定位夾制：resolveVerticalCenterPct / resolveHorizontalCenterPct（clamp 進 safe-area，非 remap）。
 * - 樣式組裝：依 enum 機械式組裝字級／顏色／描邊陰影／底框（renderer 只認對應表，不認樣式名字）。
 * - 進出場：用 Remotion interpolate + Easing，與 ClipComponent 的轉場 fade 同源。
 * - 時間軸排版：assignTextOverlayLanes（重疊字幕 lane-stacking，僅編輯顯示用）。
 */
import { interpolate, Easing } from 'remotion';
import { SUBTITLE_FONT_FAMILY } from './fonts';
import {
  SAFE_AREA,
  SUBTITLE_SIZE_MAP,
  SUBTITLE_COLOR_MAP,
  SUBTITLE_OUTLINE_CONTRAST,
  SUBTITLE_OUTLINE_WIDTH_PX,
  SUBTITLE_DROP_SHADOW,
  SUBTITLE_BG_MAP,
  SUBTITLE_BOX_PADDING,
  SUBTITLE_MAX_WIDTH_PCT,
  SUBTITLE_ANIM_FRAMES,
} from '../components/RemotionPlayer/constants';

// ── 具名常數（禁 magic number）──────────────────────────────────────────────
/** 字幕各欄位的安全可讀預設（與後端 TextOverlay schema 預設對齊；Inspector 也引用，避免重複定義飄移）。 */
export const DEFAULT_OVERLAY = {
  vertical_position: 85,
  horizontal_position: 50,
  size: 'm',
  color: 'white',
  outline: 'outline_shadow',
  background: 'none',
  animation: 'fade',
};
/** 字幕統一字重（caption 慣例為粗體）。 */
const SUBTITLE_FONT_WEIGHT = 700;
/** 行高。 */
const SUBTITLE_LINE_HEIGHT = 1.25;
/** slide_up 進出場的位移量（合成空間 px）。 */
const SLIDE_DISTANCE_PX = 40;
/** pop 進出場的最小縮放（從此放大回 1.0）。 */
const POP_MIN_SCALE = 0.8;

/** 夾在 [min, max] 區間（純工具）。 */
const clamp = (v, min, max) => Math.min(Math.max(v, min), max);

/**
 * 解析某 clip 的字幕設定，回傳 render-ready 物件或 null（無字幕）。
 *
 * 相容兩種來源：新版結構化 `clip.text_overlay`（物件）、legacy `clip.overlay_text`（字串）。
 * 任一來源的 text 為空即視為無字幕（回 null），與後端「空 text = null = 無字幕」契約一致。
 * @param {object} clip 片段資料
 * @returns {object|null} 含預設的字幕設定，或 null
 */
export function resolveTextOverlay(clip) {
  if (!clip) return null;
  const raw = clip.text_overlay;
  // 新結構：物件且 text 非空
  if (raw && typeof raw === 'object') {
    const text = (raw.text || '').trim();
    if (!text) return null;
    return { ...DEFAULT_OVERLAY, ...raw, text };
  }
  // legacy 相容：舊藍圖 / 快照的 overlay_text 字串 → 套預設樣式
  if (typeof clip.overlay_text === 'string' && clip.overlay_text.trim()) {
    return { ...DEFAULT_OVERLAY, text: clip.overlay_text.trim() };
  }
  return null;
}

/**
 * 補齊字幕的樣式預設（確保 size/color/... 與 vertical/horizontal_position 齊全）。
 * 不補 start_at/end_at（屬每條實例的計時，非樣式預設）。
 * @param {object} ov 可能殘缺的字幕物件
 * @returns {object} 補滿樣式預設的字幕物件
 */
export function fillOverlayDefaults(ov) {
  return { ...DEFAULT_OVERLAY, ...(ov || {}) };
}

/**
 * 渲染用：把 blueprint 解析成「可渲染的字幕清單」（每條含 start_at/end_at + 樣式）。
 *
 * 新模型優先：只要有 text_overlays 陣列（即使空）就用它，不回退 legacy。
 * legacy / SSR 未經 store 遷移的舊藍圖：從 timeline 收集 per-clip 字幕，補上該 clip 的絕對起訖。
 * @param {object} blueprint 導演藍圖
 * @returns {Array<object>} 可渲染字幕清單
 */
export function resolveTimelineTextOverlays(blueprint) {
  if (!blueprint) return [];
  if (Array.isArray(blueprint.text_overlays)) {
    return blueprint.text_overlays.map(fillOverlayDefaults);
  }
  // legacy：per-clip text_overlay / overlay_text → 攤平成獨立字幕（start/end 取該 clip）
  const result = [];
  (blueprint.timeline || []).forEach((clip) => {
    const ov = resolveTextOverlay(clip);
    if (ov) result.push({ ...ov, start_at: clip.start_at ?? 0, end_at: clip.end_at ?? 0 });
  });
  return result;
}

/**
 * 載入用：把 legacy（per-clip）字幕一次性遷移成 blueprint.text_overlays 獨立軌，並清掉 clip 上的舊欄位。
 * 讓編輯器與渲染器讀同一份來源（否則會出現「預覽有字幕、但字幕軌空的」不一致）。immutable，回傳新 blueprint。
 * @param {object} blueprint 導演藍圖（可能為 null）
 * @returns {object} 遷移後的新 blueprint
 */
export function migrateBlueprintTextOverlays(blueprint) {
  if (!blueprint) return blueprint;
  // 已是新模型：原樣回傳（未動）
  if (Array.isArray(blueprint.text_overlays)) return blueprint;
  const textOverlays = [];
  const cleanedTimeline = (blueprint.timeline || []).map((clip) => {
    const ov = resolveTextOverlay(clip);
    if (ov) textOverlays.push({ ...ov, start_at: clip.start_at ?? 0, end_at: clip.end_at ?? 0 });
    // 移除 clip 上的 legacy 字幕欄位（immutable 淺拷貝後刪鍵）
    const cleaned = { ...clip };
    delete cleaned.text_overlay;
    delete cleaned.overlay_text;
    return cleaned;
  });
  return { ...blueprint, text_overlays: textOverlays, timeline: cleanedTimeline };
}

/**
 * 把 vertical_position（0=畫面頂、100=畫面底）clamp 進垂直 safe-area。
 * 採 clamp 而非 remap：position 直接是畫面 %（50＝正中、85≈下三分之一），夾進安全帶最直覺。
 * @param {number} verticalPosition 0~100
 * @returns {number} 錨點佔畫面高度的百分比（已夾進安全帶）
 */
export function resolveVerticalCenterPct(verticalPosition) {
  const v = verticalPosition ?? DEFAULT_OVERLAY.vertical_position;
  return clamp(v, SAFE_AREA.TOP_PCT, 100 - SAFE_AREA.BOTTOM_PCT);
}

/**
 * 把 horizontal_position（0=畫面左、100=畫面右、50=置中）clamp 進水平 safe-area。
 * 水平 safe margin 不對稱（右側留大避平台互動按鈕列）。
 * @param {number} horizontalPosition 0~100
 * @returns {number} 錨點佔畫面寬度的百分比（已夾進安全帶）
 */
export function resolveHorizontalCenterPct(horizontalPosition) {
  const h = horizontalPosition ?? DEFAULT_OVERLAY.horizontal_position;
  return clamp(h, SAFE_AREA.LEFT_PCT, 100 - SAFE_AREA.RIGHT_PCT);
}

/**
 * 依顏色 + 描邊樣式組出 textShadow 字串（描邊用四向同色陰影模擬、陰影用柔和投影）。
 * @param {string} color 顏色 enum
 * @param {string} outline 描邊 enum
 * @returns {string} CSS textShadow 值
 */
function buildOutlineShadow(color, outline) {
  if (!outline || outline === 'none') return 'none';
  const layers = [];
  if (outline === 'outline' || outline === 'outline_shadow') {
    const c = SUBTITLE_OUTLINE_CONTRAST[color] ?? SUBTITLE_OUTLINE_CONTRAST.white;
    const w = SUBTITLE_OUTLINE_WIDTH_PX;
    layers.push(
      `-${w}px -${w}px 0 ${c}`,
      `${w}px -${w}px 0 ${c}`,
      `-${w}px ${w}px 0 ${c}`,
      `${w}px ${w}px 0 ${c}`,
    );
  }
  if (outline === 'shadow' || outline === 'outline_shadow') {
    layers.push(SUBTITLE_DROP_SHADOW);
  }
  return layers.join(', ') || 'none';
}

/**
 * 依字幕設定機械式組裝『靜態樣式』（字型 / 字級 / 顏色 / 描邊 / 底框 / 寬度）。
 * 進出場（opacity/transform）由 computeTextAnimationStyle 另算，避免與定位 transform 互蓋。
 * @param {object} overlay resolveTextOverlay 的輸出
 * @returns {object} 可直接套用的 inline style
 */
export function buildSubtitleCssStyle(overlay) {
  const sizePx = SUBTITLE_SIZE_MAP[overlay.size] ?? SUBTITLE_SIZE_MAP.m;
  const color = SUBTITLE_COLOR_MAP[overlay.color] ?? SUBTITLE_COLOR_MAP.white;
  const bg = SUBTITLE_BG_MAP[overlay.background] ?? SUBTITLE_BG_MAP.none;
  const hasBox = overlay.background && overlay.background !== 'none';
  return {
    fontFamily: SUBTITLE_FONT_FAMILY,
    fontWeight: SUBTITLE_FONT_WEIGHT,
    fontSize: `${sizePx}px`,
    lineHeight: SUBTITLE_LINE_HEIGHT,
    color,
    textAlign: 'center',
    textShadow: buildOutlineShadow(overlay.color, overlay.outline),
    maxWidth: `${SUBTITLE_MAX_WIDTH_PCT}%`,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    ...bg,
    ...(hasBox ? { padding: SUBTITLE_BOX_PADDING } : {}),
  };
}

/**
 * 算某一幀的進出場樣式（opacity + transform）。
 *
 * 進場於 [0, ANIM] 幀、出場於 [dur-ANIM, dur] 幀；取兩段的最小顯著度，片段太短時自然重疊。
 * @param {object} params
 * @param {string} params.animation 動畫 enum
 * @param {number} params.frame clip 相對當前幀
 * @param {number} params.durationInFrames 片段顯示總幀數
 * @returns {{opacity:number, transform:string}}
 */
export function computeTextAnimationStyle({ animation, frame, durationInFrames }) {
  if (!animation || animation === 'none') return { opacity: 1, transform: 'none' };
  const a = SUBTITLE_ANIM_FRAMES;
  const dur = durationInFrames || 0;
  // 進場 0→1（ease-out 衝入）、出場 1→0（ease-in 退出）
  const enter = interpolate(frame, [0, a], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.ease),
  });
  const exit = dur > 0
    ? interpolate(frame, [dur - a, dur], [1, 0], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.ease),
    })
    : 1;
  const p = Math.min(enter, exit); // 0~1 顯著度（同時受進、出場制約）
  switch (animation) {
    case 'slide_up': {
      const ty = (1 - p) * SLIDE_DISTANCE_PX; // p=0 在下方、p=1 歸位
      return { opacity: p, transform: `translateY(${ty}px)` };
    }
    case 'pop': {
      const scale = POP_MIN_SCALE + (1 - POP_MIN_SCALE) * p;
      return { opacity: p, transform: `scale(${scale})` };
    }
    case 'fade':
    default:
      return { opacity: p, transform: 'none' };
  }
}

/**
 * 時間軸 lane-stacking：把重疊的字幕貪婪分層，讓每條在字幕軌上都點得到。
 *
 * 依 start_at 升序處理，逐條塞進第一條「結束時間 ≤ 本條 start」的 lane，否則開新 lane。
 * 僅供編輯器時間軸顯示用，與渲染 z-order / 畫面位置無關。
 * @param {Array<object>} overlays 字幕清單（用原始索引對應 selection.textIndex）
 * @returns {{ laneOf: number[], laneCount: number }} laneOf[原始索引]=lane 編號、laneCount=總層數
 */
export function assignTextOverlayLanes(overlays) {
  const list = overlays || [];
  const laneOf = new Array(list.length).fill(0);
  const laneEnds = []; // 各 lane 目前佔用到的結束秒數
  // 依 start_at 升序處理（保留原始索引以回填 laneOf）
  const order = list
    .map((ov, index) => ({ index, start: ov?.start_at ?? 0, end: ov?.end_at ?? 0 }))
    .sort((a, b) => a.start - b.start);
  order.forEach(({ index, start, end }) => {
    let lane = laneEnds.findIndex((e) => e <= start);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(end);
    } else {
      laneEnds[lane] = end;
    }
    laneOf[index] = lane;
  });
  return { laneOf, laneCount: laneEnds.length };
}
