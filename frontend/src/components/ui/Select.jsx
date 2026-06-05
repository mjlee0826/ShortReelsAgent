import React from 'react';

/**
 * Select：帶標籤的下拉選單。options 為 [{ value, label }]；其餘 props 透傳給原生 select。
 */
export default function Select({ label, icon = null, hint = null, options = [], className = '', ...rest }) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label className="text-sm font-medium text-ink-muted flex items-center gap-2">
          {icon && <span className="text-accent">{icon}</span>}
          {label}
        </label>
      )}
      <select
        className={[
          'bg-surface-2 text-ink px-3.5 py-2.5 rounded-xl border border-border cursor-pointer transition-colors',
          'focus:outline-none focus:border-accent',
          className,
        ].join(' ')}
        {...rest}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      {hint && <p className="text-xs text-ink-faint px-0.5 leading-relaxed">{hint}</p>}
    </div>
  );
}
