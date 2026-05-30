import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useLogto } from '@logto/react';
import { setAuthBridge } from './services/api.service';
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
 * AuthInterceptorSetup：把 Logto 的 getAccessToken / signOut 注入 Auth Bridge。
 *
 * interceptor 本身已在 api.service 模組載入時註冊（杜絕競態），此處只負責
 * 在「render 階段」把最新的 Logto 方法餵給 bridge。
 *
 * 為何在 render 階段而非 useEffect：React 的 effect 執行順序為「子先父後」，
 * 若在 effect 注入，ProjectDashboard 的 fetchProjects effect 會早一步觸發、
 * 此時 bridge 尚未就緒。改在 render 階段注入，因父元件 render 必早於子元件
 * render 與 effect，故 bridge 必定先就緒。此處僅為冪等賦值，重複 render 無副作用。
 */
function AuthInterceptorSetup({ children }) {
  const { getAccessToken, signOut } = useLogto();
  setAuthBridge({ getAccessToken, signOut });
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
