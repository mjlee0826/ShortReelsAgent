import React from 'react';
import { Composition, registerRoot } from 'remotion';
// 引入我們寫好的時間軸核心
import MainTimeline from './components/RemotionPlayer/MainTimeline';
import '../index.css'; // 如果影片中有用到 Tailwind CSS 樣式，記得引入

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
            durationInFrames={150} // 預設值，實際會被後端傳來的 blueprint 覆蓋
            fps={30}               // 預設值
            width={1080}
            height={1920}
            defaultProps={{
            blueprint: null,
            assetsRootUrl: ''
            }}
        />
        </>
    );
};

// 將這支檔案註冊為 Remotion 的渲染根節點
registerRoot(RemotionRoot);