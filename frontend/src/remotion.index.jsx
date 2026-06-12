import React from 'react';
import { Composition, registerRoot } from 'remotion';
// 引入我們寫好的時間軸核心
import MainTimeline from './components/RemotionPlayer/MainTimeline';
import { computeVideoMetadata } from './utils/timeline';
import './index.css'; // 如果影片中有用到 Tailwind CSS 樣式，記得引入（index.css 與本檔同在 src/ 底下，用 ./）

// Composition 的靜態預設規格；實際時長 / 幀率一律由 calculateMetadata 依注入的 props 覆寫。
// Remotion 規定 Composition 必填這兩個欄位，故此處保留與預覽相同的安全回退值。
const DEFAULT_DURATION_FRAMES = 150;
const DEFAULT_FPS = 30;

export const RemotionRoot = () => {
    return (
        <>
        {/* 這裡註冊的 id="MainVideo"，就是 Python Adapter 呼叫時要尋找的目標。
            當後端執行 npx remotion render 時，
            會自動把 props.json 裡面的資料塞進這個畫布的 props 裡。
        */}
        <Composition
            id="MainVideo"
            component={MainTimeline}
            durationInFrames={DEFAULT_DURATION_FRAMES} // 靜態回退值；下方 calculateMetadata 會依 props 覆寫
            fps={DEFAULT_FPS}                          // 同上，實際幀率取自 blueprint.global_settings
            width={1080}
            height={1920}
            defaultProps={{
            blueprint: null,
            assetsRootUrl: ''
            }}
            // 關鍵修正：從注入的 props.blueprint 推導真實時長 / 幀率（與預覽共用同一計算），
            // 否則 SSR 算圖會永遠停在靜態預設的 150 幀 / 30fps（成品被鎖死成 5 秒並截斷）。
            calculateMetadata={({ props }) => computeVideoMetadata(props.blueprint)}
        />
        </>
    );
};

// 將這支檔案註冊為 Remotion 的渲染根節點
registerRoot(RemotionRoot);