import React, { useMemo, useState } from 'react'; // 【新增 useState】
import { Player } from '@remotion/player';
import MainTimeline from './MainTimeline';
import useBlueprintStore from '../../store/useBlueprintStore';
// 【新增】引入圖示
import { FaDownload, FaSpinner } from 'react-icons/fa';

export default function VideoPlayer() {
  const { blueprint, assetsRootUrl } = useBlueprintStore();
  // 【新增】本地算圖狀態
  const [isRendering, setIsRendering] = useState(false);

  const { totalFrames, targetFps } = useMemo(() => {
    // ... (維持原本計算 fps 與 frames 的邏輯) ...
    if (!blueprint || !blueprint.timeline || blueprint.timeline.length === 0) {
      return { totalFrames: 150, targetFps: 30 }; 
    }
    const fps = blueprint.global_settings?.fps || 30;
    const lastClip = blueprint.timeline[blueprint.timeline.length - 1];
    const frames = Math.round(lastClip.end_at * fps);
    return { totalFrames: frames > 0 ? frames : 150, targetFps: fps };
  }, [blueprint]);

  // --- 【重構】真正的雲端算圖下載邏輯 ---
  const handleDownloadMp4 = async () => {
    if (!blueprint) return;
    setIsRendering(true);

    try {
      // 發送藍圖至 FastAPI 進行 SSR 算圖
      const response = await fetch('http://localhost:5174/api/render_mp4', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          blueprint: blueprint,
          assets_root_url: assetsRootUrl
        })
      });

      if (!response.ok) throw new Error('伺服器算圖失敗');

      // 接收二進位影片檔案 (Blob)
      const blob = await response.blob();
      
      // 建立隱藏網址並觸發瀏覽器下載實體檔案
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'ShortReelsAgent_Output.mp4';
      document.body.appendChild(a);
      a.click();
      
      // 清理記憶體
      a.remove();
      window.URL.revokeObjectURL(url);

    } catch (error) {
      alert(`❌ 匯出失敗：${error.message}`);
    } finally {
      setIsRendering(false);
    }
  };
  // ----------------------------------------

  if (!blueprint) {
    // ... (維持 Placeholder 不變) ...
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center bg-[#0a0a0a] relative w-full h-full p-8">
      
      {/* --- 【修改】下載按鈕與 Loading 狀態綁定 --- */}
      <button 
        onClick={handleDownloadMp4}
        disabled={isRendering}
        className={`absolute top-8 right-8 text-white px-5 py-2.5 rounded-lg font-bold flex items-center gap-2 shadow-lg transition-transform z-20 ${
          isRendering ? 'bg-gray-600 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-500 hover:scale-105'
        }`}
      >
        {isRendering ? (
          <><FaSpinner className="animate-spin" /> 雲端算圖中 (約 1~2 分鐘)...</>
        ) : (
          <><FaDownload /> 下載高畫質 MP4</>
        )}
      </button>

      {/* --- 【新增】算圖時的全畫面提示遮罩 --- */}
      {isRendering && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/60 backdrop-blur-md rounded-2xl pointer-events-none">
          <div className="bg-gray-900/90 p-6 rounded-2xl border border-gray-700 shadow-2xl flex flex-col items-center">
            <FaSpinner className="animate-spin text-blue-500 text-5xl mb-4" />
            <h3 className="text-white font-bold text-lg mb-1">正在壓製 MP4 檔案</h3>
            <p className="text-sm text-gray-400">系統正在背景逐格截圖與混音，請勿關閉視窗</p>
          </div>
        </div>
      )}

      <div className="relative h-full max-h-[80vh] aspect-[9/16] rounded-2xl overflow-hidden shadow-[0_0_60px_rgba(0,0,0,0.4)] ring-1 ring-gray-800">
        <Player
          component={MainTimeline}
          inputProps={{ blueprint, assetsRootUrl }} 
          durationInFrames={totalFrames}
          fps={targetFps}
          compositionWidth={1080}
          compositionHeight={1920}
          resolutionScale={0.5}   
          style={{ width: '100%', height: '100%' }}
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