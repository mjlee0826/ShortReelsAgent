import React, { useState } from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { SliderRow, NumberRow, InspectorSection, InspectorBackRow } from './controls';
import { Button } from '../../ui';
import ChangeMusicModal from '../ChangeMusicModal';
import { FaExchangeAlt, FaMusic } from 'react-icons/fa';

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
 * 音量 / 起播點為就地編輯（即時預覽）；更換曲目 / 策略走 music-only 換曲
 * （只換配樂、保留時間軸），由 ChangeMusicModal 處理。
 */
export default function BgmInspector() {
  const bgm = useBlueprintStore((s) => s.blueprint?.bgm_track);
  const updateBgmField = useBlueprintStore((s) => s.updateBgmField);
  const clearSelection = useBlueprintStore((s) => s.clearSelection);
  const [showChangeMusic, setShowChangeMusic] = useState(false);

  const label = trackLabel(bgm?.track_id);

  return (
    <div className="flex flex-col">
      {/* 取消選取、回到全域（專案）設定的導線 */}
      <InspectorBackRow onBack={clearSelection} />

      <div className="px-5 py-4 border-b border-border bg-surface-2/40">
        <h3 className="text-base font-bold text-ink flex items-center gap-2"><FaMusic className="text-accent" /> 配樂</h3>
        <p className="text-xs text-ink-faint mt-0.5 truncate">{label || '目前無配樂'}</p>
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
        <div className="px-5 py-6 text-center text-sm text-ink-faint">
          這部影片目前沒有配樂。<br />可在「重新生成」中選擇配樂策略或上傳音樂。
        </div>
      )}

      <div className="p-5">
        <Button variant="secondary" size="md" fullWidth leftIcon={<FaExchangeAlt size={12} />} onClick={() => setShowChangeMusic(true)}>
          變更配樂 / 換一首
        </Button>
        <p className="text-xs text-ink-faint mt-2.5 leading-relaxed">
          只更換配樂、保留時間軸；AI 會重新挑選曲目，套用後可復原。
        </p>
      </div>

      {showChangeMusic && <ChangeMusicModal onClose={() => setShowChangeMusic(false)} />}
    </div>
  );
}
