import React from 'react';
import { Video, Img, useVideoConfig } from 'remotion';

/**
 * ClipComponent: 負責渲染單一影片或圖片片段
 * 接收從 MainTimeline 傳來的一段 JSON 資料與素材根目錄
 */
export default function ClipComponent({ clipData, assetsRootUrl }) {
  const { fps } = useVideoConfig();

  // 1. 組合絕對路徑 (例如: http://localhost:8000/static/snowman/IMG_0279.MOV)
  // 若 clip_id 本身帶有資料夾路徑，可依據後端結構做 replace 處理。
  // 這裡假設 clipData.clip_id 就是檔名。
  const fileName = clipData.clip_id.split('/').pop(); 
  const fileUrl = `${assetsRootUrl}${fileName}`;

  // 2. 判斷是否為靜態圖片 (根據副檔名)
  const isImage = /\.(jpg|jpeg|png|heic)$/i.test(fileName);

  // 3. 處理 CSS 樣式 (空間裁切、變焦、濾鏡)
  const dynamicStyle = {
    width: '100%',
    height: '100%',
    objectFit: 'cover', // 確保畫面填滿 9:16
    objectPosition: clipData.object_position || '50% 50%',
    transform: `scale(${clipData.scale || 1.0})`,
    filter: clipData.filter && clipData.filter !== 'none' ? clipData.filter : 'none',
  };

  // 4. 渲染靜態圖片
  if (isImage) {
    return <Img src={fileUrl} style={dynamicStyle} />;
  }

  // 5. 渲染動態影片 (處理時間裁切與變速)
  // 將大腦給的 "秒數" 乘上 "fps" 轉換為 Remotion 的 "影格數"
  const startFromFrame = Math.round((clipData.source_start || 0) * fps);
  const endAtFrame = clipData.source_end ? Math.round(clipData.source_end * fps) : undefined;

  return (
    <Video
      src={fileUrl}
      startFrom={startFromFrame}
      endAt={endAtFrame}
      playbackRate={clipData.playback_rate || 1.0}
      volume={clipData.clip_volume ?? 1.0}
      style={dynamicStyle}
    />
  );
}