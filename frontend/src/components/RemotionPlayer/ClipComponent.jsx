import React from 'react';
import { Video, Img, useVideoConfig, useCurrentFrame, interpolate } from 'remotion';

export default function ClipComponent({ clipData, assetsRootUrl }) {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();

  const fileName = clipData.clip_id.split('/').pop(); 
  const fileUrl = `${assetsRootUrl}${fileName}`;
  const isImage = /\.(jpg|jpeg|png|heic|heif)$/i.test(fileName);

  // 【轉場修正】實作 Fade 淡入動畫 (0~15 幀時透明度從 0 漸變為 1)
  const opacity = clipData.transition_in === 'fade'
    ? interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' })
    : 1;

  // LLM 輸出的語意濾鏡名稱 → 合法 CSS filter 值
  const FILTER_MAP = {
    cinematic: 'contrast(1.1) saturate(0.85) brightness(0.9)',
    grayscale:  'grayscale(1)',
    blur:       'blur(4px)',
    none:       'none',
  };
  const cssFilter = FILTER_MAP[clipData.filter] ?? 'none';

  // 基礎樣式 (包含變焦 scale 與濾鏡)
  const dynamicStyle = {
    width: '100%', height: '100%',
    objectFit: 'cover',
    objectPosition: clipData.object_position || '50% 50%',
    transform: `scale(${clipData.scale || 1.0})`,
    filter: cssFilter,
    opacity: opacity,
  };

  // 【進階功能】畫中畫 (PiP) 渲染邏輯
  const renderPiP = () => {
    if (!clipData.pip_video || !clipData.pip_video.clip_id) return null;
    
    const pipName = clipData.pip_video.clip_id.split('/').pop();
    const pipUrl = `${assetsRootUrl}${pipName}`;
    const pipStart = Math.round((clipData.pip_video.source_start || 0) * fps);
    
    // PiP 樣式與位置計算
    const pos = clipData.pip_video.position || 'top_right';
    const pipStyle = {
      position: 'absolute',
      width: '35%', height: 'auto',
      borderRadius: '16px', border: '3px solid white',
      boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
      zIndex: 20,
      ...(pos === 'top_right' ? { top: '3%', right: '3%' } : {}),
      ...(pos === 'bottom_left' ? { bottom: '3%', left: '3%' } : {}),
    };

    return <Video src={pipUrl} startFrom={pipStart} style={pipStyle} muted />;
  };

  const startFromFrame = Math.round((clipData.source_start || 0) * fps);
  const endAtFrame = clipData.source_end ? Math.round(clipData.source_end * fps) : undefined;

  return (
    <>
      {/* 主畫面 */}
      {isImage ? (
        <Img src={fileUrl} style={dynamicStyle} />
      ) : (
        <Video
          src={fileUrl}
          startFrom={startFromFrame}
          endAt={endAtFrame}
          playbackRate={clipData.playback_rate || 1.0}
          volume={clipData.clip_volume ?? 1.0}
          style={dynamicStyle}
        />
      )}
      
      {/* 畫中畫子畫面 (若有) */}
      {renderPiP()}
    </>
  );
}