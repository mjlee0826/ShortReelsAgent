import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';
import { SUBTITLE_Z_INDEX } from './constants';
import {
  resolveTextOverlay,
  resolveVerticalCenterPct,
  buildSubtitleCssStyle,
  computeTextAnimationStyle,
} from '../../utils/textOverlay';

/**
 * 字幕疊加層：讀 clip 的結構化 text_overlay（相容 legacy overlay_text），
 * 水平置中、垂直依 vertical_position 定位並夾進 safe-area；樣式與進出場由純函式組裝。
 *
 * 在 <Sequence> 內渲染，故 useCurrentFrame() 為「clip 相對幀」，配合傳入的 durationInFrames
 * 做進出場。定位 transform 與動畫 transform 分兩層套用，避免互相覆蓋。
 * @param {object} props.clip 片段資料
 * @param {number} props.durationInFrames 片段顯示總幀數（決定出場時機）
 */
export default function TextOverlayLayer({ clip, durationInFrames }) {
  const frame = useCurrentFrame();
  const overlay = resolveTextOverlay(clip);
  if (!overlay) return null;

  const centerPct = resolveVerticalCenterPct(overlay.vertical_position);
  const boxStyle = buildSubtitleCssStyle(overlay);
  const anim = computeTextAnimationStyle({ animation: overlay.animation, frame, durationInFrames });

  return (
    <AbsoluteFill className="pointer-events-none" style={{ zIndex: SUBTITLE_Z_INDEX }}>
      {/* 定位層：把文字塊錨在 (50%, centerPct%)，水平置中 */}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: `${centerPct}%`,
          transform: 'translate(-50%, -50%)',
          display: 'flex',
          justifyContent: 'center',
          width: '100%',
        }}
      >
        {/* 動畫層：opacity + 進出場 transform，與定位 transform 解耦 */}
        <div style={{ ...boxStyle, opacity: anim.opacity, transform: anim.transform }}>
          {overlay.text}
        </div>
      </div>
    </AbsoluteFill>
  );
}
