import React, { useState, useRef, useEffect, useCallback } from 'react';
import SidebarForm from './SidebarForm';
import ChatBox from './ChatBox';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaSpinner } from 'react-icons/fa';

// 上下分割的初始比例與可拖拉範圍（%）
const INITIAL_TOP_PCT = 55;
const MIN_TOP_PCT = 20;
const MAX_TOP_PCT = 80;

/**
 * RightPanel：編輯器右側控制台。上半為生成表單、下半為 AI 對話框，中間可上下拖拉調整比例。
 */
export default function RightPanel() {
  const { errorMsg, isProcessing, musicStrategy } = useBlueprintStore();
  const [topHeight, setTopHeight] = useState(INITIAL_TOP_PCT);
  const isDragging = useRef(false);
  const panelRef = useRef(null);

  const handleMouseDown = (e) => {
    isDragging.current = true;
    document.body.style.cursor = 'row-resize';
    e.preventDefault();
  };

  const handleMouseMove = useCallback((e) => {
    if (!isDragging.current || !panelRef.current) return;
    const containerRect = panelRef.current.getBoundingClientRect();
    const newHeightPct = ((e.clientY - containerRect.top) / containerRect.height) * 100;
    if (newHeightPct >= MIN_TOP_PCT && newHeightPct <= MAX_TOP_PCT) setTopHeight(newHeightPct);
  }, []);

  const handleMouseUp = useCallback(() => {
    if (isDragging.current) {
      isDragging.current = false;
      document.body.style.cursor = 'default';
    }
  }, []);

  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  return (
    <div className="w-full h-full flex flex-col bg-surface z-10 relative border-l border-border">
      {/* 載入中遮罩 */}
      {isProcessing && (
        <div className="absolute inset-0 bg-canvas/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center">
          <FaSpinner className="animate-spin text-accent text-6xl mb-6" />
          <h3 className="text-ink font-bold text-xl tracking-widest">AI 導演思考中...</h3>
          <p className="text-ink-muted text-sm mt-3 animate-pulse">正在精確計算時間軸與混音策略</p>
        </div>
      )}

      {/* 頂部標題 */}
      <div className="p-6 border-b border-border bg-surface-2/40 shrink-0">
        <h2 className="text-xl font-bold text-ink tracking-wide">AI Director</h2>
        <p className="text-xs text-ink-faint mt-1">Short Reels Agent 控制台</p>
      </div>

      {/* 系統錯誤提示 */}
      {errorMsg && (
        <div className="bg-danger/15 text-danger px-4 py-3 text-sm font-medium shrink-0 border-b border-danger/30">⚠️ {errorMsg}</div>
      )}

      {/* 版權風險提示（search_copyright 策略時顯示）*/}
      {musicStrategy === 'search_copyright' && (
        <div className="bg-warning/10 border-l-4 border-warning text-warning px-4 py-3 text-sm shrink-0">
          ⚠️ 此配樂策略可能含有版權音樂，發布至 IG / TikTok 可能遭靜音或下架。建議直接在發布平台套用官方音樂庫。
        </div>
      )}

      {/* 可拖拉的彈性視窗區域 */}
      <div className="flex-1 flex flex-col overflow-hidden" ref={panelRef}>
        {/* 上方：設定表單 */}
        <div style={{ height: `${topHeight}%` }} className="overflow-y-auto">
          <SidebarForm />
        </div>

        {/* 中間：上下拖拉分隔線 */}
        <div
          onMouseDown={handleMouseDown}
          className="h-2 w-full bg-surface-2 border-y border-border cursor-row-resize hover:bg-accent active:bg-accent-hover transition-colors shrink-0 flex items-center justify-center group"
          title="上下拖曳調整視窗大小"
        >
          <div className="w-10 flex flex-col gap-[2px] opacity-30 group-hover:opacity-100">
            <div className="h-[1px] bg-white" />
            <div className="h-[1px] bg-white" />
          </div>
        </div>

        {/* 下方：對話框 */}
        <div style={{ height: `${100 - topHeight}%` }} className="flex flex-col">
          <ChatBox />
        </div>
      </div>
    </div>
  );
}
