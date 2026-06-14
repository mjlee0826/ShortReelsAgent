/**
 * 調色 (color grading) 引擎（純函式 / 無副作用）。
 *
 * 對應設計文件 docs/editing_capability_roadmap.md §5「能力層 primitive + 命名 preset」：
 * 把「寫死的濾鏡名 → 固定 CSS 字串」拆成「資料(命名 preset) + 機械式組裝函式」。
 * renderer 只認得 primitive、不認得 look 的名字，故**新增一個 look = 在 colorPresets.json
 * 加一筆資料**即可，本檔永遠不需改動（與 utils/motion.js 同設計風格）。
 *
 * 解析鏈：clip.color({preset, ...覆寫}) → resolveColor 合併成一包扁平 primitive → buildCssFilter
 * 機械式組成 CSS filter 字串。preset 數值與 primitive 範圍皆同源於 colorPresets.json (SSOT)。
 */
import COLOR from '../config/colorPresets.json';

/** 「無調色」的 preset 名（具名常數，避免 magic string）。 */
const PRESET_NONE = 'none';
/** 無任何 primitive 時的 CSS filter 值。 */
const CSS_FILTER_NONE = 'none';

/**
 * 把 clip.color（preset 引用 + 個別覆寫）解析成一包扁平的 primitive 數值。
 *
 * 規則：先取 preset 的基底數值，再以 color 物件中『有填值(非 null)』的 primitive 逐一覆寫；
 * primitive 留空＝沿用 preset 對應值。
 * @param {object} [color] 片段的 color 物件（可為 undefined）
 * @returns {Object<string, number>} 合併後的 primitive → 數值
 */
export function resolveColor(color) {
  const base = COLOR.presets[color?.preset ?? PRESET_NONE] ?? {};
  const merged = { ...base };
  // 只認得 colorPresets.json 定義的 primitive；逐顆取片段覆寫值（有填才覆寫）
  for (const key of Object.keys(COLOR.primitives)) {
    if (color?.[key] != null) merged[key] = color[key];
  }
  return merged;
}

/**
 * 把一包 primitive 數值機械式組成 CSS filter 字串。
 *
 * 等於預設值(=CSS no-op，如 brightness(1)/blur(0))的 primitive 直接略過，避免輸出無意義片段；
 * 全部略過時回傳 'none'。primitive 的迭代順序即 CSS filter 串接順序（由 JSON key 順序決定）。
 * 本函式不認得任何 look 名稱，故新增 look 永不需改它。
 * @param {Object<string, number>} values resolveColor 的輸出
 * @returns {string} 可直接套用於 style.filter 的字串
 */
export function buildCssFilter(values) {
  const parts = [];
  for (const [key, meta] of Object.entries(COLOR.primitives)) {
    const v = values[key];
    if (v == null || v === meta.default) continue; // 未設定或等於預設(no-op)就不輸出
    parts.push(`${meta.css}(${v}${meta.unit})`);
  }
  return parts.join(' ') || CSS_FILTER_NONE;
}

/**
 * 舊藍圖相容：把 legacy 的 filter 字串（cinematic / grayscale / blur / none）轉成 color 物件。
 *
 * 方向三前的藍圖每段是 `filter: "cinematic"`；這些名稱現已是 colorPresets.json 的 preset 名，
 * 故直接當 preset 引用即可，舊持久化藍圖 / snapshot 無需遷移就能正確渲染。
 * @param {string} [filter] legacy filter 值
 * @returns {{preset: string}} 等價的 color 物件
 */
export function legacyFilterToColor(filter) {
  return { preset: !filter || filter === PRESET_NONE ? PRESET_NONE : filter };
}
