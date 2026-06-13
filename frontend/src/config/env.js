/**
 * 前端執行環境設定（集中讀取 import.meta.env）。
 *
 * 先前 api.service / useProgressSocket / main.jsx 各自讀取 VITE_* 並重複 localhost fallback，
 * 集中於此作為唯一來源，避免散落與不一致。
 */

/** 後端 base URL 的預設值（本機開發；具名避免 magic string）。 */
const DEFAULT_BACKEND_URL = 'http://localhost:5174';

/** 後端 API base URL。 */
export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || DEFAULT_BACKEND_URL;

/** 換取 access token 時指定的 API resource（須與後端 LOGTO_AUDIENCE 對應）。 */
export const API_RESOURCE = import.meta.env.VITE_LOGTO_API_RESOURCE;

/** Logto 端點。 */
export const LOGTO_ENDPOINT = import.meta.env.VITE_LOGTO_ENDPOINT || '';

/** Logto 應用 ID。 */
export const LOGTO_APP_ID = import.meta.env.VITE_LOGTO_APP_ID || '';
