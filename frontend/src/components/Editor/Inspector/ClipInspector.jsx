import React from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { clipDuration } from '../../../utils/timeline';
import { IconButton } from '../../ui';
import { FaArrowLeft, FaArrowRight, FaTrashAlt } from 'react-icons/fa';
import {
  InspectorSection, InspectorBackRow, SliderRow, SelectRow, NumberRow, ReadonlyRow,
} from './controls';
import COLOR from '../../../config/colorPresets.json';

// 調色 preset 下拉 + 進階 primitive 滑桿皆由 SSOT colorPresets.json 動態產生
// （與 renderer utils/color.js、後端 schema 同源；新增一個 look 只需改 JSON，此處自動跟上）。
const PRESET_OPTIONS = Object.entries(COLOR.presetLabels).map(([value, label]) => ({ value, label }));
const COLOR_PRIMITIVES = COLOR.primitives;

// 轉場選項（對應 schema 與 ClipComponent）
const TRANSITION_OPTIONS = [
  { value: 'none', label: '無' },
  { value: 'fade', label: '淡入' },
  { value: 'slide', label: '滑入' },
];
// 運鏡選項（對應 utils/motion.js 的 preset；auto＝交給系統依素材 / 節拍自動決定）
// 僅在「啟用自動運鏡」總開關開啟時生效（關閉時整支無運鏡）
const MOTION_OPTIONS = [
  { value: 'auto', label: '自動' },
  { value: 'none', label: '無' },
  { value: 'push_in', label: '推近' },
  { value: 'pull_out', label: '拉遠' },
  { value: 'pan', label: '平移' },
  { value: 'punch', label: '卡點' },
];
// 控制項數值範圍（具名常數，禁 magic number）
const SCALE_MIN = 1.0;
const SCALE_MAX = 2.0;
const SCALE_STEP = 0.05;
const VOLUME_MIN = 0;
const VOLUME_MAX = 1;
const VOLUME_STEP = 0.05;
const TRIM_STEP = 0.1;

// 各欄位預設值（與 ClipComponent 的 fallback 對齊）
const DEFAULT_SCALE = 1.0;
const DEFAULT_VOLUME = 1.0;

/** 將 0~1 數值格式化為百分比字串 */
const toPercent = (v) => `${Math.round((v ?? 0) * 100)}%`;

/**
 * ClipInspector：選中片段時的逐段屬性檢視器（設計文件 §5 五組）。
 *
 * 來源 / 畫面 / 字幕 / 音訊 為就地編輯，即打即預覽；
 * 進階（pip_video）與 playback_rate、object_position 第一版唯讀（D5）；reason 唯讀。
 */
export default function ClipInspector() {
  const clipIndex = useBlueprintStore((s) => s.selection.clipIndex);
  const clip = useBlueprintStore((s) => s.blueprint?.timeline?.[clipIndex]);
  const clipCount = useBlueprintStore((s) => s.blueprint?.timeline?.length ?? 0);
  const updateClipField = useBlueprintStore((s) => s.updateClipField);
  const updateClipColorField = useBlueprintStore((s) => s.updateClipColorField);
  const reorderClips = useBlueprintStore((s) => s.reorderClips);
  const removeClip = useBlueprintStore((s) => s.removeClip);
  const clearSelection = useBlueprintStore((s) => s.clearSelection);

  if (!clip) return null;

  // 包一層：固定帶入目前片段索引
  const set = (key, value) => updateClipField(clipIndex, key, value);
  // 調色就地編輯：寫進 clip.color 巢狀物件（preset 切換或個別 primitive 覆寫）
  const setColor = (key, value) => updateClipColorField(clipIndex, key, value);
  // 某 primitive 目前生效值：片段覆寫 > 所選 preset 帶的值 > primitive 預設（供進階滑桿顯示）
  const effectiveColor = (key) => {
    const override = clip.color?.[key];
    if (override != null) return override;
    const presetVal = COLOR.presets[clip.color?.preset]?.[key];
    return presetVal != null ? presetVal : COLOR_PRIMITIVES[key].default;
  };

  const pip = clip.pip_video;
  const pipSummary = pip?.clip_id ? `${pip.clip_id}（${pip.position || 'top_right'}）` : '無';

  // 刪除前確認，避免誤刪
  const handleDelete = () => {
    if (window.confirm(`確定刪除片段 ${clipIndex + 1}？後續片段會自動往前接合。`)) {
      removeClip(clipIndex);
    }
  };

  return (
    <div className="flex flex-col">
      {/* 取消選取、回到全域（專案）設定的導線 */}
      <InspectorBackRow onBack={clearSelection} />

      {/* 標題列 + 結構操作（重排 / 刪除，皆 ripple 接合）*/}
      <div className="px-5 py-4 border-b border-border bg-surface-2/40 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-bold text-ink">片段 {clipIndex + 1}</h3>
          <p className="text-xs text-ink-faint mt-0.5">時長 {clipDuration(clip).toFixed(2)}s</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <IconButton
            tone="neutral"
            title="往前移"
            disabled={clipIndex <= 0}
            onClick={() => reorderClips(clipIndex, clipIndex - 1)}
          >
            <FaArrowLeft size={12} />
          </IconButton>
          <IconButton
            tone="neutral"
            title="往後移"
            disabled={clipIndex >= clipCount - 1}
            onClick={() => reorderClips(clipIndex, clipIndex + 1)}
          >
            <FaArrowRight size={12} />
          </IconButton>
          <IconButton tone="danger" title="刪除片段" onClick={handleDelete}>
            <FaTrashAlt size={12} />
          </IconButton>
        </div>
      </div>

      {/* 來源 */}
      <InspectorSection title="來源">
        <ReadonlyRow label="素材" value={clip.clip_id} locked />
        <NumberRow label="裁切起點" value={clip.source_start ?? 0} step={TRIM_STEP} min={0} onChange={(v) => set('source_start', v)} />
        <NumberRow label="裁切終點" value={clip.source_end ?? 0} step={TRIM_STEP} min={0} onChange={(v) => set('source_end', v)} />
        <ReadonlyRow label="變速" value={`${clip.playback_rate ?? 1.0}x`} locked />
      </InspectorSection>

      {/* 畫面 */}
      <InspectorSection title="畫面">
        <SliderRow
          label="縮放"
          value={clip.scale ?? DEFAULT_SCALE}
          min={SCALE_MIN} max={SCALE_MAX} step={SCALE_STEP}
          onChange={(v) => set('scale', v)}
          format={(v) => `${(v ?? DEFAULT_SCALE).toFixed(2)}x`}
        />
        <ReadonlyRow label="定位" value={clip.object_position || '50% 50%'} locked />
        <SelectRow label="調色" value={clip.color?.preset || 'none'} options={PRESET_OPTIONS} onChange={(v) => setColor('preset', v)} />
        <SelectRow label="轉場" value={clip.transition_in || 'none'} options={TRANSITION_OPTIONS} onChange={(v) => set('transition_in', v)} />
        <SelectRow label="運鏡" value={clip.motion || 'auto'} options={MOTION_OPTIONS} onChange={(v) => set('motion', v)} />
      </InspectorSection>

      {/* 進階調色：在 preset 之上逐顆 primitive 微調（對應 P3，人類可細修）；滑桿顯示目前生效值，一拖即成覆寫 */}
      <InspectorSection title="進階調色" collapsible defaultOpen={false}>
        {Object.entries(COLOR_PRIMITIVES).map(([key, meta]) => (
          <SliderRow
            key={key}
            label={meta.label}
            value={effectiveColor(key)}
            min={meta.min} max={meta.max} step={meta.step}
            onChange={(v) => setColor(key, v)}
            format={(v) => `${+Number(v ?? meta.default).toFixed(2)}${meta.unit}`}
          />
        ))}
      </InspectorSection>

      {/* 音訊 */}
      <InspectorSection title="音訊">
        <SliderRow
          label="原音音量"
          value={clip.clip_volume ?? DEFAULT_VOLUME}
          min={VOLUME_MIN} max={VOLUME_MAX} step={VOLUME_STEP}
          onChange={(v) => set('clip_volume', v)}
          format={toPercent}
        />
        <SliderRow
          label="配樂避讓"
          value={clip.bgm_volume ?? DEFAULT_VOLUME}
          min={VOLUME_MIN} max={VOLUME_MAX} step={VOLUME_STEP}
          onChange={(v) => set('bgm_volume', v)}
          format={toPercent}
        />
      </InspectorSection>

      {/* 進階（第一版唯讀）*/}
      <InspectorSection title="進階" collapsible defaultOpen={false}>
        <ReadonlyRow label="畫中畫 (PiP)" value={pipSummary} locked />
      </InspectorSection>

      {/* AI 決策說明 */}
      {clip.reason && (
        <InspectorSection title="🤖 AI 決策說明" collapsible defaultOpen={false}>
          <p className="text-sm text-ink-muted leading-relaxed whitespace-pre-wrap">{clip.reason}</p>
        </InspectorSection>
      )}
    </div>
  );
}
