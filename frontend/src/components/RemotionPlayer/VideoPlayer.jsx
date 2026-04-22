import React, { useMemo } from 'react';
import { Player } from '@remotion/player';
import MainTimeline from './MainTimeline';
import useBlueprintStore from '../../store/useBlueprintStore';

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

  if (!blueprint) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-[#0a0a0a]">
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
    // 【修改這裡】外層容器改為深灰色背景，並完美置中內容
    <div className="flex-1 flex flex-col items-center justify-center bg-[#0a0a0a] relative w-full h-full p-8">
      
      {/* 【修改這裡】動態計算高度的 9:16 容器 */}
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
            width: '100%',   // 填滿外層的 9:16 容器
            height: '100%',
          }}
          controls 
          autoPlay 
          loop     
        />
      </div>
      
      {/* 輔助資訊標籤移到下方，改為像膠囊一樣的設計 */}
      <div className="mt-8 text-gray-500 text-sm font-mono bg-gray-900/60 px-5 py-2 rounded-full border border-gray-800">
        輸出規格: 1080x1920 | {targetFps} FPS | 總時長: {(totalFrames / targetFps).toFixed(1)}s
      </div>
    </div>
  );
}