import React, { useState } from 'react';
import { FaChevronDown, FaChevronRight, FaChevronLeft, FaLock, FaCheckSquare, FaRegSquare } from 'react-icons/fa';

/**
 * 檢視器共用小控制項（DRY）。
 *
 * 提供分組容器與各式列控制項（滑桿 / 下拉 / 文字框 / 數字 / 唯讀），
 * 讓 ClipInspector、BgmInspector、ProjectInspector 以一致樣式組裝欄位。
 */

/**
 * InspectorBackRow：返回全域設定的麵包屑列（呈現層）。
 *
 * 選中片段 / 配樂後右側檢視器會切離全域（專案）面板，編輯器內原本缺少
 * 「取消選取」的導線；此列補足該導線。實際清除選取的動作由呼叫端透過
 * onBack 注入（通常為 store 的 clearSelection），維持本模組純呈現、不耦合 store。
 * @param {() => void} onBack 點擊時觸發
 * @param {string} [label] 顯示文字
 */
export function InspectorBackRow({ onBack, label = '回到全域設定' }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="w-full flex items-center gap-1.5 px-5 py-2 text-xs text-ink-faint hover:text-ink hover:bg-surface-2/60 border-b border-border transition-colors cursor-pointer"
    >
      <FaChevronLeft size={10} /> {label}
    </button>
  );
}

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
        className={`w-full flex items-center gap-2 px-5 py-3 text-sm font-bold uppercase tracking-wider text-ink-faint ${
          collapsible ? 'hover:text-ink-muted cursor-pointer' : 'cursor-default'
        }`}
      >
        {collapsible && (isOpen ? <FaChevronDown size={11} /> : <FaChevronRight size={11} />)}
        {title}
      </button>
      {isOpen && <div className="flex flex-col gap-3.5 px-5 pb-5">{children}</div>}
    </div>
  );
}

/** 欄位列的標籤＋右側內容骨架 */
function Row({ label, children, hint }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-3">
        <label className="text-sm text-ink-muted shrink-0">{label}</label>
        {children}
      </div>
      {hint && <p className="text-xs text-ink-faint">{hint}</p>}
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
      <div className="flex items-center gap-2.5 flex-1 max-w-[58%]">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="flex-1 accent-accent cursor-pointer"
        />
        <span className="text-sm text-ink font-mono w-12 text-right shrink-0">{display}</span>
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
        className="bg-surface-2 text-ink text-sm px-3 py-2 rounded-lg border border-border focus:outline-none focus:border-accent cursor-pointer max-w-[58%]"
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
      <div className="flex items-center gap-2 max-w-[58%]">
        <input
          type="number"
          value={value}
          step={step}
          min={min}
          onChange={(e) => onChange(e.target.value === '' ? 0 : parseFloat(e.target.value))}
          className="bg-surface-2 text-ink text-sm px-3 py-2 rounded-lg border border-border focus:outline-none focus:border-accent w-24 text-right"
        />
        <span className="text-xs text-ink-faint">{unit}</span>
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
      <label className="text-sm text-ink-muted">{label}</label>
      <textarea
        rows={rows}
        value={value || ''}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface-2 text-ink text-base p-3 rounded-lg border border-border focus:outline-none focus:border-accent resize-none placeholder-ink-faint leading-relaxed"
      />
    </div>
  );
}

/**
 * ToggleRow：布林開關列（如自動運鏡 / 卡點總開關）。以勾選框呈現，與生成表單的勾選樣式一致。
 * disabled 時置灰且不可點，用於表達「從屬於另一開關」的相依關係（例：卡點需先開運鏡）。
 * @param {string} label 欄位標籤
 * @param {boolean} checked 是否勾選
 * @param {(next: boolean) => void} onChange 勾選變更回呼（傳出切換後的布林值）
 * @param {string} [hint] 標籤下方的輔助說明
 * @param {boolean} [disabled] 是否置灰不可點
 */
export function ToggleRow({ label, checked, onChange, hint, disabled = false }) {
  return (
    <Row label={label} hint={hint}>
      <button
        type="button"
        disabled={disabled}
        aria-pressed={checked}
        onClick={() => onChange(!checked)}
        className={`flex items-center text-lg shrink-0 transition-colors ${
          disabled ? 'opacity-40 cursor-not-allowed text-ink-faint' : 'cursor-pointer hover:text-ink'
        }`}
      >
        {checked
          ? <FaCheckSquare className={disabled ? '' : 'text-accent'} />
          : <FaRegSquare />}
      </button>
    </Row>
  );
}

/**
 * ReadonlyRow：唯讀欄位列（進階欄位 / 衍生值 / AI 說明）。附鎖頭標示不可編輯。
 */
export function ReadonlyRow({ label, value, locked = false }) {
  return (
    <Row label={label}>
      <span className="text-sm text-ink-faint font-mono flex items-center gap-1.5 max-w-[58%] truncate">
        {locked && <FaLock size={10} className="shrink-0" />}
        <span className="truncate">{value ?? '—'}</span>
      </span>
    </Row>
  );
}
