import React, { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useLogto } from '@logto/react';
import { apiClient } from './services/api.service';
import LoginPage from './pages/LoginPage';
import CallbackPage from './pages/CallbackPage';
import ProjectDashboard from './pages/ProjectDashboard';
import EditorPage from './pages/EditorPage';

/**
 * AuthGuard：保護需要登入才能存取的路由。
 * isLoading 期間顯示 loading indicator；未認證則重導向至 /login。
 */
function AuthGuard({ children }) {
  const { isAuthenticated, isLoading } = useLogto();

  // isLoading 也可能是 getAccessToken 代理觸發，不能用來卸載已認證的子元件
  if (isLoading && !isAuthenticated) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

/**
 * AuthInterceptorSetup：在 React context 內取得 Logto access token，
 * 並注入 axios 攔截器，讓所有 API 請求自動攜帶 Bearer token。
 */
function AuthInterceptorSetup({ children }) {
  const { getAccessToken, isAuthenticated } = useLogto();
  const API_RESOURCE = import.meta.env.VITE_LOGTO_API_RESOURCE;

  useEffect(() => {
    if (!isAuthenticated) return;

    const interceptorId = apiClient.interceptors.request.use(async (config) => {
      try {
        const token = await getAccessToken(API_RESOURCE);
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
      } catch (e) {
        console.warn('[Auth] 無法取得 access token:', e);
      }
      return config;
    });

    // 清除攔截器，避免登出後仍嘗試附加 token
    return () => apiClient.interceptors.request.eject(interceptorId);
  }, [isAuthenticated, getAccessToken, API_RESOURCE]);

  return children;
}

export default function App() {
  return (
    <AuthInterceptorSetup>
      <Routes>
        <Route path="/login"    element={<LoginPage />} />
        <Route path="/callback" element={<CallbackPage />} />
        <Route path="/"         element={<AuthGuard><ProjectDashboard /></AuthGuard>} />
        <Route path="/editor"   element={<AuthGuard><EditorPage /></AuthGuard>} />
        {/* 未知路徑一律導回首頁 */}
        <Route path="*"         element={<Navigate to="/" replace />} />
      </Routes>
    </AuthInterceptorSetup>
  );
}
