import React from 'react';
import { Sequence, AbsoluteFill, useVideoConfig, Audio } from 'remotion';
import ClipComponent from './ClipComponent';
import { TRANSITION_FRAMES, ADJACENCY_THRESHOLD_SECONDS } from './constants';

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
        // 以「邊界幀差」算長度：fromFrame 取自 start_at、toFrame 取自 end_at，各自 round 後相減。
        // 因時間軸已 repack（end_at[i] === start_at[i+1]），相鄰片段必共用同一邊界幀，
        // 故首尾嚴格相接、零黑縫零重疊；若改用 round(end-start) 則兩端獨立進位會差 ±1 幀 → 黑幀閃爍（亂跳主因之一）
        const fromFrame = Math.round(clip.start_at * fps);
        const toFrame = Math.round(clip.end_at * fps);
        const durationInFrames = toFrame - fromFrame;

        const nextClip = index < blueprint.timeline.length - 1 ? blueprint.timeline[index + 1] : null;
        // 只在相鄰片段（間距小於門檻）且下一段有轉場時才延伸，讓交叉淡入有重疊；非相鄰不延伸以免殘影
        const isAdjacent = nextClip && Math.abs((nextClip.start_at ?? 0) - (clip.end_at ?? 0)) < ADJACENCY_THRESHOLD_SECONDS;
        const hasNextTransition = isAdjacent && nextClip.transition_in && nextClip.transition_in !== 'none';
        const renderDuration = hasNextTransition ? durationInFrames + TRANSITION_FRAMES : durationInFrames;

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