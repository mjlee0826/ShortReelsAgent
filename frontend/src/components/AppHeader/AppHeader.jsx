import React from 'react';
import { useLogto } from '@logto/react';
import { useNavigate } from 'react-router-dom';
import useProjectStore from '../../store/useProjectStore';

export default function AppHeader() {
  const { signOut, fetchUserInfo } = useLogto();
  const navigate = useNavigate();
  const currentProject = useProjectStore((s) => s.currentProject);
  const [userInfo, setUserInfo] = React.useState(null);

  React.useEffect(() => {
    fetchUserInfo().then(setUserInfo).catch(() => {});
  }, [fetchUserInfo]);

  const handleBackToDashboard = () => {
    navigate('/');
  };

  const handleSignOut = () => {
    signOut(`${window.location.origin}/login`);
  };

  const displayName = userInfo?.name || userInfo?.username || userInfo?.email || '使用者';
  const avatarLetter = displayName.charAt(0).toUpperCase();

  return (
    <header className="flex items-center justify-between px-4 py-2.5 bg-gray-950 border-b border-gray-800 shrink-0 z-10">
      {/* 左側：Logo + 返回按鈕 */}
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-white tracking-tight select-none">🎬 Short Reels</span>
        {currentProject && (
          <>
            <span className="text-gray-700">/</span>
            <button
              onClick={handleBackToDashboard}
              className="text-sm text-gray-400 hover:text-white transition-colors"
              title="返回專案列表"
            >
              我的專案
            </button>
            <span className="text-gray-700">/</span>
            <span className="text-sm text-blue-400 font-medium truncate max-w-[200px]">
              {currentProject.display_name}
            </span>
          </>
        )}
      </div>

      {/* 右側：使用者資訊 + 登出 */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          {/* 頭像 */}
          <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold shrink-0">
            {userInfo?.picture ? (
              <img src={userInfo.picture} alt={displayName} className="w-full h-full rounded-full object-cover" />
            ) : (
              avatarLetter
            )}
          </div>
          <span className="text-sm text-gray-300 hidden sm:block max-w-[120px] truncate">{displayName}</span>
        </div>
        <button
          onClick={handleSignOut}
          className="text-xs text-gray-500 hover:text-red-400 transition-colors px-2 py-1 rounded border border-gray-800 hover:border-red-800"
        >
          登出
        </button>
      </div>
    </header>
  );
}
