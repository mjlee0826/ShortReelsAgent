import React from 'react';
import { FaCheckDouble, FaRegSquare, FaSync, FaPlay, FaEdit } from 'react-icons/fa';
import { Button } from '../ui';

/**
 * BulkActionBar：頂部批量操作列。
 *
 * 提供全選 / 清除、批量設策略、重新分析（選中 / 全部）、開始生成、前往編輯器。
 * 工作進行中（jobRunning）時禁用會觸發新工作的按鈕，避免重複送出。
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

  return (
    <div className="flex flex-wrap items-center gap-2 mb-5">
      <span className="text-xs text-ink-faint mr-1">已選 {selectedCount} / {total}</span>

      <Button variant="secondary" size="sm" onClick={onSelectAll} disabled={jobRunning} leftIcon={<FaCheckDouble size={11} />}>全選</Button>
      <Button variant="secondary" size="sm" onClick={onClearSelection} disabled={jobRunning || !hasSelection} leftIcon={<FaRegSquare size={11} />}>清除選取</Button>

      {/* 批量設策略（套用到選中素材）*/}
      <div className="flex items-center gap-1 pl-2 border-l border-border">
        <Button variant="secondary" size="sm" onClick={() => onBulkStrategy('simple')} disabled={jobRunning || !hasSelection}>選中設 Simple</Button>
        <Button variant="secondary" size="sm" onClick={() => onBulkStrategy('complex')} disabled={jobRunning || !hasSelection}>選中設 Complex</Button>
      </div>

      {/* 重新分析 */}
      <div className="flex items-center gap-1 pl-2 border-l border-border">
        <Button variant="secondary" size="sm" onClick={onReanalyzeSelected} disabled={jobRunning || !hasSelection} leftIcon={<FaSync size={11} />}>重新分析選中</Button>
        <Button variant="secondary" size="sm" onClick={onReanalyzeAll} disabled={jobRunning || total === 0} leftIcon={<FaSync size={11} />}>重新分析全部</Button>
      </div>

      {/* 右側主要動作 */}
      <div className="flex items-center gap-2 ml-auto">
        <Button variant="secondary" size="sm" onClick={onGoEditor} leftIcon={<FaEdit size={11} />}>前往編輯器</Button>
        <Button
          size="sm"
          onClick={onGenerate}
          disabled={jobRunning || total === 0}
          loading={jobRunning}
          leftIcon={!jobRunning ? <FaPlay size={11} /> : null}
        >
          {jobRunning ? '分析中...' : '開始生成'}
        </Button>
      </div>
    </div>
  );
}
