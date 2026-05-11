import React from 'react';
import { useHandleSignInCallback } from '@logto/react';
import { useNavigate } from 'react-router-dom';

export default function CallbackPage() {
  const navigate = useNavigate();

  // 使用 Logto v4 專用的回調 hook，完成後自動導向首頁
  const { isLoading, error } = useHandleSignInCallback(() => {
    navigate('/', { replace: true });
  });

  if (error) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-red-400 text-center px-6">
        <div>
          <p className="text-xl font-semibold mb-2">登入失敗</p>
          <p className="text-sm text-gray-400">{error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full items-center justify-center bg-black">
      <div className="flex flex-col items-center gap-4 text-gray-400">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm">正在完成登入...</p>
      </div>
    </div>
  );
}
