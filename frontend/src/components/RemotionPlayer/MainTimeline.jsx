import React from 'react';
import { Sequence, AbsoluteFill, useVideoConfig } from 'remotion';
import ClipComponent from './ClipComponent';

/**
 * MainTimeline: Remotion 的核心畫布
 * 接收 inputProps (包含 blueprint 劇本與素材路徑)
 */
export default function MainTimeline({ blueprint, assetsRootUrl }) {
  const { fps } = useVideoConfig();

  if (!blueprint || !blueprint.timeline) {
    return null;
  }

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      {blueprint.timeline.map((clip, index) => {
        // 核心數學轉換：秒數 -> 影格 (Frames)
        const fromFrame = Math.round(clip.start_at * fps);
        const durationInFrames = Math.round((clip.end_at - clip.start_at) * fps);

        // 防呆：避免因浮點數誤差導致的 0 幀片段
        if (durationInFrames <= 0) return null;

        return (
          <Sequence 
            key={`${clip.clip_id}-${index}`} 
            from={fromFrame} 
            durationInFrames={durationInFrames}
          >
            {/* 將每一個剪輯任務交給 ClipComponent 處理 */}
            <ClipComponent clipData={clip} assetsRootUrl={assetsRootUrl} />
            
            {/* 如果大腦有設定花字/字幕 (overlay_text)，直接疊加在畫面上層 */}
            {clip.overlay_text && (
              <AbsoluteFill className="flex items-center justify-center pointer-events-none">
                <div className="text-white text-5xl font-bold text-center px-8 drop-shadow-2xl bg-black/30 rounded-xl p-4">
                  {clip.overlay_text}
                </div>
              </AbsoluteFill>
            )}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
}