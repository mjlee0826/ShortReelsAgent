import React from 'react';
import { TEXT_LANE_H } from '../../RemotionPlayer/constants';

// 拖邊縮放的把手寬度（左右各一）；與 ClipBlock 一致
const EDGE_HANDLE_PX = 8;
// 字幕方塊在 lane 列內的上下內縮（讓相鄰 lane 有視覺間隙）
const LANE_GAP_PX = 3;

/**
 * TextBlock：時間軸字幕軌上的單一字幕方塊（純呈現 + 回報滑鼠事件）。
 *
 * 絕對定位（left/top/width 由 TimelinePanel 依 start_at / lane 算好）；body 按下 → 點選 / 拖移、
 * 左右把手按下 → 拖邊改起訖。實際拖拽邏輯集中在 TimelinePanel（document 監聽），此元件只回報起始事件。
 * 字幕為自由浮動（可重疊、可有間隙、不 ripple），與 ClipBlock 的 gapless 模型不同。
 * @param {object} overlay 字幕資料
 * @param {number} index 字幕索引（對應 text_overlays 陣列與 selection.textIndex）
 * @param {number} leftPx 方塊左緣（px）
 * @param {number} widthPx 方塊寬度（px）
 * @param {number} topPx 方塊上緣（px；lane 疊放）
 * @param {boolean} isSelected 是否為目前選取字幕
 * @param {(index:number, e) => void} onBodyDown body 按下
 * @param {(index:number, edge:'left'|'right', e) => void} onEdgeDown 邊把手按下
 */
export default function TextBlock({ overlay, index, leftPx, widthPx, topPx, isSelected, onBodyDown, onEdgeDown }) {
  const label = overlay.text || '（空白字幕）';
  return (
    <div
      style={{
        left: `${leftPx}px`,
        width: `${widthPx}px`,
        top: `${topPx + LANE_GAP_PX}px`,
        height: `${TEXT_LANE_H - LANE_GAP_PX * 2}px`,
      }}
      className="absolute"
    >
      {/* body：點選 / 拖移 */}
      <div
        onMouseDown={(e) => onBodyDown(index, e)}
        title={label}
        className={`h-full px-2 rounded-sm overflow-hidden flex items-center cursor-grab active:cursor-grabbing transition-colors ${
          isSelected ? 'bg-accent/30 ring-1 ring-accent ring-inset' : 'bg-accent/15 hover:bg-accent/25'
        }`}
      >
        <span className="text-[10px] text-ink truncate pointer-events-none">{label}</span>
      </div>

      {/* 左 / 右 邊把手：拖邊改起訖（stopPropagation 避免同時觸發 body 的拖移）*/}
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
