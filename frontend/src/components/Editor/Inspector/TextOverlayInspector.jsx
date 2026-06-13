import React from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { DEFAULT_OVERLAY } from '../../../utils/textOverlay';
import { IconButton } from '../../ui';
import { FaTrashAlt } from 'react-icons/fa';
import {
  InspectorSection, InspectorBackRow, SliderRow, SelectRow, NumberRow, TextAreaRow,
} from './controls';

// 字幕樣式選項（對應 schema 的 TextOverlay enum 與前端 SUBTITLE_*_MAP；自 ClipInspector 搬來）
const TEXT_SIZE_OPTIONS = [
  { value: 's', label: '小' },
  { value: 'm', label: '中' },
  { value: 'l', label: '大' },
  { value: 'xl', label: '特大' },
];
const TEXT_COLOR_OPTIONS = [
  { value: 'white', label: '白' },
  { value: 'black', label: '黑' },
  { value: 'yellow', label: '黃' },
  { value: 'accent', label: '品牌紫' },
];
const TEXT_OUTLINE_OPTIONS = [
  { value: 'none', label: '無' },
  { value: 'outline', label: '描邊' },
  { value: 'shadow', label: '陰影' },
  { value: 'outline_shadow', label: '描邊+陰影' },
];
const TEXT_BG_OPTIONS = [
  { value: 'none', label: '無' },
  { value: 'solid', label: '實底' },
  { value: 'blur', label: '霧面' },
  { value: 'pill', label: '膠囊' },
];
const TEXT_ANIM_OPTIONS = [
  { value: 'none', label: '無' },
  { value: 'fade', label: '淡入' },
  { value: 'slide_up', label: '上滑' },
  { value: 'pop', label: '彈跳' },
];
// 位置滑桿範圍（0~100；垂直 0=頂 100=底、水平 0=左 100=右）與起訖秒數級距
const POS_MIN = 0;
const POS_MAX = 100;
const POS_STEP = 1;
const TIME_STEP = 0.1;

/**
 * TextOverlayInspector：選中某條字幕時的屬性檢視器（獨立字幕軌）。
 *
 * 編輯文字 / 起訖時間 / 垂直 / 水平 / 五組樣式，即打即預覽（走 updateTextOverlayField）；可刪除該字幕。
 * 字幕為 blueprint.text_overlays 的一條，以 selection.textIndex 定位（獨立於片段）。
 */
export default function TextOverlayInspector() {
  const textIndex = useBlueprintStore((s) => s.selection.textIndex);
  const overlay = useBlueprintStore((s) => s.blueprint?.text_overlays?.[textIndex]);
  const updateTextOverlayField = useBlueprintStore((s) => s.updateTextOverlayField);
  const removeTextOverlay = useBlueprintStore((s) => s.removeTextOverlay);
  const clearSelection = useBlueprintStore((s) => s.clearSelection);

  if (!overlay) return null;

  // 包一層：固定帶入目前字幕索引
  const set = (key, value) => updateTextOverlayField(textIndex, key, value);

  const handleDelete = () => {
    if (window.confirm('確定刪除這條字幕？')) {
      removeTextOverlay(textIndex);
    }
  };

  return (
    <div className="flex flex-col">
      {/* 取消選取、回到全域（專案）設定的導線 */}
      <InspectorBackRow onBack={clearSelection} />

      {/* 標題列 + 刪除 */}
      <div className="px-5 py-4 border-b border-border bg-surface-2/40 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-bold text-ink">字幕</h3>
          <p className="text-xs text-ink-faint mt-0.5 truncate">{overlay.text || '（空白字幕）'}</p>
        </div>
        <IconButton tone="danger" title="刪除字幕" onClick={handleDelete}>
          <FaTrashAlt size={12} />
        </IconButton>
      </div>

      {/* 內容 */}
      <InspectorSection title="內容">
        <TextAreaRow
          label="字幕文字"
          value={overlay.text}
          placeholder="要顯示在畫面上的字幕 / 花字"
          onChange={(v) => set('text', v)}
        />
      </InspectorSection>

      {/* 時間（總時間軸絕對秒數；可跨片段）*/}
      <InspectorSection title="時間">
        <NumberRow label="開始" value={overlay.start_at ?? 0} step={TIME_STEP} min={0} onChange={(v) => set('start_at', v)} />
        <NumberRow label="結束" value={overlay.end_at ?? 0} step={TIME_STEP} min={0} onChange={(v) => set('end_at', v)} />
      </InspectorSection>

      {/* 位置（依主體 bbox 避主體；極端值由渲染端夾進 safe-area）*/}
      <InspectorSection title="位置">
        <SliderRow
          label="垂直位置"
          value={overlay.vertical_position ?? DEFAULT_OVERLAY.vertical_position}
          min={POS_MIN} max={POS_MAX} step={POS_STEP}
          onChange={(v) => set('vertical_position', v)}
          format={(v) => `${Math.round(v ?? DEFAULT_OVERLAY.vertical_position)}%`}
        />
        <SliderRow
          label="水平位置"
          value={overlay.horizontal_position ?? DEFAULT_OVERLAY.horizontal_position}
          min={POS_MIN} max={POS_MAX} step={POS_STEP}
          onChange={(v) => set('horizontal_position', v)}
          format={(v) => `${Math.round(v ?? DEFAULT_OVERLAY.horizontal_position)}%`}
        />
      </InspectorSection>

      {/* 樣式 */}
      <InspectorSection title="樣式">
        <SelectRow label="字級" value={overlay.size || DEFAULT_OVERLAY.size} options={TEXT_SIZE_OPTIONS} onChange={(v) => set('size', v)} />
        <SelectRow label="顏色" value={overlay.color || DEFAULT_OVERLAY.color} options={TEXT_COLOR_OPTIONS} onChange={(v) => set('color', v)} />
        <SelectRow label="描邊" value={overlay.outline || DEFAULT_OVERLAY.outline} options={TEXT_OUTLINE_OPTIONS} onChange={(v) => set('outline', v)} />
        <SelectRow label="底框" value={overlay.background || DEFAULT_OVERLAY.background} options={TEXT_BG_OPTIONS} onChange={(v) => set('background', v)} />
        <SelectRow label="動畫" value={overlay.animation || DEFAULT_OVERLAY.animation} options={TEXT_ANIM_OPTIONS} onChange={(v) => set('animation', v)} />
      </InspectorSection>
    </div>
  );
}
