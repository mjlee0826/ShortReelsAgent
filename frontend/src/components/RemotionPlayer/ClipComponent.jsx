import React from 'react';
import { Video, OffthreadVideo, Img, useVideoConfig, useCurrentFrame, interpolate, getRemotionEnvironment } from 'remotion';
import { TRANSITION_FRAMES } from './constants';
import { resolveClipMotion, computeMotionStyle } from '../../utils/motion';

export default function ClipComponent({
  clipData,
  assetsRootUrl,
  autoMotion = false,        // 全域自動運鏡開關（來自 blueprint.global_settings.auto_motion）
  clipIndex = 0,             // 片段索引：auto 模式下用於輪替不同向運鏡（避免幻燈片感）
  beatsInClipFrames = [],    // 落在此片段內的重拍幀（相對片段起點），驅動卡點 punch
  durationInFrames = 0,      // 片段顯示總幀數：決定 base 運鏡進度
}) {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();

  // 算圖（SSR）時用 OffthreadVideo：由 FFmpeg 依時間碼精準抽幀，手機 / 螢幕錄影常見的 VFR（變動幀率）
  // 來源不會再對不準幀而抖動，且不在無頭瀏覽器內跑 <video> 元素，更省記憶體（降低共用 GPU 機 OOM）。
  // 預覽（Player）維持 Video 以保拖曳 / 即時播放流暢；兩者 props 介面相同，可直接替換元件。
  const VideoComp = getRemotionEnvironment().isRendering ? OffthreadVideo : Video;

  // clip_id 為素材身分 relpath（如 standardized/clip_std.mp4）；assetsRootUrl + clip_id 直接命中
  // /static 磁碟分層，不可再 split('/').pop()（那會丟掉 raw/standardized 子目錄而指向錯誤路徑）
  const fileUrl = `${assetsRootUrl}${clipData.clip_id}`;
  const isImage = /\.(jpg|jpeg|png|heic|heif)$/i.test(clipData.clip_id);

  // 【轉場】Fade 淡入：前 TRANSITION_FRAMES 幀透明度 0→1（與 MainTimeline 的延伸重疊幀數同源，確保對齊）
  const opacity = clipData.transition_in === 'fade'
    ? interpolate(frame, [0, TRANSITION_FRAMES], [0, 1], { extrapolateRight: 'clamp' })
    : 1;

  // LLM 輸出的語意濾鏡名稱 → 合法 CSS filter 值
  const FILTER_MAP = {
    cinematic: 'contrast(1.1) saturate(0.85) brightness(0.9)',
    grayscale:  'grayscale(1)',
    blur:       'blur(4px)',
    none:       'none',
  };
  const cssFilter = FILTER_MAP[clipData.filter] ?? 'none';

  // 【自動運鏡】開啟時依 preset + 節拍算逐幀 transform（縮放支點＝主體定位，故推近往主體靠）；
  // 關閉時退回原本的靜態縮放，行為與改動前完全一致（純回歸）。
  const objectPosition = clipData.object_position || '50% 50%';
  const baseScale = clipData.scale || 1.0;
  let transform = `scale(${baseScale})`;
  let transformOrigin = '50% 50%';
  if (autoMotion) {
    const presetName = resolveClipMotion(clipData, clipIndex, isImage);
    const motionStyle = computeMotionStyle({
      presetName, frame, durationInFrames, beatsInClipFrames, baseScale, objectPosition,
    });
    transform = motionStyle.transform;
    transformOrigin = motionStyle.transformOrigin;
  }

  // 基礎樣式 (包含變焦 / 運鏡 與濾鏡)
  const dynamicStyle = {
    width: '100%', height: '100%',
    objectFit: 'cover',
    objectPosition,
    transform,
    transformOrigin,
    filter: cssFilter,
    opacity: opacity,
  };

  // 【進階功能】畫中畫 (PiP) 渲染邏輯
  const renderPiP = () => {
    if (!clipData.pip_video || !clipData.pip_video.clip_id) return null;
    
    // 同主畫面：PiP 的 clip_id 亦為 relpath，直接接在 root 後命中磁碟分層
    const pipUrl = `${assetsRootUrl}${clipData.pip_video.clip_id}`;
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

    return <VideoComp src={pipUrl} startFrom={pipStart} style={pipStyle} muted />;
  };

  const startFromFrame = Math.round((clipData.source_start || 0) * fps);
  const endAtFrame = clipData.source_end ? Math.round(clipData.source_end * fps) : undefined;

  return (
    <>
      {/* 主畫面 */}
      {isImage ? (
        <Img src={fileUrl} style={dynamicStyle} />
      ) : (
        <VideoComp
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