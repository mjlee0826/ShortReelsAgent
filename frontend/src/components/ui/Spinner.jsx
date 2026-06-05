import React from 'react';

/**
 * Spinner：旋轉載入指示。size 控制直徑（對應 Tailwind 寬高 class）。
 */
const SIZE_CLASS = {
  sm: 'w-4 h-4 border-2',
  md: 'w-6 h-6 border-2',
  lg: 'w-9 h-9 border-[3px]',
};

export default function Spinner({ size = 'md', className = '' }) {
  return (
    <span
      className={[
        'inline-block rounded-full border-accent border-t-transparent animate-spin',
        SIZE_CLASS[size] || SIZE_CLASS.md,
        className,
      ].join(' ')}
    />
  );
}
