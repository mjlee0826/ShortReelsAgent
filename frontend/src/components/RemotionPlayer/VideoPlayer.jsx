import React, { useMemo, useState } from 'react';
import { Player } from '@remotion/player';
import MainTimeline from './MainTimeline';
import useBlueprintStore from '../../store/useBlueprintStore';
// 【新增】引入科技感圖示 (包含 FaRocket 增加動態感)
import { FaDownload, FaSpinner, FaRocket } from 'react-icons/fa';

export default function VideoPlayer() {
  const { blueprint, assetsRootUrl } = useBlueprintStore();
  const [isRendering, setIsRendering] = useState(false);

  // 1. 判斷藍圖是否為空 (嚴格條件)
  const isBlueprintEmpty = !blueprint || !blueprint.timeline || blueprint.timeline.length === 0;

  // 2. 【修正】單純計算總幀數與 FPS，不可在這裡回傳 HTML/JSX！
  const { totalFrames, targetFps } = useMemo(() => {
    if (isBlueprintEmpty) {
      return { totalFrames: 150, targetFps: 30 }; // 給予安全預設值，避免底層崩潰
    }
    const fps = blueprint.global_settings?.fps || 30;
    const lastClip = blueprint.timeline[blueprint.timeline.length - 1];
    const frames = Math.round(lastClip.end_at * fps);
    return { totalFrames: frames > 0 ? frames : 150, targetFps: fps };
  }, [blueprint, isBlueprintEmpty]);

  // 3. 雲端算圖下載邏輯
  const handleDownloadMp4 = async () => {
    if (isBlueprintEmpty) return;
    setIsRendering(true);

    try {
      const response = await fetch('http://localhost:5174/api/render_mp4', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          blueprint: blueprint,
          assets_root_url: assetsRootUrl
        })
      });

      if (!response.ok) throw new Error('伺服器算圖失敗');

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'ShortReelsAgent_Output.mp4';
      document.body.appendChild(a);
      a.click();
      
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      alert(`❌ 匯出失敗：${error.message}`);
    } finally {
      setIsRendering(false);
    }
  };

  // 4. 【新增】嚴格判斷按鈕是否應該被禁用
  const isDownloadDisabled = isBlueprintEmpty || isRendering;

  return (
    <div className="flex-1 flex flex-col items-center justify-center bg-[#0a0a0a] relative w-full h-full p-8">
      
      {/* --- 【修改】科技感下載按鈕 --- */}
      <button 
        onClick={handleDownloadMp4}
        disabled={isDownloadDisabled}
        className={`
          absolute top-8 right-8 px-6 py-3 rounded-xl font-bold flex items-center gap-3 transition-all duration-500 z-20
          ${isDownloadDisabled 
            ? 'bg-gray-800/50 text-gray-500 border border-gray-700 cursor-not-allowed opacity-50' 
            : 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white border border-blue-400/30 shadow-[0_0_15px_rgba(59,130,246,0.4)] hover:shadow-[0_0_25px_rgba(59,130,246,0.6)] hover:scale-105 active:scale-95 group'
          }
        `}
      >
        {isRendering ? (
          <>
            <FaSpinner className="animate-spin text-blue-300" />
            <span className="tracking-tight">核心引擎算圖中...</span>
          </>
        ) : (
          <>
            <FaRocket className={`transition-transform duration-500 ${isDownloadDisabled ? '' : 'group-hover:-translate-y-1 group-hover:translate-x-1'}`} />
            <span className="tracking-widest">匯出高畫質 MP4</span>
            {!isDownloadDisabled && (
              <div className="absolute inset-0 rounded-xl bg-gradient-to-r from-white/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            )}
          </>
        )}
      </button>

      {/* --- 【修改】算圖時的科技感全畫面遮罩 --- */}
      {isRendering && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/70 backdrop-blur-xl rounded-2xl pointer-events-none transition-all duration-500">
          <div className="p-8 rounded-3xl border border-blue-500/20 bg-gray-900/80 shadow-[0_0_50px_rgba(0,0,0,0.5)] flex flex-col items-center">
            <div className="relative mb-6">
              <FaSpinner className="animate-spin text-blue-500 text-6xl" />
              <div className="absolute inset-0 blur-xl bg-blue-500/30 animate-pulse" />
            </div>
            <h3 className="text-white font-bold text-xl mb-2 tracking-widest">RENDERING ENGINE</h3>
            <p className="text-sm text-blue-400/70 font-mono">FRAME BY FRAME SYNTHESIS IN PROGRESS</p>
          </div>
        </div>
      )}

      {/* --- 【修正】嚴格判斷：如果沒有藍圖，顯示漂亮的 Placeholder；否則顯示 Remotion 播放器 --- */}
      {isBlueprintEmpty ? (
        <div className="w-[360px] h-[640px] border-2 border-dashed border-gray-800 flex items-center justify-center rounded-3xl bg-gray-900/20 backdrop-blur-sm shadow-[0_0_40px_rgba(0,0,0,0.2)]">
          <div className="text-center p-6">
            <div className="w-16 h-16 bg-gray-800 rounded-full flex items-center justify-center mx-auto mb-4 border border-gray-700">
              <span className="text-2xl">🎬</span>
            </div>
            <h2 className="text-xl font-bold text-gray-500 tracking-tight">等待導演劇本</h2>
            <p className="text-gray-600 mt-2 text-sm leading-relaxed">
              請在右側控制台輸入指令<br/>解鎖 AI 創作空間
            </p>
          </div>
        </div>
      ) : (
        <div className="relative h-full max-h-[80vh] aspect-[9/16] rounded-3xl overflow-hidden shadow-[0_0_80px_rgba(0,0,0,0.6)] ring-1 ring-white/10">
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
      )}
      
      {/* --- 底部專業規格資訊 (僅在有影片時顯示) --- */}
      {!isBlueprintEmpty && (
        <div className="mt-8 flex gap-4 text-[10px] uppercase tracking-[0.2em] font-mono">
          <span className="text-blue-500/80">Output: 1080x1920</span>
          <span className="text-gray-600">|</span>
          <span className="text-blue-500/80">Encoding: H.264</span>
          <span className="text-gray-600">|</span>
          <span className="text-blue-500/80">Status: {isRendering ? 'Processing' : 'Ready'}</span>
        </div>
      )}
    </div>
  );
}