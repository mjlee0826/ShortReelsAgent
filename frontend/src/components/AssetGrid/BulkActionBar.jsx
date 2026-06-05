import React from 'react';
import { FaCheckSquare, FaSync, FaPlay, FaEdit } from 'react-icons/fa';
import { Button } from '../ui';

/**
 * BulkActionBar：預設（非選取模式）工具列。
 *
 * 左側「選取」進入選取模式；右側為主要動作：重新分析全部、前往編輯器、開始生成。
 * 需先選取的批量操作改由選取模式的 SelectionToolbar 提供。工作進行中時禁用會觸發新工作的按鈕。
 *
 * @param {number} total 素材總數
 * @param {boolean} jobRunning 是否工作進行中
 * @param {()=>void} onEnterSelection 進入選取模式
 * @param {()=>void} onReanalyzeAll 重新分析全部
 * @param {()=>void} onGoEditor 前往編輯器
 * @param {()=>void} onGenerate 開始生成
 */
export default function BulkActionBar({
  total,
  jobRunning,
  onEnterSelection,
  onReanalyzeAll,
  onGoEditor,
  onGenerate,
}) {
  const isEmpty = total === 0;

  return (
    <div className="flex flex-wrap items-center gap-2 mb-5">
      {/* 進入選取模式（空專案無可選 → 禁用）*/}
      <Button variant="secondary" size="sm" onClick={onEnterSelection} disabled={jobRunning || isEmpty} leftIcon={<FaCheckSquare size={11} />}>選取</Button>

      {/* 右側主要動作 */}
      <div className="flex items-center gap-2 ml-auto">
        <Button variant="secondary" size="sm" onClick={onReanalyzeAll} disabled={jobRunning || isEmpty} leftIcon={<FaSync size={11} />}>重新分析全部</Button>
        <Button variant="secondary" size="sm" onClick={onGoEditor} leftIcon={<FaEdit size={11} />}>前往編輯器</Button>
        <Button
          size="sm"
          onClick={onGenerate}
          disabled={jobRunning || isEmpty}
          loading={jobRunning}
          leftIcon={!jobRunning ? <FaPlay size={11} /> : null}
        >
          {jobRunning ? '分析中...' : '開始生成'}
        </Button>
      </div>
    </div>
  );
}
