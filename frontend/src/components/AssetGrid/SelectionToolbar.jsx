import React from 'react';
import { FaTimes, FaCheckDouble, FaRegSquare, FaSync } from 'react-icons/fa';
import { Button } from '../ui';
import { STRATEGY } from './assetStatus';

/**
 * SelectionToolbar：選取模式的情境操作列。
 *
 * 取代預設工具列，集中「離開選取、全選 / 清除、批量設策略、重新分析選中」等需先選取的操作。
 * 與預設列同位置、等高（同樣帶 border / 圓角容器），切換時版面不跳動。工作進行中時禁用會觸發新工作的鈕。
 *
 * @param {number} total 素材總數
 * @param {number} selectedCount 已選數
 * @param {boolean} jobRunning 是否工作進行中
 * @param {()=>void} onExitSelection 離開選取模式（會清空選取）
 * @param {()=>void} onSelectAll 全選
 * @param {()=>void} onClearSelection 清除選取
 * @param {(strategy:string)=>void} onBulkStrategy 批量設策略
 * @param {()=>void} onReanalyzeSelected 重新分析選中
 */
export default function SelectionToolbar({
  total,
  selectedCount,
  jobRunning,
  onExitSelection,
  onSelectAll,
  onClearSelection,
  onBulkStrategy,
  onReanalyzeSelected,
}) {
  const hasSelection = selectedCount > 0;

  return (
    <div className="flex flex-wrap items-center gap-2 mb-5 px-3 py-2 bg-surface border border-border rounded-xl">
      {/* 離開選取模式（會清空選取）*/}
      <Button variant="ghost" size="sm" onClick={onExitSelection} leftIcon={<FaTimes size={12} />}>取消</Button>
      <span className="text-xs text-ink-faint">已選 {selectedCount} / {total}</span>

      <Button variant="secondary" size="sm" onClick={onSelectAll} disabled={jobRunning} leftIcon={<FaCheckDouble size={11} />}>全選</Button>
      <Button variant="secondary" size="sm" onClick={onClearSelection} disabled={jobRunning || !hasSelection} leftIcon={<FaRegSquare size={11} />}>清除</Button>

      {/* 批量設策略（套用到選中素材）*/}
      <div className="flex items-center gap-1 pl-2 border-l border-border">
        <Button variant="secondary" size="sm" onClick={() => onBulkStrategy(STRATEGY.SIMPLE)} disabled={jobRunning || !hasSelection}>設 Simple</Button>
        <Button variant="secondary" size="sm" onClick={() => onBulkStrategy(STRATEGY.COMPLEX)} disabled={jobRunning || !hasSelection}>設 Complex</Button>
      </div>

      {/* 重新分析選中（靠右）*/}
      <Button variant="secondary" size="sm" className="ml-auto" onClick={onReanalyzeSelected} disabled={jobRunning || !hasSelection} leftIcon={<FaSync size={11} />}>重新分析選中</Button>
    </div>
  );
}
