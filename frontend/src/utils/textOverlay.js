/**
 * 字幕（TextOverlay）render-time 純函式集（無副作用，比照 utils/motion.js）。
 *
 * 對應 docs/editing_capability_roadmap.md §4 方向二（精簡版）：把 clip 的結構化 text_overlay
 * 解析成可渲染的樣式與定位。三件事：
 * - resolveTextOverlay：相容層（新 text_overlay 物件／legacy overlay_text 字串）+ 填預設。
 * - 樣式組裝：依 enum 機械式組裝字級／顏色／描邊陰影／底框（renderer 不認得樣式名字，只認對應表）。
 * - 進出場：用 Remotion interpolate + Easing，與 ClipComponent 的轉場 fade 同源。
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
 * 把 LLM 的 vertical_position（0=畫面頂、100=畫面底）線性映進 safe-area 中心線範圍，
 * 確保字幕錨點永遠落在安全帶內、不撞平台 UI。
 * @param {number} verticalPosition 0~100
 * @returns {number} 錨點佔畫面高度的百分比（已夾進安全帶）
 */
export function resolveVerticalCenterPct(verticalPosition) {
  const v = clamp(verticalPosition ?? DEFAULT_OVERLAY.vertical_position, 0, 100);
  const min = SAFE_AREA.TOP_PCT;
  const max = 100 - SAFE_AREA.BOTTOM_PCT;
  return min + (v / 100) * (max - min);
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
