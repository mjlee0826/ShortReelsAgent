import React from 'react';
import { FaSearch } from 'react-icons/fa';
import { Select } from '../ui';
import { SORT_OPTIONS } from './projectStatus';

/**
 * ProjectToolbar：儀表板瀏覽工具列（受控元件，state 提升至頁面）。
 *
 * 左：名稱搜尋框（沿用 Input 的設計 token，自製內嵌放大鏡，因 ui/Input 的 icon 只在 label 旁）。
 * 右：排序下拉（沿用 ui/Select）。
 */
export default function ProjectToolbar({ searchQuery, onSearchChange, sortKey, onSortChange }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-6">
      {/* 搜尋框 */}
      <div className="relative flex-1">
        <FaSearch className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-faint" size={13} />
        <input
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="搜尋專案名稱…"
          className="w-full bg-surface-2 text-ink placeholder-ink-faint pl-10 pr-3.5 py-2.5 rounded-xl border border-border focus:outline-none focus:border-accent transition-colors"
        />
      </div>

      {/* 排序 */}
      <Select
        value={sortKey}
        onChange={(e) => onSortChange(e.target.value)}
        options={SORT_OPTIONS}
        className="sm:w-44"
      />
    </div>
  );
}
