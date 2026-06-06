/**
 * useProgressSocket：訂閱後端 Phase 1 進度 WebSocket 的 Hook（Observer Pattern 前端側）。
 *
 * 回傳一個 connect(jobId) 函式：呼叫即連到 /ws/progress/{job_id}，把收到的每個事件回呼給
 * onEvent；收到 job_finished / job_error 終端事件後自動關閉。連線錯誤 / 斷線只記 log，不拋出，
 * 確保進度面板問題不影響頁面其餘功能。元件卸載時自動關閉殘留連線。
 *
 * onClosedWithoutTerminal（選填）：連線在「未收到終端事件」且「非主動關閉」下斷掉時回呼（如後端
 * 重啟）。供呼叫端回抓最終狀態、清除處理中旗標，避免素材卡片永久卡在「處理中」。
 */
import { useCallback, useEffect, useRef } from 'react';
import { useLogto } from '@logto/react';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5174';
// 換取 access token 時指定的 API resource（與 api.service 一致）
const API_RESOURCE = import.meta.env.VITE_LOGTO_API_RESOURCE;
// 收到這些事件型態即視為工作流結束，主動關閉連線
const TERMINAL_EVENT_TYPES = new Set(['job_finished', 'job_error']);

/** 把後端 http(s) base 轉成 ws(s) base。 */
function toWebSocketBase(httpUrl) {
  return httpUrl.replace(/^http/, 'ws');
}

export default function useProgressSocket(onEvent, onClosedWithoutTerminal) {
  const { getAccessToken } = useLogto();
  const socketRef = useRef(null);
  // 以 ref 持有最新 callback，避免 connect 因 callback 變動而重建（在 effect 內更新，不在 render 期）
  const onEventRef = useRef(onEvent);
  useEffect(() => { onEventRef.current = onEvent; }, [onEvent]);
  // 同理以 ref 持有最新「異常斷線」回呼
  const onClosedRef = useRef(onClosedWithoutTerminal);
  useEffect(() => { onClosedRef.current = onClosedWithoutTerminal; }, [onClosedWithoutTerminal]);

  // 關閉目前連線（若有）；標記為主動關閉，使其 onclose 不觸發異常斷線 fallback
  const closeSocket = useCallback(() => {
    if (socketRef.current) {
      socketRef.current._intentional = true;
      socketRef.current.close();
      socketRef.current = null;
    }
  }, []);

  const connect = useCallback(async (jobId) => {
    closeSocket();
    // 帶 token 讓後端驗 job 擁有者；換不到 token 仍可連（job_id 即 capability）
    let token = null;
    try {
      token = await getAccessToken(API_RESOURCE);
    } catch {
      // 取不到 token 不致命，照樣以無 token 連線
      token = null;
    }
    const query = token ? `?token=${encodeURIComponent(token)}` : '';
    const url = `${toWebSocketBase(BACKEND_URL)}/ws/progress/${jobId}${query}`;
    const ws = new WebSocket(url);
    // 每條連線各自的旗標：主動關閉 / 已收到終端事件（決定 onclose 是否觸發 fallback）
    ws._intentional = false;
    ws._sawTerminal = false;
    socketRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        onEventRef.current?.(event);
        if (TERMINAL_EVENT_TYPES.has(event.event_type)) {
          ws._sawTerminal = true;
          ws.close();
        }
      } catch (err) {
        console.warn('[ProgressSocket] 事件解析失敗：', err);
      }
    };
    ws.onerror = (err) => console.warn('[ProgressSocket] WebSocket 連線錯誤：', err);
    ws.onclose = () => {
      if (socketRef.current === ws) socketRef.current = null;
      // 非主動關閉、且未收到終端事件（如後端重啟）→ 通知呼叫端回抓最終狀態，避免永久卡在處理中
      if (!ws._intentional && !ws._sawTerminal) onClosedRef.current?.();
    };
  }, [getAccessToken, closeSocket]);

  // 元件卸載時關閉殘留連線
  useEffect(() => closeSocket, [closeSocket]);

  return connect;
}
