import React from 'react';

/**
 * Badge：小型狀態膠囊。tone 決定語意色（中性 / 成功 / 警告 / 危險 / 資訊 / 強調）。
 *
 * 預設為半透明柔色（適合深色卡身）；solid 為實心高對比版，疊在封面縮圖 / 影像上仍清楚可讀。
 */

// 預設半透明柔色：底色 + 文字 + 邊框（適合深色表面）
const TONE_CLASS = {
  neutral: 'bg-surface-2 text-ink-muted border border-border',
  success: 'bg-success/15 text-success border border-success/30',
  warning: 'bg-warning/15 text-warning border border-warning/30',
  danger: 'bg-danger/15 text-danger border border-danger/30',
  info: 'bg-info/15 text-info border border-info/30',
  accent: 'bg-accent-soft text-accent-ink border border-accent/30',
};

// 實心高對比版：不透明底 + 反差文字，用於疊在影像上確保可讀（如封面狀態膠囊）
const TONE_SOLID_CLASS = {
  neutral: 'bg-black/70 text-white backdrop-blur-sm',
  success: 'bg-success text-black',
  warning: 'bg-warning text-black',
  danger: 'bg-danger text-white',
  info: 'bg-info text-black',
  accent: 'bg-accent text-white',
};

export default function Badge({ tone = 'neutral', solid = false, className = '', children }) {
  // solid 時改用實心高對比樣式並加粗、加陰影，提升疊圖可讀性；否則維持原半透明柔色
  const toneMap = solid ? TONE_SOLID_CLASS : TONE_CLASS;
  return (
    <span
      className={[
        'inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full whitespace-nowrap',
        solid ? 'font-semibold shadow-sm' : 'font-medium',
        toneMap[tone] || toneMap.neutral,
        className,
      ].join(' ')}
    >
      {children}
    </span>
  );
}
