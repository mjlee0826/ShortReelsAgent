import React from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';

/**
 * Playhead：時間軸播放頭（紅線）。
 *
 * 獨立訂閱 playheadSeconds，使其每幀更新時只重繪這條線、不牽動整個 TimelinePanel
 * 與所有 ClipBlock（效能考量）。
 * @param {number} pxPerSecond 每秒像素（由 TimelinePanel 傳入）
 */
export default function Playhead({ pxPerSecond }) {
  const seconds = useBlueprintStore((s) => s.playheadSeconds);
  const left = seconds * pxPerSecond;

  return (
    <div
      className="absolute top-0 bottom-0 w-px bg-danger pointer-events-none z-20"
      style={{ left: `${left}px` }}
    >
      {/* 頂端把手三角，便於辨識 */}
      <div className="absolute -top-0.5 -left-1 w-2 h-2 rounded-sm bg-danger" />
    </div>
  );
}
