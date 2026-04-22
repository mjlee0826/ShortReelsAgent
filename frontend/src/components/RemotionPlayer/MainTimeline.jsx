import React from 'react';
import { Sequence, AbsoluteFill, useVideoConfig, Audio } from 'remotion';
import ClipComponent from './ClipComponent';

export default function MainTimeline({ blueprint, assetsRootUrl }) {
  const { fps } = useVideoConfig();

  if (!blueprint || !blueprint.timeline) return null;

  // 動態音量計算：當播放到有人講話的片段時，自動把背景音樂降小聲 (Audio Ducking)
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

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      
      {/* --- 全局背景音樂 --- */}
      {blueprint.bgm_track && blueprint.bgm_track.track_id && (
        <Audio 
          src={`${assetsRootUrl}${blueprint.bgm_track.track_id.split('/').pop()}`}
          startFrom={Math.round((blueprint.bgm_track.source_start || 0) * fps)}
          volume={getDynamicBgmVolume}
        />
      )}

      {/* --- 影片序列排版 --- */}
      {blueprint.timeline.map((clip, index) => {
        const fromFrame = Math.round(clip.start_at * fps);
        const durationInFrames = Math.round((clip.end_at - clip.start_at) * fps);

        // 【轉場修正】如果有設定轉場，當前片段必須「延長 15 幀」，與下一個片段重疊才能做出 Fade 效果
        const hasNextTransition = index < blueprint.timeline.length - 1 && blueprint.timeline[index + 1].transition_in !== 'none';
        const renderDuration = hasNextTransition ? durationInFrames + 15 : durationInFrames;

        if (renderDuration <= 0) return null;

        return (
          <Sequence key={`${clip.clip_id}-${index}`} from={fromFrame} durationInFrames={renderDuration}>
            <ClipComponent clipData={clip} assetsRootUrl={assetsRootUrl} />
            
            {/* 字幕疊加 */}
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