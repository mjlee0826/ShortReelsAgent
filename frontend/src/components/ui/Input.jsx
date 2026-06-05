import React from 'react';

/**
 * Input：帶標籤的文字輸入。支援 icon（標籤前圖示）、hint（輔助說明）、error（錯誤訊息，優先於 hint）。
 * 其餘 props（value / onChange / placeholder / type…）透傳給原生 input。
 */
export default function Input({ label, icon = null, hint = null, error = null, className = '', ...rest }) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label className="text-sm font-medium text-ink-muted flex items-center gap-2">
          {icon && <span className="text-accent">{icon}</span>}
          {label}
        </label>
      )}
      <input
        className={[
          'bg-surface-2 text-ink placeholder-ink-faint px-3.5 py-2.5 rounded-xl border transition-colors',
          'focus:outline-none focus:border-accent',
          error ? 'border-danger/60' : 'border-border',
          className,
        ].join(' ')}
        {...rest}
      />
      {error ? (
        <p className="text-xs text-danger px-0.5">{error}</p>
      ) : hint ? (
        <p className="text-xs text-ink-faint px-0.5 leading-relaxed">{hint}</p>
      ) : null}
    </div>
  );
}
