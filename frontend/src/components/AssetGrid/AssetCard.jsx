import React from 'react';
import { FaImage, FaVideo, FaCheck } from 'react-icons/fa';
import { Badge } from '../ui';
import { THUMB_ASPECT, resolveStatusMeta, buildDetailText, detailTone } from './assetStatus';
import StrategyToggle from './StrategyToggle';

// 影片標圖示尺寸（具名常數，避免 magic number）
const VIDEO_TAG_ICON_SIZE = 9;
// 無縮圖時的佔位 icon 尺寸 class
const PLACEHOLDER_ICON_SIZE = 'text-3xl';

/**
 * AssetCard：單張素材卡片（縮圖 + 實心狀態膠囊 + Simple/Complex segmented + 選取）。
 *
 * 嚴格等高設計：縮圖固定 3:2（object-cover 正規化任意尺寸），縮圖上所有覆蓋元素皆 absolute
 * 不佔流排版；資訊區檔名與詳情各鎖單行（詳情恆渲染固定行高、空時保留空行）；策略列 mt-auto 釘底。
 * 任何狀態都渲染相同 DOM 槽位、只改「固定槽位的內容/顏色/脈動」，故各卡高度一致。
 *
 * 選取模式（selectionMode）顯示左上勾選框、整卡點擊切換選取；非選取模式整卡點擊開啟詳情彈窗。
 * effectiveStatus 已由父層把 WebSocket 即時狀態覆蓋在持久化狀態之上；切換 / 選取於處理中禁用。
 *
 * 素材身分一律用 relpath（asset.path）作為識別傳給回呼；asset.filename（basename）僅供顯示。
 *
 * @param {object} asset 素材資料（含 path 身分與 filename 顯示名）
 * @param {boolean} selected 是否已選取
 * @param {string} effectiveStatus 生效狀態（即時覆蓋後）
 * @param {?string} liveStage 即時處理階段名
 * @param {boolean} disabled 是否禁用（工作進行中）
 * @param {boolean} selectionMode 是否處於選取模式
 * @param {(path:string)=>void} onToggleSelect 切換選取
 * @param {(path:string, strategy:string)=>void} onToggleStrategy 切換策略
 * @param {(path:string)=>void} onOpenDetail 開啟詳情（非選取模式整卡點擊）
 */
export default function AssetCard({
  asset,
  selected,
  effectiveStatus,
  liveStage,
  disabled,
  selectionMode,
  onToggleSelect,
  onToggleStrategy,
  onOpenDetail,
}) {
  const meta = resolveStatusMeta(effectiveStatus);
  const isVideo = asset.media_kind === 'video';
  const detail = buildDetailText({
    status: effectiveStatus,
    reason: asset.reason,
    error: asset.error,
    liveStage,
  });
  // 選取模式且未禁用時，整卡可點選（IG / Google 相簿式）
  const cardSelectable = selectionMode && !disabled;
  // 非選取模式：整卡點擊開啟詳情（即使分析進行中亦可，詳情為唯讀）；選取模式維持切換選取
  const handleCardClick = selectionMode
    ? (cardSelectable ? () => onToggleSelect(asset.path) : undefined)
    : () => onOpenDetail?.(asset.path);
  // 游標手型：選取模式需可選才顯示；非選取模式恆可點開詳情
  const showPointer = selectionMode ? cardSelectable : true;

  return (
    <div
      onClick={handleCardClick}
      className={[
        'relative h-full flex flex-col bg-surface border rounded-2xl overflow-hidden transition-colors',
        selected ? 'border-accent' : 'border-border hover:border-border-strong',
        showPointer ? 'cursor-pointer' : '',
      ].join(' ')}
    >
      {/* 縮圖區（固定 3:2，object-cover 正規化任意尺寸使各卡等高）；覆蓋元素皆 absolute 不佔高 */}
      <div className={`relative ${THUMB_ASPECT} bg-canvas flex items-center justify-center shrink-0 overflow-hidden`}>
        {asset.thumbnail_url ? (
          <img src={asset.thumbnail_url} alt={asset.filename} loading="lazy" className="w-full h-full object-cover" />
        ) : (
          <div className={`text-ink-faint/40 ${PLACEHOLDER_ICON_SIZE}`}>{isVideo ? <FaVideo /> : <FaImage />}</div>
        )}

        {/* 底部暗化漸層，提升膠囊 / 影片標可讀 */}
        <div className="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/40 to-transparent" />

        {/* 選取覆蓋層（選取模式且已選）：accent 內框 + 淡色罩，強化選取回饋；不攔截點擊 */}
        {selectionMode && selected && (
          <div className="absolute inset-0 ring-2 ring-inset ring-accent bg-accent/20 pointer-events-none" />
        )}

        {/* 選取勾選框（左上，僅選取模式顯示）*/}
        {selectionMode && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggleSelect(asset.path); }}
            disabled={disabled}
            className={[
              'absolute top-2 left-2 z-10 w-6 h-6 rounded-md flex items-center justify-center border transition-colors disabled:opacity-40',
              selected ? 'bg-accent border-accent text-white' : 'bg-black/50 border-border-strong text-transparent hover:border-ink-faint',
            ].join(' ')}
            title={selected ? '取消選取' : '選取'}
          >
            <FaCheck size={11} />
          </button>
        )}

        {/* dirty 待重跑（右上，實心高對比）*/}
        {asset.dirty && (
          <div className="absolute top-2 right-2 z-10"><Badge tone="accent" solid>待重跑</Badge></div>
        )}

        {/* 影片標（左下）*/}
        {isVideo && (
          <span className="absolute bottom-2 left-2 z-10 text-[10px] px-1.5 py-0.5 rounded bg-black/70 text-white flex items-center gap-1">
            <FaVideo size={VIDEO_TAG_ICON_SIZE} /> 影片
          </span>
        )}

        {/* 狀態膠囊（右下，永遠渲染、實心高對比；處理中加脈動點）*/}
        <div className="absolute bottom-2 right-2 z-10">
          <Badge tone={meta.tone} solid>
            {meta.pulse && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
            {meta.label}
          </Badge>
        </div>
      </div>

      {/* 資訊 + 策略切換：flex-1 撐高、切換器 mt-auto 釘底 */}
      <div className="flex flex-col gap-1.5 p-2 flex-1">
        {/* 檔名（醒目：sm 粗體亮白，單行 truncate）*/}
        <p className="text-sm font-semibold text-ink truncate" title={asset.filename}>{asset.filename}</p>
        {/* 詳情鎖單行固定行高並恆渲染（空時保留空行）；依狀態著色提升可讀 */}
        <p className={`text-[12px] font-medium truncate h-4 leading-4 ${detailTone(effectiveStatus)}`} title={detail || undefined}>{detail}</p>

        {/* Simple / Complex segmented 切換器（mt-auto 釘底）；外層 stopPropagation 避免點切換器誤開詳情 */}
        <div className="mt-auto" onClick={(e) => e.stopPropagation()}>
          <StrategyToggle
            value={asset.strategy}
            disabled={disabled}
            onChange={(value) => onToggleStrategy(asset.path, value)}
          />
        </div>
      </div>
    </div>
  );
}
