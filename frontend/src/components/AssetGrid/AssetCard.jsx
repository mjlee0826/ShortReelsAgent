import React from 'react';
import { FaImage, FaVideo, FaCheck } from 'react-icons/fa';

/**
 * 五種素材狀態的徽章樣式與文字（含前端即時覆蓋的「處理中」）。
 * 後端持久化狀態為 unprocessed/success/rejected/error；processing 由 WebSocket 事件即時帶入。
 */
const STATUS_BADGE = {
  unprocessed: { label: '未處理', className: 'bg-gray-700 text-gray-300' },
  processing: { label: '處理中', className: 'bg-blue-900/60 text-blue-300 animate-pulse' },
  success: { label: '成功', className: 'bg-green-900/50 text-green-400' },
  rejected: { label: '拒絕', className: 'bg-amber-900/50 text-amber-400' },
  error: { label: '失敗', className: 'bg-red-900/50 text-red-400' },
};

const STRATEGY_SIMPLE = 'simple';
const STRATEGY_COMPLEX = 'complex';

/**
 * AssetCard：單張素材卡片（縮圖 + 狀態徽章 + Simple/Complex 切換 + 選取 checkbox）。
 *
 * effectiveStatus 已由父層把 WebSocket 即時狀態覆蓋在持久化狀態之上；liveStage 為處理中當前的
 * stage 名稱（無則不顯示）。切換策略 / 選取在處理中(disabled)時禁用,避免與進行中的工作衝突。
 */
export default function AssetCard({
  asset,
  selected,
  effectiveStatus,
  liveStage,
  disabled,
  onToggleSelect,
  onToggleStrategy,
}) {
  const badge = STATUS_BADGE[effectiveStatus] || STATUS_BADGE.unprocessed;
  const isVideo = asset.media_kind === 'video';
  const detail = effectiveStatus === 'rejected' ? asset.reason
    : effectiveStatus === 'error' ? asset.error
      : effectiveStatus === 'processing' && liveStage ? `分析中：${liveStage}`
        : null;

  return (
    <div
      className={`relative flex flex-col bg-gray-900 border rounded-xl overflow-hidden transition-colors ${
        selected ? 'border-blue-500' : 'border-gray-800 hover:border-gray-700'
      }`}
    >
      {/* 選取 checkbox（左上角）*/}
      <button
        onClick={() => onToggleSelect(asset.filename)}
        disabled={disabled}
        className={`absolute top-2 left-2 z-10 w-6 h-6 rounded-md flex items-center justify-center border transition-colors ${
          selected ? 'bg-blue-600 border-blue-500 text-white' : 'bg-black/50 border-gray-600 text-transparent hover:border-gray-400'
        } disabled:opacity-40`}
        title={selected ? '取消選取' : '選取'}
      >
        <FaCheck size={11} />
      </button>

      {/* dirty 標記（策略已變更、待重跑）*/}
      {asset.dirty && (
        <span className="absolute top-2 right-2 z-10 text-[10px] px-2 py-0.5 rounded-full bg-purple-900/70 text-purple-300 border border-purple-700/50">
          待重跑
        </span>
      )}

      {/* 縮圖區（4:3）*/}
      <div className="relative aspect-[4/3] bg-gray-950 flex items-center justify-center">
        {asset.thumbnail_url ? (
          <img
            src={asset.thumbnail_url}
            alt={asset.filename}
            loading="lazy"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="text-gray-700 text-3xl">{isVideo ? <FaVideo /> : <FaImage />}</div>
        )}
        {/* 影片標記 */}
        {isVideo && (
          <span className="absolute bottom-2 left-2 text-[10px] px-1.5 py-0.5 rounded bg-black/70 text-gray-200 flex items-center gap-1">
            <FaVideo size={9} /> 影片
          </span>
        )}
        {/* 狀態徽章 */}
        <span className={`absolute bottom-2 right-2 text-[10px] px-2 py-0.5 rounded-full ${badge.className}`}>
          {badge.label}
        </span>
      </div>

      {/* 資訊與策略切換 */}
      <div className="flex flex-col gap-2 p-3">
        <p className="text-xs text-gray-300 truncate" title={asset.filename}>{asset.filename}</p>
        {detail && <p className="text-[11px] text-gray-500 line-clamp-2" title={detail}>{detail}</p>}

        {/* Simple / Complex 切換器 */}
        <div className="flex rounded-lg overflow-hidden border border-gray-700 text-[11px]">
          {[STRATEGY_SIMPLE, STRATEGY_COMPLEX].map((value) => (
            <button
              key={value}
              onClick={() => onToggleStrategy(asset.filename, value)}
              disabled={disabled || asset.strategy === value}
              className={`flex-1 px-2 py-1.5 transition-colors disabled:cursor-default ${
                asset.strategy === value
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
              }`}
            >
              {value === STRATEGY_SIMPLE ? 'Simple' : 'Complex'}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
