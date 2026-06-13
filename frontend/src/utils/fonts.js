/**
 * 字幕字型載入（Noto Sans TC，含繁中字符）。
 *
 * 經 @remotion/google-fonts 動態載入 Google Fonts：`loadFont()` 內部會掛 delayRender，
 * 確保 SSR（npx remotion render）算圖前字型就緒；並以 unicode-range 切分，瀏覽器只抓
 * 實際用到的字段，不會一次下載整套 CJK。於 remotion.index.jsx（SSR 根）與字幕元件匯入即生效。
 *
 * ⚠️ 限制：render 當下需可連到 Google Fonts。離線環境（如部分 Leibniz 機）需改自帶字型檔。
 */
import { loadFont } from '@remotion/google-fonts/NotoSansTC';

// loadFont() 同步回傳 CSS fontFamily 名稱（"Noto Sans TC"），副作用為注入 @font-face 並掛 delayRender。
const { fontFamily } = loadFont();

/** 字幕統一使用的字型家族名稱（供字幕樣式組裝取用）。 */
export const SUBTITLE_FONT_FAMILY = fontFamily;
