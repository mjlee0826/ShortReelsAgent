import React, { useState, useRef, useEffect, useCallback } from 'react';
import SidebarForm from './SidebarForm';
import ChatBox from './ChatBox';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaSpinner } from 'react-icons/fa';

export default function RightPanel() {
  const { errorMsg, isProcessing, musicStrategy } = useBlueprintStore();
  
  const [topHeight, setTopHeight] = useState(55);
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
    const newHeightPx = e.clientY - containerRect.top;
    const newHeightPct = (newHeightPx / containerRect.height) * 100;

    if (newHeightPct >= 20 && newHeightPct <= 80) {
      setTopHeight(newHeightPct);
    }
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
    // 【修改重點】移除了固定的 w-[500px] 等寬度設定，改為 w-full，讓 App.jsx 負責控制寬度
    <div className="w-full h-full flex flex-col bg-gray-900 shadow-2xl z-10 relative">
      
      {/* 載入中遮罩 */}
      {isProcessing && (
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm z-50 flex flex-col items-center justify-center transition-all duration-300">
          <FaSpinner className="animate-spin text-blue-500 text-6xl mb-6 shadow-blue-500/50 drop-shadow-lg" />
          <h3 className="text-white font-bold text-xl tracking-widest">AI 導演思考中...</h3>
          <p className="text-gray-400 text-sm mt-3 animate-pulse">正在精確計算時間軸與混音策略</p>
        </div>
      )}

      {/* 頂部標題 */}
      <div className="p-6 border-b border-gray-800 bg-black shrink-0">
        <h2 className="text-xl font-bold text-white tracking-wide">AI Director</h2>
        <p className="text-xs text-gray-500 mt-1">Short Reels Agent 控制台</p>
      </div>

      {/* 系統錯誤提示 */}
      {errorMsg && (
        <div className="bg-red-900 text-red-200 p-3 text-sm font-semibold shrink-0 shadow-inner">
          ⚠️ {errorMsg}
        </div>
      )}

      {/* 版權風險提示：search_copyright 策略時顯示，前端直接判斷無需等 API */}
      {musicStrategy === 'search_copyright' && (
        <div className="bg-yellow-950/60 border-l-4 border-yellow-500 text-yellow-200 p-3 text-sm shrink-0">
          ⚠️ 此配樂策略可能含有版權音樂，發布至 IG / TikTok 可能遭靜音或下架。
          建議直接在發布平台套用官方音樂庫。
        </div>
      )}

      {/* 可拖拉的彈性視窗區域 */}
      <div className="flex-1 flex flex-col overflow-hidden" ref={panelRef}>
        
        {/* 上方：設定表單 */}
        <div style={{ height: `${topHeight}%` }} className="overflow-y-auto bg-gray-900">
          <SidebarForm />
        </div>

        {/* 中間：拖拉分隔線 (上下) */}
        <div 
          onMouseDown={handleMouseDown}
          className="h-2 w-full bg-gray-800 border-y border-gray-700 cursor-row-resize hover:bg-blue-600 active:bg-blue-500 transition-colors shrink-0 flex items-center justify-center group"
          title="上下拖曳調整視窗大小"
        >
          <div className="w-10 flex flex-col gap-[2px] opacity-30 group-hover:opacity-100">
            <div className="h-[1px] bg-white"></div>
            <div className="h-[1px] bg-white"></div>
          </div>
        </div>

        {/* 下方：對話框 */}
        <div style={{ height: `${100 - topHeight}%` }} className="flex flex-col bg-gray-900">
          <ChatBox />
        </div>
        
      </div>
    </div>
  );
}