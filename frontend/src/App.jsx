import React, { useState, useRef, useEffect, useCallback } from 'react';
import RightPanel from './components/RightPanel/RightPanel';
import VideoPlayer from './components/RemotionPlayer/VideoPlayer';

function App() {
  // 【新增】管理右側面板的寬度，預設 500px
  const [panelWidth, setPanelWidth] = useState(500);
  const isDragging = useRef(false);

  // --- 左右拖曳分隔線邏輯 ---
  const handleMouseDown = (e) => {
    isDragging.current = true;
    document.body.style.cursor = 'col-resize'; // 改變全域游標為左右調整
    e.preventDefault(); // 防止拖曳時選取到文字或圖片
  };

  const handleMouseMove = useCallback((e) => {
    if (!isDragging.current) return;
    
    // 計算新寬度：視窗總寬度 - 滑鼠目前的 X 座標
    const newWidth = window.innerWidth - e.clientX;
    
    // 限制寬度範圍：最窄 350px，最寬 800px (保護左右兩側都不會消失)
    if (newWidth >= 350 && newWidth <= 800) {
      setPanelWidth(newWidth);
    }
  }, []);

  const handleMouseUp = useCallback(() => {
    if (isDragging.current) {
      isDragging.current = false;
      document.body.style.cursor = 'default';
    }
  }, []);

  // 掛載全域事件監聽，確保滑鼠移動過快時不會脫離掌控
  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);
  // -------------------------

  return (
    <div className="flex h-screen w-full font-sans bg-black overflow-hidden">
      
      {/* 左側：影片預覽器 (flex-1 讓它自動填滿剩餘的空間) */}
      <div className="flex-1 min-w-[300px] relative">
        <VideoPlayer />
      </div>

      {/* 【新增】垂直拖拉分隔線 */}
      <div 
        onMouseDown={handleMouseDown}
        className="w-1.5 hover:w-2 bg-gray-900 border-x border-gray-800 cursor-col-resize hover:bg-blue-600 active:bg-blue-500 transition-colors flex flex-col items-center justify-center shrink-0 z-20 group"
        title="左右拖曳調整控制台寬度"
      >
        {/* 增加一點視覺小細節：垂直防滑紋 */}
        <div className="h-10 flex gap-[2px] opacity-30 group-hover:opacity-100">
          <div className="w-[1px] bg-white h-full"></div>
          <div className="w-[1px] bg-white h-full"></div>
        </div>
      </div>

      {/* 右側：控制面板 (寬度由 panelWidth 動態決定) */}
      <div 
        style={{ width: `${panelWidth}px` }} 
        className="shrink-0 h-full relative"
      >
        <RightPanel />
      </div>
      
    </div>
  );
}

export default App;