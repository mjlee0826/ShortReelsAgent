/**
 * 後端錯誤訊息抽取工具（共用 helper，避免 DRY 違規）。
 *
 * 全站的 store / page 在 catch 區塊都需要把 axios 錯誤轉成一段可顯示的中文訊息，
 * 先前各處重複 `error.response?.data?.detail || error.message || String(error)`，
 * 集中於此作為唯一來源。
 */

/**
 * 從 axios 錯誤統一抽出可讀訊息。
 * 後端 detail 可能是字串（一般 HTTPException）或物件（{ code, message }），兩種皆涵蓋；
 * 皆取不到時退回 error.message，再退回字串化結果。
 * @param {unknown} error axios 攔截後的錯誤物件
 * @returns {string} 可直接顯示的錯誤訊息
 */
export function extractErrorMessage(error) {
  const detail = error?.response?.data?.detail;
  // detail 為物件時取其 message 欄位；為字串時直接用
  const fromDetail = typeof detail === 'string' ? detail : detail?.message;
  return fromDetail || error?.message || String(error);
}
