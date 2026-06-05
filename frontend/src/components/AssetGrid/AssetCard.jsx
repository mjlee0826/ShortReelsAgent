import React from 'react';
import { FaImage, FaVideo, FaCheck } from 'react-icons/fa';
import { Badge } from '../ui';

/**
 * 五種素材狀態 → Badge tone 與顯示文字。
 * 後端持久化狀態為 unprocessed/success/rejected/error；processing 由 WebSocket 事件即時帶入。
 */
const STATUS_META = {
  unprocessed: { tone: 'neutral', label: '未處理' },
  processing: { tone: 'info', label: '處理中' },
  success: { tone: 'success', label: '成功' },
  rejected: { tone: 'warning', label: '拒絕' },
  error: { tone: 'danger', label: '失敗' },
};

const STRATEGY_SIMPLE = 'simple';
const STRATEGY_COMPLEX = 'complex';
const STRATEGY_OPTIONS = [STRATEGY_SIMPLE, STRATEGY_COMPLEX];

/**
 * AssetCard：單張素材卡片（縮圖 + 狀態徽章 + Simple/Complex 切換 + 選取）。
 *
 * 卡片採固定結構並撐滿格高（h-full）；縮圖固定 4:3 並 object-cover 正規化任意尺寸素材，
 * 詳情區保留固定高度，切換器以 mt-auto 釘在底部。配合 AssetGrid 的 auto-rows-fr，
 * 確保所有卡片的 Simple/Complex 切換器在各種縮圖尺寸 / 文字長度下位置與外觀皆一致（修正需求 2）。
 *
 * effectiveStatus 已由父層把 WebSocket 即時狀態覆蓋在持久化狀態之上；切換 / 選取於處理中禁用。
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
  const status = STATUS_META[effectiveStatus] || STATUS_META.unprocessed;
  const isVideo = asset.media_kind === 'video';
  const detail = effectiveStatus === 'rejected' ? asset.reason
    : effectiveStatus === 'error' ? asset.error
      : effectiveStatus === 'processing' && liveStage ? `分析中：${liveStage}`
        : null;

  return (
    <div
      className={`relative h-full flex flex-col bg-surface border rounded-2xl overflow-hidden transition-colors ${
        selected ? 'border-accent' : 'border-border hover:border-border-strong'
      }`}
    >
      {/* 選取 checkbox（左上）*/}
      <button
        onClick={() => onToggleSelect(asset.filename)}
        disabled={disabled}
        className={`absolute top-2 left-2 z-10 w-6 h-6 rounded-md flex items-center justify-center border transition-colors disabled:opacity-40 ${
          selected ? 'bg-accent border-accent text-white' : 'bg-black/50 border-border-strong text-transparent hover:border-ink-faint'
        }`}
        title={selected ? '取消選取' : '選取'}
      >
        <FaCheck size={11} />
      </button>

      {/* dirty 待重跑（右上）*/}
      {asset.dirty && (
        <div className="absolute top-2 right-2 z-10"><Badge tone="accent">待重跑</Badge></div>
      )}

      {/* 縮圖區（固定 4:3）*/}
      <div className="relative aspect-[4/3] bg-canvas flex items-center justify-center shrink-0">
        {asset.thumbnail_url ? (
          <img src={asset.thumbnail_url} alt={asset.filename} loading="lazy" className="w-full h-full object-cover" />
        ) : (
          <div className="text-ink-faint/40 text-3xl">{isVideo ? <FaVideo /> : <FaImage />}</div>
        )}
        {isVideo && (
          <span className="absolute bottom-2 left-2 text-[10px] px-1.5 py-0.5 rounded bg-black/70 text-ink-muted flex items-center gap-1">
            <FaVideo size={9} /> 影片
          </span>
        )}
        <div className="absolute bottom-2 right-2"><Badge tone={status.tone}>{status.label}</Badge></div>
      </div>

      {/* 資訊 + 策略切換：flex-1 撐高、切換器 mt-auto 釘底 */}
      <div className="flex flex-col gap-2 p-3 flex-1">
        <p className="text-xs text-ink-muted truncate" title={asset.filename}>{asset.filename}</p>
        {/* 詳情區保留固定高度，避免有無詳情造成版面位移 */}
        <p className="text-[11px] text-ink-faint line-clamp-2 min-h-[2rem]" title={detail || undefined}>{detail}</p>

        {/* Simple / Complex 切換器（whitespace-nowrap 確保窄卡不換行）*/}
        <div className="mt-auto flex rounded-lg overflow-hidden border border-border text-[11px]">
          {STRATEGY_OPTIONS.map((value) => {
            const active = asset.strategy === value;
            return (
              <button
                key={value}
                onClick={() => onToggleStrategy(asset.filename, value)}
                disabled={disabled || active}
                className={`flex-1 px-2 py-1.5 whitespace-nowrap transition-colors disabled:cursor-default ${
                  active ? 'bg-accent text-white' : 'bg-surface-2 text-ink-muted hover:bg-elevated hover:text-ink'
                }`}
              >
                {value === STRATEGY_SIMPLE ? 'Simple' : 'Complex'}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
