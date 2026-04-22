import React from 'react';
import RightPanel from './components/RightPanel/RightPanel';
import VideoPlayer from './components/RemotionPlayer/VideoPlayer';

function App() {
  return (
    <div className="flex h-screen w-full font-sans bg-black overflow-hidden">
      {/* 左側：真實的 Remotion 影片預覽器 */}
      <VideoPlayer />
      
      {/* 右側：控制面板 (表單與對話) */}
      <RightPanel />
    </div>
  );
}

export default App;