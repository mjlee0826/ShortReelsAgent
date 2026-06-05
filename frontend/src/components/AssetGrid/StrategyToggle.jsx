import React from 'react';
import { STRATEGY_OPTIONS, STRATEGY_LABEL } from './assetStatus';

// segmented 切換器的具名 class（避免 magic string 散落各處）
const SEGMENT_CONTAINER = 'inline-flex w-full rounded-lg bg-surface-2 p-0.5 gap-0.5 text-[11px] font-medium';
const SEGMENT_BASE = 'flex-1 px-2 py-1 rounded-md whitespace-nowrap transition-colors disabled:cursor-default';
const SEGMENT_ACTIVE = 'bg-accent text-white shadow-sm';
const SEGMENT_INACTIVE = 'text-ink-muted hover:text-ink';

/**
 * StrategyToggle：Simple / Complex 的 IG 風 segmented 切換器（無狀態受控元件）。
 *
 * 外層凹槽（bg-surface-2 + p-0.5）搭配 active 浮起填色 pill（rounded-md 小於外層 rounded-lg），
 * 營造 IG 分段控制觀感。每顆按鈕先 stopPropagation 再 onChange，確保父層「選取模式整卡可點」時，
 * 點切換策略不會誤觸整卡選取。
 *
 * @param {string} value 目前策略（STRATEGY.SIMPLE / COMPLEX）
 * @param {boolean} disabled 是否禁用（工作進行中）
 * @param {(value:string)=>void} onChange 切換回呼
 * @param {string} className 額外 class（如 mt-auto 釘底）
 */
export default function StrategyToggle({ value, disabled = false, onChange, className = '' }) {
  return (
    <div className={[SEGMENT_CONTAINER, className].join(' ')}>
      {STRATEGY_OPTIONS.map((option) => {
        const active = value === option;
        return (
          <button
            key={option}
            type="button"
            // active 時一併禁用（無需重複切換相同值），沿用原邏輯
            disabled={disabled || active}
            // 先攔截冒泡，避免選取模式下點策略誤觸整卡選取
            onClick={(e) => { e.stopPropagation(); onChange(option); }}
            className={[SEGMENT_BASE, active ? SEGMENT_ACTIVE : SEGMENT_INACTIVE].join(' ')}
          >
            {STRATEGY_LABEL[option]}
          </button>
        );
      })}
    </div>
  );
}
