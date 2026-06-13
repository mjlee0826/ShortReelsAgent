import React from 'react';
import { resolveTextOverlay } from '../../../utils/textOverlay';

// 拖邊裁切的把手寬度（左右各一）
const EDGE_HANDLE_PX = 8;

/**
 * ClipBlock：時間軸影片軌上的單一片段方塊（純呈現 + 回報滑鼠事件）。
 *
 * 寬度正比於時長；body 按下 → 點選/拖拉重排；左右邊把手按下 → 拖邊裁切。
 * 實際拖拽邏輯集中在 TimelinePanel（document 監聽），此元件只負責回報起始事件。
 * @param {object} clip 片段資料
 * @param {number} index 片段索引
 * @param {number} widthPx 方塊寬度（px）
 * @param {boolean} isSelected 是否為目前選取片段
 * @param {boolean} isDragging 是否正被拖曳（重排中）
 * @param {(index:number, edge:'left'|'right', e) => void} onEdgeDown 邊把手按下
 * @param {(index:number, e) => void} onBodyDown body 按下
 */
export default function ClipBlock({ clip, index, widthPx, isSelected, isDragging, onEdgeDown, onBodyDown }) {
  const hasTransition = clip.transition_in && clip.transition_in !== 'none';
  // 字幕摘要：相容新結構 text_overlay 與 legacy overlay_text
  const overlayText = resolveTextOverlay(clip)?.text;

  return (
    <div
      style={{ width: `${widthPx}px` }}
      className={`relative h-full shrink-0 border-r border-border/60 ${isDragging ? 'opacity-40' : ''}`}
    >
      {/* body：點選 / 拖拉重排 */}
      <div
        onMouseDown={(e) => onBodyDown(index, e)}
        title={`片段 ${index + 1}｜${clip.clip_id}`}
        className={`h-full px-2 py-1 overflow-hidden cursor-grab active:cursor-grabbing transition-colors ${
          isSelected ? 'bg-accent/25 ring-1 ring-accent ring-inset' : 'bg-surface-2 hover:bg-elevated'
        }`}
      >
        {hasTransition && <span className="absolute left-0 top-0 bottom-0 w-1 bg-accent/70 pointer-events-none" />}
        <span className="text-[11px] font-bold text-ink">{index + 1}</span>
        {overlayText && (
          <span className="block text-[10px] text-ink-faint truncate">💬 {overlayText}</span>
        )}
      </div>

      {/* 左 / 右 邊把手：拖邊裁切（stopPropagation 避免同時觸發 body 的重排）*/}
      <div
        onMouseDown={(e) => { e.stopPropagation(); onEdgeDown(index, 'left', e); }}
        style={{ width: `${EDGE_HANDLE_PX}px` }}
        className="absolute left-0 top-0 bottom-0 cursor-ew-resize hover:bg-accent/60 z-10"
      />
      <div
        onMouseDown={(e) => { e.stopPropagation(); onEdgeDown(index, 'right', e); }}
        style={{ width: `${EDGE_HANDLE_PX}px` }}
        className="absolute right-0 top-0 bottom-0 cursor-ew-resize hover:bg-accent/60 z-10"
      />
    </div>
  );
}
