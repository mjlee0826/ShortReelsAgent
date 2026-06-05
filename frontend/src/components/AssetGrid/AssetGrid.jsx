import React from 'react';
import AssetCard from './AssetCard';

/**
 * AssetGrid：素材縮圖網格（Composite）。
 *
 * 把每個 AssetView 渲染成一張 AssetCard,並把該素材的即時狀態（liveStatusMap[filename]）覆蓋在
 * 持久化狀態之上後傳入。本身不持狀態,所有互動回呼透傳給父頁。
 */
export default function AssetGrid({
  assets,
  selected,
  liveStatusMap,
  jobRunning,
  onToggleSelect,
  onToggleStrategy,
}) {
  return (
    <div className="grid auto-rows-fr grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
      {assets.map((asset) => {
        const live = liveStatusMap[asset.filename];
        return (
          <AssetCard
            key={asset.filename}
            asset={asset}
            selected={selected.has(asset.filename)}
            effectiveStatus={live?.status || asset.status}
            liveStage={live?.stage || null}
            disabled={jobRunning}
            onToggleSelect={onToggleSelect}
            onToggleStrategy={onToggleStrategy}
          />
        );
      })}
    </div>
  );
}
