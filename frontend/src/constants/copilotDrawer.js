/**
 * AI Copilot 抽屜的尺寸常數（SSOT）。
 *
 * 先前寬度以 Tailwind 字面值 w-[440px] 寫死在 AiCopilotDrawer；改為可拖曳調整後，
 * 寬度範圍、預設值與持久化鍵集中於此，避免 magic number 散落於元件與 hook。
 */

/** 抽屜預設寬度（px）：使用者尚未拖曳調整過時採用。 */
export const COPILOT_DEFAULT_WIDTH = 480;

/** 抽屜最小寬度（px）：再窄對話內容會擠壓難讀。 */
export const COPILOT_MIN_WIDTH = 360;

/** 抽屜最大寬度（px）：上限以免蓋滿整個編輯區（仍會再受視窗寬度夾限）。 */
export const COPILOT_MAX_WIDTH = 880;

/** 寬度持久化的 localStorage 鍵：跨重整 / 重開記住使用者偏好。 */
export const COPILOT_WIDTH_STORAGE_KEY = 'copilotDrawerWidth';
