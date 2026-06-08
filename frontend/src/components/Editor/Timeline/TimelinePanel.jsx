import React, { useState, useRef, useMemo, useEffect } from 'react';
import useBlueprintStore from '../../../store/useBlueprintStore';
import { clipDuration, MIN_CLIP_DURATION } from '../../../utils/timeline';
import ClipBlock from './ClipBlock';
import Playhead from './Playhead';
import { FaMusic, FaFilm, FaSearchMinus, FaSearchPlus } from 'react-icons/fa';

// 縮放：每秒像素的預設 / 範圍 / 級距（具名常數，禁 magic number）
const DEFAULT_PX_PER_SEC = 80;
const MIN_PX_PER_SEC = 20;
const MAX_PX_PER_SEC = 240;
const ZOOM_STEP = 20;

// 點擊與拖拉的判定門檻（px）；超過才視為拖拉，否則視為點選
const DRAG_THRESHOLD_PX = 4;

// 軌道高度
const RULER_H = 22;
const VIDEO_TRACK_H = 56;
const BGM_TRACK_H = 30;
const LABEL_COL = 'w-14';

// 刻度尺：每格目標像素，據此挑「漂亮」的時間間隔
const RULER_TARGET_PX = 70;
const RULER_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];

// 圖片素材（無來源時間窗，裁切時只改時長、不動 source_start/end）
const IMAGE_RE = /\.(jpg|jpeg|png|heic|heif)$/i;

/** 依目前縮放挑選一格的「漂亮」秒數間隔 */
function niceInterval(pxPerSecond) {
  for (const step of RULER_STEPS) {
    if (step * pxPerSecond >= RULER_TARGET_PX) return step;
  }
  return RULER_STEPS[RULER_STEPS.length - 1];
}

/** 秒數格式化為刻度標籤（>=60 顯示 m:ss，否則顯示秒）*/
function formatTick(sec) {
  if (sec >= 60) {
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }
  return `${+sec.toFixed(1)}s`;
}

/** 從 track_id（URL 或檔名）取出可讀檔名 */
function trackLabel(trackId) {
  if (!trackId) return null;
  try {
    return decodeURIComponent(trackId.split('/').pop());
  } catch {
    return trackId;
  }
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/**
 * TimelinePanel：底部時間軸（M2 可操作版）。
 *
 * 像素↔時間座標系 + 縮放 + 刻度尺 + 播放頭；片段可拖邊裁切、拖拉重排（皆 ripple 接合），
 * 點刻度尺可連續 scrub。拖拽邏輯集中於此（document 監聽 + ref 狀態），ClipBlock / Playhead 為呈現層。
 */
export default function TimelinePanel() {
  const timeline = useBlueprintStore((s) => s.blueprint?.timeline);
  const bgm = useBlueprintStore((s) => s.blueprint?.bgm_track);
  const selection = useBlueprintStore((s) => s.selection);
  const select = useBlueprintStore((s) => s.select);
  const seekTo = useBlueprintStore((s) => s.seekTo);

  const [pxPerSecond, setPxPerSecond] = useState(DEFAULT_PX_PER_SEC);
  const [draggingIndex, setDraggingIndex] = useState(null);
  const [dragOverIndex, setDragOverIndex] = useState(null);

  // 拖拽狀態與工具用 ref（避免 document 監聽閉包抓到舊值）
  const dragRef = useRef(null);
  const lastXRef = useRef(0);
  const rafRef = useRef(null);
  const contentRef = useRef(null);
  const pxRef = useRef(pxPerSecond);
  // 同步最新縮放給 document 監聽閉包使用（避免於 render 期間寫 ref）
  useEffect(() => { pxRef.current = pxPerSecond; }, [pxPerSecond]);

  const clips = timeline || [];

  const { durations, total } = useMemo(() => {
    const ds = (timeline || []).map(clipDuration);
    return { durations: ds, total: ds.reduce((sum, d) => sum + d, 0) };
  }, [timeline]);

  const contentWidth = total * pxPerSecond;
  const bgmName = trackLabel(bgm?.track_id);

  // ── 片段方塊：起始事件（實際運算在 document 監聽）──────────────────────────────

  const handleEdgeDown = (index, edge, e) => {
    const clip = clips[index];
    if (!clip) return;
    const dur = clipDuration(clip);
    const pr = clip.playback_rate || 1;
    const ss = clip.source_start ?? 0;
    const se = clip.source_end ?? (ss + dur * pr);
    dragRef.current = {
      mode: 'trim', index, edge, startX: e.clientX, committed: false,
      origDuration: dur, origSourceStart: ss, origSourceEnd: se,
      isImage: IMAGE_RE.test(clip.clip_id), pr,
    };
    document.body.style.cursor = 'ew-resize';
    e.preventDefault();
  };

  const handleBodyDown = (index, e) => {
    dragRef.current = { mode: 'reorder', index, startX: e.clientX, moved: false, insertion: null };
    e.preventDefault();
  };

  // ── 刻度尺點擊 → 連續 seek ───────────────────────────────────────────────────

  const handleRulerClick = (e) => {
    const rect = contentRef.current?.getBoundingClientRect();
    if (!rect) return;
    const seconds = clamp((e.clientX - rect.left) / pxPerSecond, 0, total);
    seekTo(seconds);
  };

  // ── document 拖拽監聽（掛載一次；以 ref + getState 讀最新值，避免 stale closure）──

  useEffect(() => {
    const processMove = () => {
      rafRef.current = null;
      const d = dragRef.current;
      if (!d) return;
      const x = lastXRef.current;
      const px = pxRef.current;
      const store = useBlueprintStore.getState();

      if (d.mode === 'trim') {
        if (!d.committed) { store.commitSnapshot(); d.committed = true; } // 整段拖拽只記一次 Undo
        const deltaSec = (x - d.startX) / px;
        if (d.edge === 'right') {
          if (d.isImage) {
            store.trimClipTransient(d.index, { duration: Math.max(MIN_CLIP_DURATION, d.origDuration + deltaSec) });
          } else {
            const newSE = Math.max(d.origSourceStart + MIN_CLIP_DURATION * d.pr, d.origSourceEnd + deltaSec * d.pr);
            store.trimClipTransient(d.index, {
              duration: (newSE - d.origSourceStart) / d.pr, sourceStart: d.origSourceStart, sourceEnd: newSE,
            });
          }
        } else { // left
          if (d.isImage) {
            store.trimClipTransient(d.index, { duration: Math.max(MIN_CLIP_DURATION, d.origDuration - deltaSec) });
          } else {
            const newSS = clamp(d.origSourceStart + deltaSec * d.pr, 0, d.origSourceEnd - MIN_CLIP_DURATION * d.pr);
            store.trimClipTransient(d.index, {
              duration: (d.origSourceEnd - newSS) / d.pr, sourceStart: newSS, sourceEnd: d.origSourceEnd,
            });
          }
        }
      } else if (d.mode === 'reorder') {
        if (!d.moved && Math.abs(x - d.startX) < DRAG_THRESHOLD_PX) return;
        if (!d.moved) { d.moved = true; setDraggingIndex(d.index); document.body.style.cursor = 'grabbing'; }
        const durs = (store.blueprint?.timeline || []).map(clipDuration);
        const rect = contentRef.current?.getBoundingClientRect();
        if (!rect) return;
        const cursorSec = (x - rect.left) / px;
        let acc = 0;
        let insertion = durs.length;
        for (let i = 0; i < durs.length; i++) {
          if (cursorSec < acc + durs[i] / 2) { insertion = i; break; }
          acc += durs[i];
        }
        d.insertion = insertion;
        setDragOverIndex(insertion);
      }
    };

    const onMove = (e) => {
      if (!dragRef.current) return;
      lastXRef.current = e.clientX;
      if (!rafRef.current) rafRef.current = requestAnimationFrame(processMove);
    };

    const onUp = () => {
      const d = dragRef.current;
      if (d && d.mode === 'reorder') {
        const store = useBlueprintStore.getState();
        const len = store.blueprint?.timeline?.length ?? 0;
        if (d.moved && d.insertion != null) {
          let to = d.insertion > d.index ? d.insertion - 1 : d.insertion;
          to = clamp(to, 0, len - 1);
          if (to !== d.index) store.reorderClips(d.index, to);
          else store.select('clip', d.index);
        } else {
          // 未超過門檻 → 視為點選：選取並 seek 到片段起點
          const clip = store.blueprint?.timeline?.[d.index];
          store.select('clip', d.index);
          store.seekTo(clip?.start_at ?? 0);
        }
      }
      dragRef.current = null;
      setDraggingIndex(null);
      setDragOverIndex(null);
      document.body.style.cursor = '';
      if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
  }, []);

  // ── 刻度尺資料 ───────────────────────────────────────────────────────────────

  const ticks = useMemo(() => {
    if (total <= 0) return [];
    const interval = niceInterval(pxPerSecond);
    const result = [];
    for (let t = 0; t <= total + 1e-6; t += interval) {
      result.push({ sec: t, x: t * pxPerSecond });
    }
    return result;
  }, [total, pxPerSecond]);

  // 重排時插入指示線的 X 位置（累加到 dragOverIndex 之前的時長）
  const insertionX = useMemo(() => {
    if (draggingIndex == null || dragOverIndex == null) return null;
    return durations.slice(0, dragOverIndex).reduce((sum, d) => sum + d, 0) * pxPerSecond;
  }, [draggingIndex, dragOverIndex, durations, pxPerSecond]);

  return (
    <div className="bg-surface border-t border-border select-none">
      {/* 標題 + 縮放控制 */}
      <div className="flex items-center justify-between px-4 py-1.5 border-b border-border/60">
        <span className="text-xs text-ink-faint">時間軸</span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setPxPerSecond((v) => Math.max(MIN_PX_PER_SEC, v - ZOOM_STEP))}
            className="text-ink-faint hover:text-ink transition-colors disabled:opacity-30"
            disabled={pxPerSecond <= MIN_PX_PER_SEC}
            title="縮小"
          >
            <FaSearchMinus size={12} />
          </button>
          <button
            type="button"
            onClick={() => setPxPerSecond((v) => Math.min(MAX_PX_PER_SEC, v + ZOOM_STEP))}
            className="text-ink-faint hover:text-ink transition-colors disabled:opacity-30"
            disabled={pxPerSecond >= MAX_PX_PER_SEC}
            title="放大"
          >
            <FaSearchPlus size={12} />
          </button>
        </div>
      </div>

      <div className="flex">
        {/* 左側固定標籤欄 */}
        <div className={`${LABEL_COL} shrink-0 border-r border-border`}>
          <div style={{ height: RULER_H }} />
          <div style={{ height: VIDEO_TRACK_H }} className="flex items-center gap-1.5 px-2 text-xs text-ink-faint">
            <FaFilm size={11} /> 影片
          </div>
          <div style={{ height: BGM_TRACK_H }} className="flex items-center gap-1.5 px-2 text-xs text-ink-faint">
            <FaMusic size={11} /> 配樂
          </div>
        </div>

        {/* 右側可橫向捲動的軌道區 */}
        <div className="flex-1 overflow-x-auto">
          {clips.length === 0 ? (
            <div className="h-[80px] flex items-center justify-center text-xs text-ink-faint">尚無片段</div>
          ) : (
            <div ref={contentRef} className="relative" style={{ width: `${contentWidth}px`, minWidth: '100%' }}>
              {/* 刻度尺（可點擊 seek）*/}
              <div
                onClick={handleRulerClick}
                style={{ height: RULER_H }}
                className="relative border-b border-border/60 cursor-pointer"
              >
                {ticks.map((tick) => (
                  <div key={tick.sec} className="absolute top-0 bottom-0 flex items-end" style={{ left: `${tick.x}px` }}>
                    <span className="absolute top-0 left-0 w-px h-1.5 bg-border-strong" />
                    <span className="text-[9px] text-ink-faint pl-1 leading-none pb-0.5">{formatTick(tick.sec)}</span>
                  </div>
                ))}
              </div>

              {/* 軌道區（影片 + 配樂 + 播放頭 + 重排插入線）*/}
              <div className="relative">
                {/* 影片軌 */}
                <div style={{ height: VIDEO_TRACK_H }} className="flex">
                  {clips.map((clip, index) => (
                    <ClipBlock
                      key={`${clip.clip_id}-${index}`}
                      clip={clip}
                      index={index}
                      widthPx={durations[index] * pxPerSecond}
                      isSelected={selection.type === 'clip' && selection.clipIndex === index}
                      isDragging={draggingIndex === index}
                      onEdgeDown={handleEdgeDown}
                      onBodyDown={handleBodyDown}
                    />
                  ))}
                </div>

                {/* 配樂軌 */}
                <button
                  type="button"
                  onClick={() => select('bgm')}
                  title={bgmName || '無配樂'}
                  style={{ height: BGM_TRACK_H, width: `${contentWidth}px` }}
                  className={`text-left px-2.5 flex items-center transition-colors border-t border-border/60 ${
                    selection.type === 'bgm'
                      ? 'bg-accent/25 ring-1 ring-accent ring-inset'
                      : bgmName ? 'bg-success/10 hover:bg-success/20' : 'bg-surface-2'
                  }`}
                >
                  <span className={`text-[11px] truncate ${bgmName ? 'text-success' : 'text-ink-faint'}`}>
                    {bgmName ? `🎵 ${bgmName}` : '無配樂'}
                  </span>
                </button>

                {/* 重排插入指示線 */}
                {insertionX != null && (
                  <div className="absolute top-0 bottom-0 w-0.5 bg-accent z-20 pointer-events-none" style={{ left: `${insertionX}px` }} />
                )}

                {/* 播放頭（獨立訂閱，逐幀只重繪這條線）*/}
                <Playhead pxPerSecond={pxPerSecond} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
