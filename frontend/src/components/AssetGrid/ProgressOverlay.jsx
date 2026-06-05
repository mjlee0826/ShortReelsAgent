import React from 'react';

/**
 * ProgressOverlay：頁面頂部 Phase 1 分析進度條。
 *
 * 只在工作進行中（visible）顯示;done / total 由父頁依 WebSocket 的 pipeline_finish 事件累計。
 * total 為 0 時不顯示百分比進度條(避免除以零),改顯示準備中提示。
 */
export default function ProgressOverlay({ visible, done, total }) {
  if (!visible) return null;
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <div className="mb-5 px-4 py-3 bg-blue-950/40 border border-blue-800/40 rounded-xl">
      <div className="flex items-center justify-between mb-2 text-xs text-blue-300">
        <span>正在分析素材...</span>
        <span>{total > 0 ? `${done} / ${total}` : '準備中'}</span>
      </div>
      <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 transition-all duration-300"
          style={{ width: `${total > 0 ? percent : 15}%` }}
        />
      </div>
    </div>
  );
}
