import React, { useMemo } from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { clipDuration } from '../../../utils/timeline';
import { FaMusic, FaFilm } from 'react-icons/fa';

// 片段方塊在軌道上的最小寬度百分比，確保極短片段仍可點擊
const MIN_BLOCK_PCT = 4;
// 軌道左側標籤欄寬
const LABEL_COL = 'w-16';

/** 從 track_id（URL 或檔名）取出可讀檔名 */
function trackLabel(trackId) {
  if (!trackId) return null;
  try {
    return decodeURIComponent(trackId.split('/').pop());
  } catch {
    return trackId;
  }
}

/**
 * TimelinePanel：底部時間軸（M1 唯讀視覺化）。
 *
 * 影片軌的片段方塊寬度正比於時長，一眼看出節奏；點方塊選取片段、點配樂軌選取配樂。
 * M2 會在此基礎上加入像素↔時間換算、拖拉裁切 / 重排與 playhead。
 */
export default function TimelinePanel() {
  // 直接選 blueprint?.timeline（可能 undefined）以保持 selector 回傳穩定，避免每次 render 產生新陣列
  const timeline = useBlueprintStore((s) => s.blueprint?.timeline);
  const bgm = useBlueprintStore((s) => s.blueprint?.bgm_track);
  const selection = useBlueprintStore((s) => s.selection);
  const select = useBlueprintStore((s) => s.select);
  const seekTo = useBlueprintStore((s) => s.seekTo);

  // 點片段：選取並讓預覽跳轉到該片段在時間軸上的起點
  const handleClipClick = (index, startAt) => {
    select('clip', index);
    seekTo(startAt ?? 0);
  };

  // 各片段時長與總時長（供寬度百分比計算）
  const { durations, total } = useMemo(() => {
    const clips = timeline || [];
    const ds = clips.map(clipDuration);
    return { durations: ds, total: ds.reduce((sum, d) => sum + d, 0) || 1 };
  }, [timeline]);

  const clips = timeline || [];

  const bgmName = trackLabel(bgm?.track_id);

  return (
    <div className="bg-surface border-t border-border px-4 py-3 select-none">
      {/* 影片軌 */}
      <div className="flex items-center gap-2 mb-2">
        <div className={`${LABEL_COL} shrink-0 flex items-center gap-1.5 text-xs text-ink-faint`}>
          <FaFilm size={11} /> 影片
        </div>
        <div className="flex-1 flex gap-[2px] h-14">
          {clips.length === 0 && (
            <div className="flex-1 flex items-center justify-center text-xs text-ink-faint border border-dashed border-border rounded-lg">
              尚無片段
            </div>
          )}
          {clips.map((clip, index) => {
            const widthPct = Math.max(MIN_BLOCK_PCT, (durations[index] / total) * 100);
            const isSelected = selection.type === 'clip' && selection.clipIndex === index;
            const hasTransition = clip.transition_in && clip.transition_in !== 'none';
            return (
              <button
                key={`${clip.clip_id}-${index}`}
                type="button"
                onClick={() => handleClipClick(index, clip.start_at)}
                style={{ width: `${widthPct}%` }}
                title={`片段 ${index + 1}｜${clip.clip_id}｜${durations[index].toFixed(2)}s`}
                className={`relative h-full rounded-lg border text-left px-2 py-1 overflow-hidden transition-colors ${
                  isSelected
                    ? 'bg-accent/25 border-accent ring-1 ring-accent'
                    : 'bg-surface-2 border-border hover:border-border-strong'
                }`}
              >
                {/* 轉場標記：左緣豎條 */}
                {hasTransition && <span className="absolute left-0 top-0 bottom-0 w-1 bg-accent/70" />}
                <span className="text-[11px] font-bold text-ink">{index + 1}</span>
                {clip.overlay_text && (
                  <span className="block text-[10px] text-ink-faint truncate">💬 {clip.overlay_text}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 配樂軌 */}
      <div className="flex items-center gap-2">
        <div className={`${LABEL_COL} shrink-0 flex items-center gap-1.5 text-xs text-ink-faint`}>
          <FaMusic size={11} /> 配樂
        </div>
        <button
          type="button"
          onClick={() => select('bgm')}
          title={bgmName || '無配樂'}
          className={`flex-1 h-8 rounded-lg border text-left px-2.5 flex items-center transition-colors ${
            selection.type === 'bgm'
              ? 'bg-accent/25 border-accent ring-1 ring-accent'
              : bgmName
                ? 'bg-success/10 border-success/30 hover:border-success/60'
                : 'bg-surface-2 border-dashed border-border hover:border-border-strong'
          }`}
        >
          <span className={`text-[11px] truncate ${bgmName ? 'text-success' : 'text-ink-faint'}`}>
            {bgmName ? `🎵 ${bgmName}` : '無配樂'}
          </span>
        </button>
      </div>
    </div>
  );
}
