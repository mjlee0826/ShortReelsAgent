import React from 'react';
import { useHandleSignInCallback } from '@logto/react';
import { useNavigate } from 'react-router-dom';
import { Spinner } from '../components/ui';

/**
 * CallbackPage：Logto 登入回調頁。完成 OAuth 流程後自動導回首頁，失敗時顯示錯誤。
 */
export default function CallbackPage() {
  const navigate = useNavigate();

  // 使用 Logto v4 專用的回調 hook，完成後自動導向首頁
  const { error } = useHandleSignInCallback(() => {
    navigate('/', { replace: true });
  });

  if (error) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-canvas text-danger text-center px-6">
        <div>
          <p className="text-xl font-semibold mb-2">登入失敗</p>
          <p className="text-sm text-ink-muted">{error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full items-center justify-center bg-canvas">
      <div className="flex flex-col items-center gap-4 text-ink-muted">
        <Spinner size="lg" />
        <p className="text-sm">正在完成登入...</p>
      </div>
    </div>
  );
}
