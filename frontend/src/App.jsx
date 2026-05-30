import React, { useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useLogto } from '@logto/react';
import { setAuthBridge } from './services/api.service';
import LoginPage from './pages/LoginPage';
import CallbackPage from './pages/CallbackPage';
import ProjectDashboard from './pages/ProjectDashboard';
import EditorPage from './pages/EditorPage';

const API_RESOURCE = import.meta.env.VITE_LOGTO_API_RESOURCE;

// 模組層級旗標：避免多個 AuthGuard / StrictMode 重複觸發 signOut
let _forcingReLogin = false;

/** 強制登出並回登入頁；signOut 會清掉 localStorage 內殘留的失效 token。 */
async function forceReLogin(signOut) {
  if (_forcingReLogin) return;
  _forcingReLogin = true;
  try {
    await signOut(`${window.location.origin}/login`);
  } catch {
    // signOut 端點失敗（離線等）也要保證離開受保護頁面
    window.location.assign('/login');
  }
}

/**
 * Spinner：載入 / 驗證 token 期間的等待畫面。
 */
function FullScreenSpinner() {
  return (
    <div className="flex h-screen w-full items-center justify-center bg-black">
      <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

/**
 * AuthGuard：保護需要登入才能存取的路由。
 *
 * 關鍵：``isAuthenticated`` 僅反映 localStorage 內有無 session 快取，
 * **不保證 refresh token 在 server 端仍有效**。因此進入受保護路由時主動
 * 嘗試換一次 access token：
 * - 成功 → refresh token 仍有效，放行子元件。
 * - 失敗 → refresh token 已過期/撤銷，呼叫 signOut 清掉殘留 token 並導回 /login，
 *   而不是放行後讓子元件的 API 請求一路撞 401。
 */
function AuthGuard({ children }) {
  const { isAuthenticated, isLoading, getAccessToken, signOut } = useLogto();
  // null=驗證中、true=token 有效、false=已觸發強制重登
  const [tokenValid, setTokenValid] = useState(null);

  useEffect(() => {
    let active = true;

    // 未登入：交給下方 Navigate 處理，不需驗 token
    if (!isAuthenticated) {
      setTokenValid(null);
      return;
    }

    // 已登入：主動驗證 refresh token 是否仍能換出 access token
    (async () => {
      try {
        await getAccessToken(API_RESOURCE);
        if (active) setTokenValid(true);
      } catch (err) {
        // refresh token 失效 → 強制重登（清狀態 + 導向 /login）
        console.warn('[Auth] refresh token 失效，強制重新登入：', err?.message || err);
        if (active) setTokenValid(false);
        await forceReLogin(signOut);
      }
    })();

    return () => { active = false; };
  }, [isAuthenticated, getAccessToken, signOut]);

  // SDK 還在還原 session，或已登入但 token 尚在驗證 → 顯示等待畫面
  if (isLoading || (isAuthenticated && tokenValid === null)) {
    return <FullScreenSpinner />;
  }

  // 未登入，或 token 驗證失敗（強制重登進行中）→ 導回登入頁
  if (!isAuthenticated || tokenValid === false) {
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
