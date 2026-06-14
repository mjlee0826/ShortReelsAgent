import React from 'react';
import { FaImage, FaVideo, FaClock } from 'react-icons/fa';
import { formatTotalDuration } from './assetSummary';

// 統計項目 icon 尺寸（具名常數，避免 magic number）
const STAT_ICON_SIZE = 12;

/**
 * 單一統計膠囊：icon + 標籤 + 數值（同一視覺槽位，三項等高一致）。
 *
 * @param {React.ReactNode} icon 前置圖示
 * @param {string} label 統計項目名稱
 * @param {string} value 統計值（已格式化字串）
 */
function StatChip({ icon, label, value }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-surface border border-border rounded-xl text-sm">
      <span className="text-ink-faint">{icon}</span>
      <span className="text-ink-faint">{label}</span>
      <span className="font-semibold text-ink tabular-nums">{value}</span>
    </div>
  );
}

/**
 * AssetSummaryBar：素材統計列（照片數 / 影片數 / 影片總時長）。
 *
 * 純呈現元件：統計由父層以 summarizeAssets 算好後傳入，本元件只負責版面與格式化顯示。
 * 與工具列風格一致（IG 深色 token），置於頁面標題下方供使用者一眼掌握素材組成。
 *
 * @param {number} imageCount 照片數
 * @param {number} videoCount 影片數
 * @param {number} totalVideoDuration 影片總時長（秒）
 */
export default function AssetSummaryBar({ imageCount, videoCount, totalVideoDuration }) {
  return (
    <div className="flex flex-wrap items-center gap-2 mb-5">
      <StatChip icon={<FaImage size={STAT_ICON_SIZE} />} label="照片" value={`${imageCount} 張`} />
      <StatChip icon={<FaVideo size={STAT_ICON_SIZE} />} label="影片" value={`${videoCount} 部`} />
      <StatChip
        icon={<FaClock size={STAT_ICON_SIZE} />}
        label="影片總時長"
        value={formatTotalDuration(totalVideoDuration)}
      />
    </div>
  );
}
