import React from 'react';

/**
 * IconButton：純圖示的方形按鈕（工具列鈕 / 關閉鈕等）。tone 決定 hover 後的語意色。
 */

// hover 後的語意色映射
const TONE_CLASS = {
  neutral: 'text-ink-muted hover:text-ink hover:bg-surface-2',
  danger: 'text-ink-faint hover:text-danger hover:bg-danger/10',
  accent: 'text-ink-muted hover:text-accent hover:bg-accent-soft',
  // 疊在封面縮圖上的危險操作（如刪除）：半透明深底確保可讀，hover 轉實心危險色
  'overlay-danger': 'text-white bg-black/45 hover:bg-danger backdrop-blur-sm',
};

export default function IconButton({ tone = 'neutral', className = '', children, ...rest }) {
  return (
    <button
      type="button"
      className={[
        'inline-flex items-center justify-center w-9 h-9 rounded-lg transition-colors',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        TONE_CLASS[tone] || TONE_CLASS.neutral,
        className,
      ].join(' ')}
      {...rest}
    >
      {children}
    </button>
  );
}
