import React from 'react';
import { Sequence, AbsoluteFill, useVideoConfig, Audio } from 'remotion';
import ClipComponent from './ClipComponent';
import TextOverlayLayer from './TextOverlayLayer';
import { TRANSITION_FRAMES, ADJACENCY_THRESHOLD_SECONDS, PREMOUNT_LEAD_SECONDS } from './constants';
import { thinBeatFrames } from '../../utils/motion';
import { resolveBgmUrl } from '../../utils/assetUrl';
import { resolveTimelineTextOverlays } from '../../utils/textOverlay';

export default function MainTimeline({ blueprint, assetsRootUrl }) {
  const { fps } = useVideoConfig();

  if (!blueprint || !blueprint.timeline) return null;

  const getDynamicBgmVolume = (frame) => {
    const currentClip = blueprint.timeline.find((c) => {
      const startFrame = Math.round(c.start_at * fps);
      const endFrame = Math.round(c.end_at * fps);
      return frame >= startFrame && frame <= endFrame;
    });
    const baseVol = blueprint.bgm_track?.volume ?? 1.0;
    const duckingWeight = currentClip?.bgm_volume ?? 1.0;
    return baseVol * duckingWeight;
  };

  // 背景音樂來源網址：走共用 util 解析（http 直通 / 否則同資料夾檔名），與預抓共用同一邏輯
  const getBgmSrc = () => resolveBgmUrl(assetsRootUrl, blueprint.bgm_track?.track_id);

  // 【自動運鏡】總開關（舊藍圖無此欄位 → 視為關閉，不改變既有專案行為）+ 節拍時間映射（一次算好）。
  // 音檔 beat 秒 → 影片時間軸秒：影片時間 = bgm 起播秒 +（beat 秒 − 擷取起點秒）。
  const autoMotion = blueprint.global_settings?.auto_motion ?? false;
  // 【卡點 Punch】獨立子開關（編輯器即時可切）：舊藍圖無此欄位 → 預設 true，維持「運鏡開即有卡點」的既有行為。
  // 關閉時不映射任何節拍 → 各片段 beatsInClipFrames 為空 → punch 自動退化為 0，但 base Ken Burns 運鏡不受影響。
  const autoPunch = blueprint.global_settings?.auto_punch ?? true;
  const bgm = blueprint.bgm_track;
  const beatVideoTimes = (autoMotion && autoPunch && Array.isArray(bgm?.beats))
    ? bgm.beats.map((t) => (bgm.start_at || 0) + (t - (bgm.source_start || 0)))
    : [];

  // 交界預掛載幀數：提前掛載下一段，使其 <video> 先 seek/decode 就緒，消除切片瞬間的卡頓。
  // （第一段 from=0 無法再往前提前，故首段仍依賴 pauseWhenBuffering 兜底。）
  const premountFrames = Math.round(fps * PREMOUNT_LEAD_SECONDS);

  return (
    <AbsoluteFill style={{ backgroundColor: 'black' }}>
      
      {/* --- 全局背景音樂 --- */}
      {blueprint.bgm_track && blueprint.bgm_track.track_id && (
        <Audio
          src={getBgmSrc()}
          startFrom={Math.round((blueprint.bgm_track.source_start || 0) * fps)}
          volume={getDynamicBgmVolume}
          pauseWhenBuffering
        />
      )}

      {/* --- 影片序列排版 --- */}
      {blueprint.timeline.map((clip, index) => {
        // 以「邊界幀差」算長度：fromFrame 取自 start_at、toFrame 取自 end_at，各自 round 後相減。
        // 因時間軸已 repack（end_at[i] === start_at[i+1]），相鄰片段必共用同一邊界幀，
        // 故首尾嚴格相接、零黑縫零重疊；若改用 round(end-start) 則兩端獨立進位會差 ±1 幀 → 黑幀閃爍（亂跳主因之一）
        const fromFrame = Math.round(clip.start_at * fps);
        const toFrame = Math.round(clip.end_at * fps);
        const durationInFrames = toFrame - fromFrame;

        // 落在此片段內的重拍 → 換算成相對片段起點的幀，供卡點 punch（無節拍則為空陣列、自動退化）。
        // 再抽稀至最小間隔，避免每拍都彈造成「持續抖動」（每拍 punch 是先前振動 bug 的主因）。
        const beatsInClipFrames = thinBeatFrames(
          beatVideoTimes
            .filter((vt) => vt >= clip.start_at && vt < clip.end_at)
            .map((vt) => Math.round((vt - clip.start_at) * fps)),
          fps,
        );

        const nextClip = index < blueprint.timeline.length - 1 ? blueprint.timeline[index + 1] : null;
        // 只在相鄰片段（間距小於門檻）且下一段有轉場時才延伸，讓交叉淡入有重疊；非相鄰不延伸以免殘影
        const isAdjacent = nextClip && Math.abs((nextClip.start_at ?? 0) - (clip.end_at ?? 0)) < ADJACENCY_THRESHOLD_SECONDS;
        const hasNextTransition = isAdjacent && nextClip.transition_in && nextClip.transition_in !== 'none';
        const renderDuration = hasNextTransition ? durationInFrames + TRANSITION_FRAMES : durationInFrames;

        if (renderDuration <= 0) return null;

        return (
          <Sequence key={`${clip.clip_id}-${index}`} from={fromFrame} durationInFrames={renderDuration} premountFor={premountFrames}>
            <ClipComponent
              clipData={clip}
              assetsRootUrl={assetsRootUrl}
              autoMotion={autoMotion}
              clipIndex={index}
              beatsInClipFrames={beatsInClipFrames}
              durationInFrames={durationInFrames}
            />
          </Sequence>
        );
      })}

      {/* --- 獨立字幕軌（與片段解耦）--- */}
      {/* 每條字幕包成自己的 <Sequence>：跨片段持續顯示不在切點閃爍、同框重疊者並存（Remotion 原生疊放）。 */}
      {/* resolveTimelineTextOverlays 容錯：新藍圖讀 text_overlays，legacy / SSR 未遷移則回退 per-clip。 */}
      {resolveTimelineTextOverlays(blueprint).map((ov, i) => {
        const from = Math.round((ov.start_at ?? 0) * fps);
        const dur = Math.round((ov.end_at ?? 0) * fps) - from;
        if (dur <= 0) return null;
        return (
          <Sequence key={`text-${i}`} from={from} durationInFrames={dur}>
            <TextOverlayLayer overlay={ov} durationInFrames={dur} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
}