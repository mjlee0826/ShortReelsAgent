import React from 'react';
import { Sequence, AbsoluteFill, useVideoConfig, Audio } from 'remotion';
import ClipComponent from './ClipComponent';

export default function MainTimeline({ blueprint, assetsRootUrl }) {
  const { fps } = useVideoConfig();

  if (!blueprint || !blueprint.timeline) return null;

  const getDynamicBgmVolume = (frame) => {
    const currentClip = blueprint.timeline.find((c) => {
      const startFrame = Math.round(c.start_at * fps);
      const endFrame = Math.round(c.end_at * fps);
      return frame >= startFrame && frame <= endFrame;
    });
    const baseVol = blueprint.bgm_track?.volume ?? 1.0;
    const duckingWeight = currentClip?.bgm_volume ?? 1.0;
    return baseVol * duckingWeight;
  };

  // 【新增】智慧判斷音樂來源網址
  const getBgmSrc = () => {
    const trackId = blueprint.bgm_track?.track_id;
    if (!trackId) return null;
    
    // 若為完整網址 (例如全域快取池來的)，直接回傳
    if (trackId.startsWith('http')) {
      return trackId;
    }
    // 否則為舊版相容 (同資料夾的檔名)
    return `${assetsRootUrl}${trackId.split('/').pop()}`;
  };

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      
      {/* --- 全局背景音樂 --- */}
      {blueprint.bgm_track && blueprint.bgm_track.track_id && (
        <Audio 
          src={getBgmSrc()}
          startFrom={Math.round((blueprint.bgm_track.source_start || 0) * fps)}
          volume={getDynamicBgmVolume}
        />
      )}

      {/* --- 影片序列排版 --- */}
      {blueprint.timeline.map((clip, index) => {
        const fromFrame = Math.round(clip.start_at * fps);
        const durationInFrames = Math.round((clip.end_at - clip.start_at) * fps);

        const nextClip = index < blueprint.timeline.length - 1 ? blueprint.timeline[index + 1] : null;
        // 只在相鄰片段（間距 < 0.1s）且下一段有轉場時才延伸，避免非相鄰片段出現殘影
        const isAdjacent = nextClip && Math.abs((nextClip.start_at ?? 0) - (clip.end_at ?? 0)) < 0.1;
        const hasNextTransition = isAdjacent && nextClip.transition_in && nextClip.transition_in !== 'none';
        const renderDuration = hasNextTransition ? durationInFrames + 15 : durationInFrames;

        if (renderDuration <= 0) return null;

        return (
          <Sequence key={`${clip.clip_id}-${index}`} from={fromFrame} durationInFrames={renderDuration}>
            <ClipComponent clipData={clip} assetsRootUrl={assetsRootUrl} />
            
            {clip.overlay_text && (
              <AbsoluteFill className="flex items-center justify-center pointer-events-none z-50">
                <div className="text-white text-5xl font-bold text-center px-8 drop-shadow-2xl bg-black/40 rounded-xl p-4">
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