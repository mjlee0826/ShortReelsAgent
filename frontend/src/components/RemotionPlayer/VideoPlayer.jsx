import React, { useMemo } from 'react';
import { Player } from '@remotion/player';
import MainTimeline from './MainTimeline';
import useBlueprintStore from '../../store/useBlueprintStore';
// 【新增】引入下載圖示
import { FaDownload } from 'react-icons/fa';

export default function VideoPlayer() {
  const { blueprint, assetsRootUrl } = useBlueprintStore();

  const { totalFrames, targetFps } = useMemo(() => {
    if (!blueprint || !blueprint.timeline || blueprint.timeline.length === 0) {
      return { totalFrames: 150, targetFps: 30 }; 
    }

    const fps = blueprint.global_settings?.fps || 30;
    const lastClip = blueprint.timeline[blueprint.timeline.length - 1];
    const frames = Math.round(lastClip.end_at * fps);
    
    return { 
      totalFrames: frames > 0 ? frames : 150, 
      targetFps: fps 
    };
  }, [blueprint]);

  // --- 【新增】處理下載邏輯 ---
  const handleDownload = () => {
    if (!blueprint) return;

    // 1. 將 JSON 物件轉換為可下載的字串格式
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(blueprint, null, 2));
    
    // 2. 建立一個隱藏的 <a> 標籤來觸發下載
    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href", dataStr);
    downloadAnchorNode.setAttribute("download", "reels_blueprint.json");
    document.body.appendChild(downloadAnchorNode);
    downloadAnchorNode.click();
    downloadAnchorNode.remove();

    // 3. 貼心提醒使用者 Remotion 的運作機制
    alert("✅ 劇本藍圖 (JSON) 已下載！\\n\\n【系統提示】\\n目前網頁為即時預覽模式。若需輸出實體 MP4 檔案，未來需將此 JSON 劇本送交至 Node.js 渲染伺服器進行壓製。");
  };
  // ------------------------------

  if (!blueprint) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-[#0a0a0a]">
        {/* ... (維持原本的 Placeholder 不變) ... */}
        <div className="w-[360px] h-[640px] border-2 border-dashed border-gray-800 flex items-center justify-center rounded-2xl bg-gray-900/30">
          <div className="text-center">
            <h2 className="text-xl font-bold text-gray-500">影片預覽區</h2>
            <p className="text-gray-600 mt-2 text-sm">請在右側控制台輸入指令並生成</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center bg-[#0a0a0a] relative w-full h-full p-8">
      
      {/* --- 【新增】懸浮的匯出按鈕 --- */}
      <button 
        onClick={handleDownload}
        className="absolute top-8 right-8 bg-blue-600 hover:bg-blue-500 text-white px-5 py-2.5 rounded-lg font-bold flex items-center gap-2 shadow-lg transition-transform hover:scale-105 z-20"
      >
        <FaDownload /> 匯出劇本藍圖
      </button>
      {/* ------------------------------ */}

      <div className="relative h-full max-h-[80vh] aspect-[9/16] rounded-2xl overflow-hidden shadow-[0_0_60px_rgba(0,0,0,0.4)] ring-1 ring-gray-800">
        <Player
          component={MainTimeline}
          inputProps={{ blueprint, assetsRootUrl }} 
          durationInFrames={totalFrames}
          fps={targetFps}
          compositionWidth={1080}
          compositionHeight={1920}
          resolutionScale={0.5}   
          style={{
            width: '100%',   
            height: '100%',
          }}
          controls 
          autoPlay 
          loop     
        />
      </div>
      
      <div className="mt-8 text-gray-500 text-sm font-mono bg-gray-900/60 px-5 py-2 rounded-full border border-gray-800">
        輸出規格: 1080x1920 | {targetFps} FPS | 總時長: {(totalFrames / targetFps).toFixed(1)}s
      </div>
    </div>
  );
}