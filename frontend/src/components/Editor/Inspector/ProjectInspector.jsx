import React from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { InspectorSection, ReadonlyRow } from './controls';
import { Button } from '../../ui';
import { FaSyncAlt, FaCog } from 'react-icons/fa';

// 輸出規格（與 VideoPlayer 的 composition 尺寸一致，固定值）
const OUTPUT_RESOLUTION = '1080 × 1920';
const DEFAULT_FPS = 30;
const DEFAULT_ASPECT = '9:16';

/**
 * ProjectInspector：未選取特定物件時的全域 / 輸出設定（檢視器預設面板）。
 *
 * fps / 比例 / 解析度為衍生值，唯讀顯示（D5 / 後端 #2）；
 * 字幕·濾鏡總開關與配樂策略屬「重新生成」，集中於 RegeneratePanel。
 * @param {() => void} onRequestRegenerate 要求開啟重新生成面板
 */
export default function ProjectInspector({ onRequestRegenerate }) {
  const global = useBlueprintStore((s) => s.blueprint?.global_settings);

  return (
    <div className="flex flex-col">
      <div className="px-4 py-3 border-b border-border bg-surface-2/40">
        <h3 className="text-sm font-bold text-ink flex items-center gap-2"><FaCog className="text-accent" /> 專案 / 輸出</h3>
        <p className="text-[11px] text-ink-faint mt-0.5">點選時間軸上的片段或配樂軌可編輯細項</p>
      </div>

      <InspectorSection title="輸出規格">
        <ReadonlyRow label="解析度" value={OUTPUT_RESOLUTION} locked />
        <ReadonlyRow label="FPS" value={global?.fps ?? DEFAULT_FPS} locked />
        <ReadonlyRow label="比例" value={global?.aspect_ratio || DEFAULT_ASPECT} locked />
      </InspectorSection>

      <div className="p-4">
        <Button variant="secondary" size="sm" fullWidth leftIcon={<FaSyncAlt size={11} />} onClick={onRequestRegenerate}>
          重新生成 / 變更設定
        </Button>
        <p className="text-[11px] text-ink-faint mt-2 leading-relaxed">
          字幕 / 濾鏡總開關、配樂策略與導演指令的變更需 AI 重新生成。
        </p>
      </div>
    </div>
  );
}
