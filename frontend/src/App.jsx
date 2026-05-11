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
 * AuthInterceptorSetup：注入 axios request / response 攔截器。
 *
 * Strategy Pattern：
 * - Request interceptor：有 token 就附上，沒有（未登入）則略過。
 * - Response interceptor：收到 401 時自動換 token 重打；
 *   refresh token 也失效時強制登出，導向 /login。
 *
 * 掛載時一次性註冊，不依賴 isAuthenticated，徹底消除 race condition。
 */
function AuthInterceptorSetup({ children }) {
  const { getAccessToken, signOut } = useLogto();
  const API_RESOURCE = import.meta.env.VITE_LOGTO_API_RESOURCE;

  useEffect(() => {
    // 有 token 就附上，未登入時 getAccessToken 會拋出，略過即可
    const reqId = apiClient.interceptors.request.use(async (config) => {
      try {
        const token = await getAccessToken(API_RESOURCE);
        if (token) config.headers.Authorization = `Bearer ${token}`;
      } catch {
        // 未登入或 token 尚未就緒，讓 request 照常送出
      }
      return config;
    });

    // 401 → 嘗試換新 token 重打；換不了 → refresh token 過期，強制登出
    const resId = apiClient.interceptors.response.use(
      res => res,
      async (error) => {
        if (error.response?.status === 401 && !error.config._retry) {
          error.config._retry = true;
          try {
            const token = await getAccessToken(API_RESOURCE);
            error.config.headers.Authorization = `Bearer ${token}`;
            return apiClient(error.config);
          } catch {
            await signOut(`${window.location.origin}/login`);
          }
        }
        return Promise.reject(error);
      }
    );

    return () => {
      apiClient.interceptors.request.eject(reqId);
      apiClient.interceptors.response.eject(resId);
    };
  }, [getAccessToken, signOut, API_RESOURCE]);

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
