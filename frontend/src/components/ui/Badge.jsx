import React from 'react';

/**
 * Badge：小型狀態膠囊。tone 決定語意色（中性 / 成功 / 警告 / 危險 / 資訊 / 強調）。
 */

// 各語意色對應的底色 + 文字 + 邊框
const TONE_CLASS = {
  neutral: 'bg-surface-2 text-ink-muted border border-border',
  success: 'bg-success/15 text-success border border-success/30',
  warning: 'bg-warning/15 text-warning border border-warning/30',
  danger: 'bg-danger/15 text-danger border border-danger/30',
  info: 'bg-info/15 text-info border border-info/30',
  accent: 'bg-accent-soft text-accent-ink border border-accent/30',
};

export default function Badge({ tone = 'neutral', className = '', children }) {
  return (
    <span
      className={[
        'inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap',
        TONE_CLASS[tone] || TONE_CLASS.neutral,
        className,
      ].join(' ')}
    >
      {children}
    </span>
  );
}
