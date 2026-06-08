import React, { useState } from 'react';
import { FaChevronDown, FaChevronRight, FaLock } from 'react-icons/fa';

/**
 * 檢視器共用小控制項（DRY）。
 *
 * 提供分組容器與各式列控制項（滑桿 / 下拉 / 文字框 / 數字 / 唯讀），
 * 讓 ClipInspector、BgmInspector、ProjectInspector 以一致樣式組裝欄位。
 */

/**
 * InspectorSection：檢視器分組容器，可選收合。
 * @param {string} title 分組標題
 * @param {boolean} collapsible 是否可收合
 * @param {boolean} defaultOpen 預設是否展開
 */
export function InspectorSection({ title, collapsible = false, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = collapsible ? open : true;

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={() => collapsible && setOpen((v) => !v)}
        className={`w-full flex items-center gap-2 px-4 py-2.5 text-xs font-bold uppercase tracking-wider text-ink-faint ${
          collapsible ? 'hover:text-ink-muted cursor-pointer' : 'cursor-default'
        }`}
      >
        {collapsible && (isOpen ? <FaChevronDown size={10} /> : <FaChevronRight size={10} />)}
        {title}
      </button>
      {isOpen && <div className="flex flex-col gap-3 px-4 pb-4">{children}</div>}
    </div>
  );
}

/** 欄位列的標籤＋右側內容骨架 */
function Row({ label, children, hint }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-3">
        <label className="text-xs text-ink-muted shrink-0">{label}</label>
        {children}
      </div>
      {hint && <p className="text-[11px] text-ink-faint">{hint}</p>}
    </div>
  );
}

/**
 * SliderRow：滑桿列（縮放 / 各種音量）。回呼傳出已轉好的浮點數值。
 */
export function SliderRow({ label, value, min, max, step, onChange, format }) {
  const display = format ? format(value) : value;
  return (
    <Row label={label}>
      <div className="flex items-center gap-2 flex-1 max-w-[60%]">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="flex-1 accent-accent cursor-pointer"
        />
        <span className="text-xs text-ink font-mono w-10 text-right shrink-0">{display}</span>
      </div>
    </Row>
  );
}

/**
 * SelectRow：下拉列（濾鏡 / 轉場）。options 為 [{ value, label }]。
 */
export function SelectRow({ label, value, options, onChange }) {
  return (
    <Row label={label}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface-2 text-ink text-xs px-2.5 py-1.5 rounded-lg border border-border focus:outline-none focus:border-accent cursor-pointer max-w-[60%]"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </Row>
  );
}

/**
 * NumberRow：數字輸入列（裁切秒數 / 起播點）。回呼傳出浮點數值（空字串視為 0）。
 */
export function NumberRow({ label, value, step = 0.1, min, onChange, unit = 's' }) {
  return (
    <Row label={label}>
      <div className="flex items-center gap-1.5 max-w-[60%]">
        <input
          type="number"
          value={value}
          step={step}
          min={min}
          onChange={(e) => onChange(e.target.value === '' ? 0 : parseFloat(e.target.value))}
          className="bg-surface-2 text-ink text-xs px-2.5 py-1.5 rounded-lg border border-border focus:outline-none focus:border-accent w-20 text-right"
        />
        <span className="text-[11px] text-ink-faint">{unit}</span>
      </div>
    </Row>
  );
}

/**
 * TextAreaRow：多行文字列（字幕）。
 */
export function TextAreaRow({ label, value, placeholder, onChange, rows = 2 }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs text-ink-muted">{label}</label>
      <textarea
        rows={rows}
        value={value || ''}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface-2 text-ink text-sm p-2.5 rounded-lg border border-border focus:outline-none focus:border-accent resize-none placeholder-ink-faint"
      />
    </div>
  );
}

/**
 * ReadonlyRow：唯讀欄位列（進階欄位 / 衍生值 / AI 說明）。附鎖頭標示不可編輯。
 */
export function ReadonlyRow({ label, value, locked = false }) {
  return (
    <Row label={label}>
      <span className="text-xs text-ink-faint font-mono flex items-center gap-1.5 max-w-[60%] truncate">
        {locked && <FaLock size={9} className="shrink-0" />}
        <span className="truncate">{value ?? '—'}</span>
      </span>
    </Row>
  );
}
