import React from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { SliderRow, NumberRow, InspectorSection } from './controls';
import { Button } from '../../ui';
import { FaSyncAlt, FaMusic } from 'react-icons/fa';

const VOLUME_MIN = 0;
const VOLUME_MAX = 1;
const VOLUME_STEP = 0.05;
const START_STEP = 0.5;
const DEFAULT_VOLUME = 1.0;

/** 將 0~1 數值格式化為百分比字串 */
const toPercent = (v) => `${Math.round((v ?? 0) * 100)}%`;

/** 從 track_id（可能是完整 URL 或檔名）取出可讀檔名 */
function trackLabel(trackId) {
  if (!trackId) return null;
  try {
    return decodeURIComponent(trackId.split('/').pop());
  } catch {
    return trackId;
  }
}

/**
 * BgmInspector：選中配樂軌時的全域配樂設定。
 *
 * 音量 / 起播點為就地編輯（即時預覽）；更換曲目 / 配樂策略屬「重新生成」，
 * 透過 onRequestRegenerate 開啟 RegeneratePanel 處理。
 * @param {() => void} onRequestRegenerate 要求開啟重新生成面板
 */
export default function BgmInspector({ onRequestRegenerate }) {
  const bgm = useBlueprintStore((s) => s.blueprint?.bgm_track);
  const updateBgmField = useBlueprintStore((s) => s.updateBgmField);

  const label = trackLabel(bgm?.track_id);

  return (
    <div className="flex flex-col">
      <div className="px-4 py-3 border-b border-border bg-surface-2/40">
        <h3 className="text-sm font-bold text-ink flex items-center gap-2"><FaMusic className="text-accent" /> 配樂</h3>
        <p className="text-[11px] text-ink-faint mt-0.5 truncate">{label || '目前無配樂'}</p>
      </div>

      {label ? (
        <InspectorSection title="軌道">
          <SliderRow
            label="配樂音量"
            value={bgm.volume ?? DEFAULT_VOLUME}
            min={VOLUME_MIN} max={VOLUME_MAX} step={VOLUME_STEP}
            onChange={(v) => updateBgmField('volume', v)}
            format={toPercent}
          />
          <NumberRow
            label="起播點"
            value={bgm.source_start ?? 0}
            step={START_STEP} min={0}
            onChange={(v) => updateBgmField('source_start', v)}
          />
        </InspectorSection>
      ) : (
        <div className="px-4 py-6 text-center text-xs text-ink-faint">
          這部影片目前沒有配樂。<br />可在「重新生成」中選擇配樂策略或上傳音樂。
        </div>
      )}

      <div className="p-4">
        <Button variant="secondary" size="sm" fullWidth leftIcon={<FaSyncAlt size={11} />} onClick={onRequestRegenerate}>
          變更配樂 / 換一首
        </Button>
        <p className="text-[11px] text-ink-faint mt-2 leading-relaxed">
          更換曲目或配樂策略需要 AI 重新挑選，將透過「重新生成」進行。
        </p>
      </div>
    </div>
  );
}
