import { useCallback, useEffect, useRef, useState } from 'react';

/** 拖曳期間覆寫在 document.body 上的游標（讓整個畫面拖曳時都呈現左右調整游標）。 */
const RESIZE_CURSOR = 'col-resize';

/** localStorage 不可用（無痕模式 / 配額）時靜默忽略，不影響拖曳本身。 */
function readStoredWidth(storageKey, fallback) {
  if (!storageKey) return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  } catch {
    return fallback;
  }
}

/** 寫回偏好寬度，失敗同樣靜默忽略。 */
function writeStoredWidth(storageKey, width) {
  if (!storageKey) return;
  try {
    window.localStorage.setItem(storageKey, String(width));
  } catch {
    /* 忽略持久化失敗 */
  }
}

/**
 * useResizableWidth：以拖曳把手調整面板寬度的可複用 hook（單一職責）。
 *
 * 封裝「拖曳調寬 + 範圍夾限 + localStorage 持久化」三件事，與面板長相解耦，
 * 任何靠右錨定（右側固定、向左加寬）的面板都能共用。拖曳量以「起點差值」計算
 * （newWidth = 起始寬度 + (起始 X − 當前 X)），不依賴視窗寬度，行為穩定。
 *
 * @param {Object}   options
 * @param {number}   options.defaultWidth 預設寬度（px），無持久化值時採用
 * @param {number}   options.minWidth     寬度下限（px）
 * @param {number}   options.maxWidth     寬度上限（px），實際還會再被視窗寬度夾限
 * @param {string}   [options.storageKey] 持久化鍵；省略則不記憶偏好
 * @returns {{ width: number, isResizing: boolean, onResizeStart: (e) => void, resetWidth: () => void }}
 */
export default function useResizableWidth({ defaultWidth, minWidth, maxWidth, storageKey }) {
  // 初始寬度：優先採用持久化偏好，否則回退預設
  const [width, setWidth] = useState(() => readStoredWidth(storageKey, defaultWidth));
  const [isResizing, setIsResizing] = useState(false);
  // 拖曳期間的暫存：起始游標 X、起始寬度、最新寬度；用 ref 避免每次 mousemove 重綁監聽
  const dragState = useRef({ startX: 0, startWidth: 0, latestWidth: 0 });

  /** 將寬度夾限在 [minWidth, maxWidth] 且不超過當前視窗寬度。 */
  const clamp = useCallback(
    (value) => {
      const upper = Math.min(maxWidth, window.innerWidth);
      return Math.max(minWidth, Math.min(value, upper));
    },
    [minWidth, maxWidth],
  );

  /** 把手 onMouseDown：記下拖曳起點並進入調整中。 */
  const onResizeStart = useCallback(
    (e) => {
      e.preventDefault();
      dragState.current = { startX: e.clientX, startWidth: width, latestWidth: width };
      setIsResizing(true);
    },
    [width],
  );

  /** 雙擊把手：還原為預設寬度（順手的重置入口）。 */
  const resetWidth = useCallback(() => {
    const next = clamp(defaultWidth);
    setWidth(next);
    writeStoredWidth(storageKey, next);
  }, [clamp, defaultWidth, storageKey]);

  // 調整中才掛載全域 mousemove / mouseup：拖曳結束即解除，避免長駐監聽
  useEffect(() => {
    if (!isResizing) return undefined;

    const handleMouseMove = (e) => {
      // 把手在面板左緣、面板靠右錨定：游標往左移（delta 為正）即加寬
      const delta = dragState.current.startX - e.clientX;
      const next = clamp(dragState.current.startWidth + delta);
      dragState.current.latestWidth = next; // 暫存最新寬度，供放手時持久化
      setWidth(next);
    };
    const handleMouseUp = () => {
      setIsResizing(false);
      // 從 ref 取最終寬度持久化，避免在 state updater 內做副作用（StrictMode 會重複呼叫）
      writeStoredWidth(storageKey, dragState.current.latestWidth);
    };

    // 拖曳期間鎖住整頁游標與選取，避免選到文字 / 游標閃動
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = RESIZE_CURSOR;
    document.body.style.userSelect = 'none';

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
    };
  }, [isResizing, clamp, storageKey]);

  return { width, isResizing, onResizeStart, resetWidth };
}
