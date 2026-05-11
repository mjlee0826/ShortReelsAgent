import React from 'react';
import { useLogto } from '@logto/react';

export default function LoginPage() {
  const { signIn } = useLogto();

  return (
    <div className="flex h-screen w-full items-center justify-center bg-black">
      <div className="flex flex-col items-center gap-8 text-center px-6">
        {/* Logo 區域 */}
        <div className="flex flex-col items-center gap-3">
          <div className="text-5xl">🎬</div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Short Reels Agent</h1>
          <p className="text-gray-400 text-base max-w-sm">
            AI 驅動的短影片剪輯助手，讓你的素材秒變爆款 Reels
          </p>
        </div>

        {/* 登入按鈕 */}
        <button
          onClick={() => signIn(`${window.location.origin}/callback`)}
          className="px-10 py-4 bg-blue-600 hover:bg-blue-500 active:scale-[0.98] text-white font-semibold text-lg rounded-xl transition-all shadow-lg shadow-blue-500/20"
        >
          登入 / 註冊
        </button>

        <p className="text-gray-600 text-xs">
          使用 Logto 安全登入，你的專案資料完全隔離
        </p>
      </div>
    </div>
  );
}
