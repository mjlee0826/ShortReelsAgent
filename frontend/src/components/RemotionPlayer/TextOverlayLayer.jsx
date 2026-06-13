import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';
import { SUBTITLE_Z_INDEX } from './constants';
import {
  resolveVerticalCenterPct,
  resolveHorizontalCenterPct,
  buildSubtitleCssStyle,
  computeTextAnimationStyle,
} from '../../utils/textOverlay';

/**
 * 字幕疊加層：渲染單一條已填好預設的字幕（overlay）。
 *
 * 由 MainTimeline 把每條 text_overlay 包進自己的 <Sequence> 後渲染本元件，故 useCurrentFrame()
 * 為「該字幕相對幀」（在各自 Sequence 內歸零）→ 進出場不在 clip 切點閃爍。
 * 錨點由 vertical/horizontal_position 決定（皆已 clamp 進 safe-area），定位 transform 與進出場
 * transform 合成於同一字串（非兩個 style 屬性互蓋）。文字塊為 AbsoluteFill 的直接子節點，
 * 故 buildSubtitleCssStyle 的 maxWidth（% of 合成寬）正確相對 1080 寬解析。
 * @param {object} props.overlay 已 fillOverlayDefaults 的字幕物件（含 text / 位置 / 樣式）
 * @param {number} props.durationInFrames 此字幕顯示總幀數（決定出場時機）
 */
export default function TextOverlayLayer({ overlay, durationInFrames }) {
  const frame = useCurrentFrame();
  if (!overlay) return null;

  const topPct = resolveVerticalCenterPct(overlay.vertical_position);
  const leftPct = resolveHorizontalCenterPct(overlay.horizontal_position);
  const boxStyle = buildSubtitleCssStyle(overlay);
  const anim = computeTextAnimationStyle({ animation: overlay.animation, frame, durationInFrames });
  // 定位 transform（把錨點移到文字塊中心）後接進出場 transform；fade/none 的 transform 為 'none' 則略去。
  const animTransform = anim.transform && anim.transform !== 'none' ? ` ${anim.transform}` : '';

  return (
    <AbsoluteFill className="pointer-events-none" style={{ zIndex: SUBTITLE_Z_INDEX }}>
      <div
        style={{
          ...boxStyle,
          position: 'absolute',
          left: `${leftPct}%`,
          top: `${topPct}%`,
          transform: `translate(-50%, -50%)${animTransform}`,
          opacity: anim.opacity,
        }}
      >
        {overlay.text}
      </div>
    </AbsoluteFill>
  );
}
