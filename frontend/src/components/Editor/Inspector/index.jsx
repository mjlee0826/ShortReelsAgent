import React from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import ClipInspector from './ClipInspector';
import BgmInspector from './BgmInspector';
import TextOverlayInspector from './TextOverlayInspector';
import ProjectInspector from './ProjectInspector';

/**
 * Inspector：右側檢視器（State Pattern by selection）。
 *
 * 依目前選取對象切換顯示：
 *   - 'clip' → ClipInspector（逐段屬性）
 *   - 'bgm'  → BgmInspector（配樂軌）
 *   - 'text' → TextOverlayInspector（字幕軌單條字幕）
 *   - 其他   → ProjectInspector（全域 / 輸出，預設面板）
 * @param {() => void} onRequestRegenerate 由子面板要求開啟重新生成面板
 */
export default function Inspector({ onRequestRegenerate }) {
  const selectionType = useBlueprintStore((s) => s.selection.type);

  return (
    <div className="w-full h-full overflow-y-auto bg-surface border-l border-border">
      {selectionType === 'clip' ? (
        <ClipInspector />
      ) : selectionType === 'bgm' ? (
        <BgmInspector />
      ) : selectionType === 'text' ? (
        <TextOverlayInspector />
      ) : (
        <ProjectInspector onRequestRegenerate={onRequestRegenerate} />
      )}
    </div>
  );
}
