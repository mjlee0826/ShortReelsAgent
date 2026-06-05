import React from 'react';
import { useLogto } from '@logto/react';
import { Button } from '../components/ui';

/**
 * LoginPage：未登入時的進入頁。品牌標語 + Logto 登入按鈕，背景帶品牌光暈裝飾。
 */
export default function LoginPage() {
  const { signIn } = useLogto();

  return (
    <div className="relative flex h-screen w-full items-center justify-center bg-canvas overflow-hidden">
      {/* 背景光暈裝飾 */}
      <div className="pointer-events-none absolute -top-32 left-1/2 -translate-x-1/2 w-[36rem] h-[36rem] rounded-full bg-accent/20 blur-[120px]" />

      <div className="relative flex flex-col items-center gap-8 text-center px-6">
        <div className="flex flex-col items-center gap-4">
          <div className="w-20 h-20 rounded-3xl bg-accent/15 border border-accent/30 flex items-center justify-center text-4xl">🎬</div>
          <h1 className="text-4xl font-bold text-ink tracking-tight">Short Reels Agent</h1>
          <p className="text-ink-muted text-base max-w-sm leading-relaxed">
            AI 驅動的短影片剪輯助手，讓你的素材秒變爆款 Reels
          </p>
        </div>

        <Button size="lg" onClick={() => signIn(`${window.location.origin}/callback`)} className="px-10">
          登入 / 註冊
        </Button>

        <p className="text-ink-faint text-xs">使用 Logto 安全登入，你的專案資料完全隔離</p>
      </div>
    </div>
  );
}
