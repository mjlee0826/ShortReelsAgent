import React, { useMemo } from 'react';
import { Player } from '@remotion/player';
import MainTimeline from './MainTimeline';
import useBlueprintStore from '../../store/useBlueprintStore';

export default function VideoPlayer() {
  // 從 Zustand 取得資料
  const { blueprint, assetsRootUrl } = useBlueprintStore();

  // 計算影片的總影格數與全域 FPS
  const { totalFrames, targetFps } = useMemo(() => {
    if (!blueprint || !blueprint.timeline || blueprint.timeline.length === 0) {
      return { totalFrames: 150, targetFps: 30 }; // 預設值 (無資料時)
    }

    const fps = blueprint.global_settings?.fps || 30;
    
    // 找出劇本中最後一個片段的結束時間，並轉換為影格
    const lastClip = blueprint.timeline[blueprint.timeline.length - 1];
    const frames = Math.round(lastClip.end_at * fps);
    
    return { 
      totalFrames: frames > 0 ? frames : 150, 
      targetFps: fps 
    };
  }, [blueprint]);

  // 如果還沒有生成劇本，顯示等待畫面
  if (!blueprint) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-black">
        <div className="w-[360px] h-[640px] border-2 border-dashed border-gray-700 flex items-center justify-center rounded-lg">
          <div className="text-center">
            <h2 className="text-xl font-bold text-gray-500">影片預覽區</h2>
            <p className="text-gray-600 mt-2">請在右側控制台輸入指令並生成</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center bg-black relative">
      {/* Remotion 播放器核心 */}
      <Player
        component={MainTimeline}
        inputProps={{ blueprint, assetsRootUrl }} // 將資料傳入 Composition
        durationInFrames={totalFrames}
        fps={targetFps}
        compositionWidth={1080}
        compositionHeight={1920}
        style={{
          width: '360px',  // 在網頁上縮小預覽 (維持 9:16)
          height: '640px',
          borderRadius: '12px',
          boxShadow: '0 20px 50px -12px rgba(0,0,0,0.5)',
        }}
        controls // 顯示播放控制條
        autoPlay // 生成後自動播放
        loop     // 循環播放
      />
      
      {/* 輔助資訊標籤 */}
      <div className="absolute bottom-10 text-gray-500 text-sm">
        輸出規格: 1080x1920 | {targetFps} FPS | 總時長: {(totalFrames / targetFps).toFixed(1)}s
      </div>
    </div>
  );
}