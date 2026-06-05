import React from 'react';

/**
 * Button：全站統一的按鈕元件。
 *
 * 以 variant（視覺樣式）× size（尺寸）組合出一致外觀；支援 loading（顯示旋轉圈並禁用）、
 * leftIcon / rightIcon、fullWidth。封裝原本散落各頁的 Tailwind 按鈕樣式。
 */

// 各視覺樣式對應的 class（具名映射，避免散落的 magic string）
const VARIANT_CLASS = {
  primary: 'bg-accent hover:bg-accent-hover text-white shadow-lg shadow-accent/20 active:scale-[0.98]',
  secondary: 'bg-surface-2 hover:bg-elevated text-ink border border-border hover:border-border-strong',
  ghost: 'bg-transparent hover:bg-surface-2 text-ink-muted hover:text-ink',
  danger: 'bg-danger/15 hover:bg-danger/25 text-danger border border-danger/30',
  outline: 'bg-transparent border border-border-strong text-ink-muted hover:text-ink hover:border-accent',
};

// 各尺寸對應的 padding / 字級 / 圖文間距
const SIZE_CLASS = {
  sm: 'px-3 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2.5 text-sm gap-2',
  lg: 'px-5 py-3 text-base gap-2.5',
};

export default function Button({
  variant = 'primary',
  size = 'md',
  type = 'button',
  loading = false,
  disabled = false,
  fullWidth = false,
  leftIcon = null,
  rightIcon = null,
  className = '',
  children,
  ...rest
}) {
  const isDisabled = disabled || loading;
  return (
    <button
      type={type}
      disabled={isDisabled}
      className={[
        'inline-flex items-center justify-center font-medium rounded-xl transition-all',
        'disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100',
        VARIANT_CLASS[variant] || VARIANT_CLASS.primary,
        SIZE_CLASS[size] || SIZE_CLASS.md,
        fullWidth ? 'w-full' : '',
        className,
      ].join(' ')}
      {...rest}
    >
      {/* 載入中以旋轉圈取代左圖示，提供即時回饋 */}
      {loading ? (
        <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      ) : (
        leftIcon
      )}
      {children}
      {!loading && rightIcon}
    </button>
  );
}
