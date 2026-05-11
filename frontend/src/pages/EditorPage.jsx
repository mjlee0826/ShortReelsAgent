import React, { useState, useRef, useEffect, useCallback } from 'react';
import RightPanel from '../components/RightPanel/RightPanel';
import VideoPlayer from '../components/RemotionPlayer/VideoPlayer';
import AppHeader from '../components/AppHeader/AppHeader';

export default function EditorPage() {
  const [panelWidth, setPanelWidth] = useState(500);
  const isDragging = useRef(false);

  const handleMouseDown = (e) => {
    isDragging.current = true;
    document.body.style.cursor = 'col-resize';
    e.preventDefault();
  };

  const handleMouseMove = useCallback((e) => {
    if (!isDragging.current) return;
    const newWidth = window.innerWidth - e.clientX;
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

  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  return (
    <div className="flex flex-col h-screen w-full font-sans bg-black overflow-hidden">
      <AppHeader />

      {/* 主要編輯區：左右兩欄 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左側：影片預覽器 */}
        <div className="flex-1 min-w-[300px] relative">
          <VideoPlayer />
        </div>

        {/* 垂直拖拉分隔線 */}
        <div
          onMouseDown={handleMouseDown}
          className="w-1.5 hover:w-2 bg-gray-900 border-x border-gray-800 cursor-col-resize hover:bg-blue-600 active:bg-blue-500 transition-colors flex flex-col items-center justify-center shrink-0 z-20 group"
          title="左右拖曳調整控制台寬度"
        >
          <div className="h-10 flex gap-[2px] opacity-30 group-hover:opacity-100">
            <div className="w-[1px] bg-white h-full"></div>
            <div className="w-[1px] bg-white h-full"></div>
          </div>
        </div>

        {/* 右側：控制面板 */}
        <div style={{ width: `${panelWidth}px` }} className="shrink-0 h-full relative">
          <RightPanel />
        </div>
      </div>
    </div>
  );
}
