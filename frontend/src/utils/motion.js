/**
 * 自動運鏡引擎（純函式 / 無副作用）。
 *
 * 對應設計文件 docs/editing_capability_roadmap.md §3「動畫 / keyframe + 卡點」的精簡版：
 * 不做手動 keyframe 編輯 UI，改由系統依「素材類型 + 片段索引 + 配樂節拍」自動套用
 * 有變化、會踩拍的運鏡（Ken Burns 推近 / 拉遠 / 平移 + 卡點 punch）。
 *
 * 設計重點：
 * - 朝主體：縮放支點（transformOrigin）取自片段既有 object_position（主體 bbox 中心），
 *   故推近時往主體靠，免再抓 bbox。
 * - 變化：auto 模式下相鄰圖片輪替不同向運鏡，避免整支同向慢推的「幻燈片感」。
 * - 卡點：落在片段內的重拍各疊一個短促放大脈衝，製造踩拍的「snappy」年輕感。
 * - 退化：無節拍（舊藍圖 / 換曲後）時僅保留變化型 base 運鏡、不報錯、無 punch。
 *
 * 與 Remotion fade 同源使用 interpolate；本模組由 ClipComponent 於每一幀呼叫。
 */
import { interpolate, Easing } from 'remotion';

// ── 具名常數（禁 magic number）──────────────────────────────────────────────
/** Ken Burns 推近 / 拉遠的縮放幅度（1.0 → 1.0+此值）。 */
const KEN_BURNS_ZOOM = 0.12;
/** 平移類運鏡的底縮放：須略大於 1，留出位移空間，避免平移時露出畫面邊緣。
 *  取 1.12 使單側溢出約 6%，大於下方位移量 3%，平移到底仍有安全邊界、不露邊。 */
const PAN_BASE_SCALE = 1.12;
/** 平移的單側最大位移（百分比，相對自身尺寸）；須小於底縮放溢出量以免露邊。 */
const PAN_SHIFT_PCT = 3;
/** 卡點脈衝的瞬間放大幅度（額外縮放比例）。 */
const PUNCH_SCALE = 0.05;
/** 卡點脈衝衝上去的幀數（attack）。 */
const PUNCH_ATTACK_FRAMES = 2;
/** 卡點脈衝回穩的幀數（decay）。 */
const PUNCH_DECAY_FRAMES = 7;
/** 兩次卡點脈衝的最小間隔（秒）：避免每個重拍都 punch 造成「持續抖動」，只在夠稀疏處才彈一下。 */
const MIN_PUNCH_INTERVAL_SEC = 1.2;

/** 運鏡 preset 名稱（具名常數，供前端下拉與本引擎共用詞彙）。 */
export const MOTION = {
  AUTO: 'auto',
  NONE: 'none',
  STATIC: 'static',
  PUSH_IN: 'push_in',
  PULL_OUT: 'pull_out',
  PAN: 'pan',
  PAN_LEFT: 'pan_left',
  PAN_RIGHT: 'pan_right',
  PUNCH: 'punch',
};

/**
 * auto 模式下，圖片可用的有變化運鏡循環。
 * 以片段索引輪替，確保相鄰圖片不同向、不致看起來像同向慢推的幻燈片。
 */
const AUTO_IMAGE_CYCLE = [MOTION.PUSH_IN, MOTION.PAN_LEFT, MOTION.PULL_OUT, MOTION.PAN_RIGHT];

/**
 * 決定某片段實際採用的運鏡 preset。
 *
 * 規則：明確覆寫（非 auto）優先；auto 時——影片本身已有運動，預設靜止（僅保留卡點 punch），
 * 避免與既有運鏡疊加打架；圖片則依索引輪替 AUTO_IMAGE_CYCLE 取得變化。
 * @param {object} clip 片段資料（讀 clip.motion 覆寫值）
 * @param {number} index 片段在時間軸的索引（用於輪替變化）
 * @param {boolean} isImage 是否為圖片素材
 * @returns {string} preset 名稱
 */
export function resolveClipMotion(clip, index, isImage) {
  const explicit = clip?.motion;
  if (explicit && explicit !== MOTION.AUTO) return explicit;
  // 影片：預設靜止（base 不動），只接受卡點 punch
  if (!isImage) return MOTION.STATIC;
  // 圖片：依索引輪替不同向運鏡
  return AUTO_IMAGE_CYCLE[index % AUTO_IMAGE_CYCLE.length];
}

/**
 * 算某 preset 在進度 p（0~1）當下的 base 縮放與位移。
 * @param {string} presetName preset 名稱
 * @param {number} p 進度 0~1（已套 easing）
 * @returns {{scale:number, tx:number, ty:number}} 縮放與位移（位移為百分比）
 */
function basePreset(presetName, p) {
  switch (presetName) {
    case MOTION.PUSH_IN:
      return { scale: 1 + KEN_BURNS_ZOOM * p, tx: 0, ty: 0 };
    case MOTION.PULL_OUT:
      return { scale: 1 + KEN_BURNS_ZOOM * (1 - p), tx: 0, ty: 0 };
    case MOTION.PAN_LEFT:
    case MOTION.PAN:
      // 由右往左掃：tx 從 +PAN_SHIFT_PCT 漸變到 -PAN_SHIFT_PCT
      return { scale: PAN_BASE_SCALE, tx: PAN_SHIFT_PCT * (1 - 2 * p), ty: 0 };
    case MOTION.PAN_RIGHT:
      return { scale: PAN_BASE_SCALE, tx: PAN_SHIFT_PCT * (2 * p - 1), ty: 0 };
    case MOTION.PUNCH:
      // 只靠卡點脈衝，base 不動
      return { scale: 1, tx: 0, ty: 0 };
    case MOTION.NONE:
    case MOTION.STATIC:
    default:
      return { scale: 1, tx: 0, ty: 0 };
  }
}

/**
 * 卡點脈衝：取當前幀距離各重拍幀的最強脈衝量（attack 衝上、decay 回穩）。
 * @param {number} frame 片段內的當前幀（相對片段起點）
 * @param {number[]} beatsInClipFrames 落在此片段內的重拍幀清單（相對片段起點）
 * @returns {number} 額外縮放比例（0 表示無脈衝）
 */
function punchAt(frame, beatsInClipFrames) {
  if (!beatsInClipFrames || beatsInClipFrames.length === 0) return 0;
  const total = PUNCH_ATTACK_FRAMES + PUNCH_DECAY_FRAMES;
  let strongest = 0;
  for (const beat of beatsInClipFrames) {
    const delta = frame - beat;
    if (delta < 0 || delta > total) continue; // 不在此脈衝影響範圍
    const amount = delta <= PUNCH_ATTACK_FRAMES
      ? interpolate(delta, [0, PUNCH_ATTACK_FRAMES], [0, PUNCH_SCALE], { extrapolateRight: 'clamp' })
      : interpolate(delta, [PUNCH_ATTACK_FRAMES, total], [PUNCH_SCALE, 0], { extrapolateRight: 'clamp' });
    if (amount > strongest) strongest = amount;
  }
  return strongest;
}

/**
 * 稀疏化重拍：貪婪保留彼此間隔 ≥ MIN_PUNCH_INTERVAL_SEC 的重拍，其餘丟棄。
 *
 * librosa 的 beats 是「每一拍」（約每 0.5 秒一個），若每拍都 punch 會變成持續抖動；
 * 故在送進渲染前先抽稀，讓 punch 成為「偶爾彈一下」的卡點重音，而非震動。
 * @param {number[]} frames 片段內重拍幀（相對片段起點）
 * @param {number} fps 幀率（換算最小間隔）
 * @returns {number[]} 抽稀後的重拍幀
 */
export function thinBeatFrames(frames, fps) {
  if (!frames || frames.length === 0) return frames;
  const minGap = MIN_PUNCH_INTERVAL_SEC * (fps || 30);
  const sorted = [...frames].sort((a, b) => a - b);
  const kept = [];
  let last = -Infinity;
  for (const f of sorted) {
    if (f - last >= minGap) {
      kept.push(f);
      last = f;
    }
  }
  return kept;
}

/**
 * 算出某一幀的運鏡樣式（transform + transformOrigin）。
 *
 * 最終縮放 = 片段既有 scale × preset base 縮放 ×（1 + 卡點脈衝）；
 * 縮放支點設為 object_position，使推近往主體靠。
 * @param {object} params
 * @param {string} params.presetName 已解析的 preset 名稱
 * @param {number} params.frame 片段內當前幀
 * @param {number} params.durationInFrames 片段顯示總幀數（決定 base 運鏡進度）
 * @param {number[]} params.beatsInClipFrames 片段內重拍幀清單
 * @param {number} params.baseScale 片段既有 scale（與運鏡相乘合成）
 * @param {string} params.objectPosition 主體定位（作為縮放支點）
 * @returns {{transform:string, transformOrigin:string}} 可直接套用的樣式
 */
export function computeMotionStyle({
  presetName,
  frame,
  durationInFrames,
  beatsInClipFrames,
  baseScale = 1,
  objectPosition = '50% 50%',
}) {
  // 進度套 ease-in-out，讓 base 運鏡頭尾更柔順
  const progress = durationInFrames > 0
    ? interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.inOut(Easing.ease),
    })
    : 0;
  const base = basePreset(presetName, progress);
  // 'none' 代表完全靜止（連卡點都不彈）；其餘 preset 才疊加卡點脈衝
  const punch = presetName === MOTION.NONE ? 0 : punchAt(frame, beatsInClipFrames);
  const scale = baseScale * base.scale * (1 + punch);
  return {
    transform: `translate(${base.tx}%, ${base.ty}%) scale(${scale})`,
    transformOrigin: objectPosition,
  };
}
