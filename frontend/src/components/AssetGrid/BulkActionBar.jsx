import React from 'react';
import { FaCheckDouble, FaRegSquare, FaSync, FaPlay, FaEdit } from 'react-icons/fa';

/**
 * BulkActionBar：頂部批量操作列。
 *
 * 提供全選 / 清除、批量設策略、重新分析（選中 / 全部）、開始生成、前往編輯器。
 * 工作進行中（jobRunning）時禁用會觸發新工作的按鈕,避免重複送出。
 */
export default function BulkActionBar({
  total,
  selectedCount,
  jobRunning,
  onSelectAll,
  onClearSelection,
  onBulkStrategy,
  onReanalyzeSelected,
  onReanalyzeAll,
  onGenerate,
  onGoEditor,
}) {
  const hasSelection = selectedCount > 0;
  const btnBase = 'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed';

  return (
    <div className="flex flex-wrap items-center gap-2 mb-5">
      {/* 選取狀態 */}
      <span className="text-xs text-gray-500 mr-1">
        已選 {selectedCount} / {total}
      </span>

      <button onClick={onSelectAll} disabled={jobRunning} className={`${btnBase} bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white`}>
        <FaCheckDouble size={11} /> 全選
      </button>
      <button onClick={onClearSelection} disabled={jobRunning || !hasSelection} className={`${btnBase} bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white`}>
        <FaRegSquare size={11} /> 清除選取
      </button>

      {/* 批量設策略（套用到選中素材）*/}
      <div className="flex items-center gap-1 pl-2 border-l border-gray-800">
        <button onClick={() => onBulkStrategy('simple')} disabled={jobRunning || !hasSelection} className={`${btnBase} bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white`}>
          選中設 Simple
        </button>
        <button onClick={() => onBulkStrategy('complex')} disabled={jobRunning || !hasSelection} className={`${btnBase} bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white`}>
          選中設 Complex
        </button>
      </div>

      {/* 重新分析 */}
      <div className="flex items-center gap-1 pl-2 border-l border-gray-800">
        <button onClick={onReanalyzeSelected} disabled={jobRunning || !hasSelection} className={`${btnBase} bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white`}>
          <FaSync size={11} /> 重新分析選中
        </button>
        <button onClick={onReanalyzeAll} disabled={jobRunning || total === 0} className={`${btnBase} bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white`}>
          <FaSync size={11} /> 重新分析全部
        </button>
      </div>

      {/* 右側主要動作 */}
      <div className="flex items-center gap-2 ml-auto">
        <button onClick={onGoEditor} className={`${btnBase} bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white`}>
          <FaEdit size={11} /> 前往編輯器
        </button>
        <button onClick={onGenerate} disabled={jobRunning || total === 0} className={`${btnBase} bg-blue-600 text-white hover:bg-blue-500 shadow-lg shadow-blue-500/20`}>
          <FaPlay size={11} /> {jobRunning ? '分析中...' : '開始生成'}
        </button>
      </div>
    </div>
  );
}
