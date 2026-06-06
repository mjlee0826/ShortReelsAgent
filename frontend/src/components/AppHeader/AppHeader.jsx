import React from 'react';
import { useLogto } from '@logto/react';
import { useNavigate, useLocation } from 'react-router-dom';
import { FaThLarge, FaCog } from 'react-icons/fa';
import useProjectStore from '../../store/useProjectStore';
import { Button, IconButton } from '../ui';

/**
 * AppHeader：全站頂部導覽列。
 *
 * 顯示品牌 + 麵包屑（我的專案 / 當前專案）、編輯器頁專屬的「管理素材」捷徑（需求 5），
 * 以及使用者頭像資訊與登出。
 */
export default function AppHeader() {
  const { signOut, fetchUserInfo } = useLogto();
  const navigate = useNavigate();
  const location = useLocation();
  const currentProject = useProjectStore((s) => s.currentProject);
  const [userInfo, setUserInfo] = React.useState(null);

  React.useEffect(() => {
    fetchUserInfo().then(setUserInfo).catch(() => {});
  }, [fetchUserInfo]);

  const handleSignOut = () => signOut(`${window.location.origin}/login`);

  // 僅在編輯器頁、且已選定專案時顯示「管理素材」捷徑，導向該專案的素材審閱頁
  const showManageAssets = location.pathname === '/editor' && currentProject?.name;
  const goManageAssets = () => navigate(`/projects/${currentProject.name}/assets`);

  const displayName = userInfo?.name || userInfo?.username || userInfo?.email || '使用者';
  const avatarLetter = displayName.charAt(0).toUpperCase();

  return (
    <header className="flex items-center justify-between px-5 py-3 bg-surface/80 backdrop-blur border-b border-border shrink-0 z-10">
      {/* 左側：品牌 + 麵包屑 */}
      <div className="flex items-center gap-2.5 min-w-0">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-2 text-base font-bold text-ink tracking-tight hover:opacity-80 transition-opacity shrink-0"
          title="回首頁"
        >
          <span className="w-7 h-7 rounded-lg bg-accent/15 text-accent flex items-center justify-center text-sm">🎬</span>
          <span className="hidden sm:block">Short Reels</span>
        </button>
        {currentProject && (
          <>
            <span className="text-ink-faint/50">/</span>
            <button
              onClick={() => navigate('/')}
              className="text-sm text-ink-muted hover:text-ink transition-colors shrink-0"
            >
              我的專案
            </button>
            <span className="text-ink-faint/50">/</span>
            <span className="text-sm text-accent-ink font-medium truncate max-w-[180px]">
              {currentProject.display_name}
            </span>
          </>
        )}
      </div>

      {/* 右側：管理素材（編輯器頁）+ 使用者資訊 + 登出 */}
      <div className="flex items-center gap-3 shrink-0">
        {showManageAssets && (
          <Button variant="secondary" size="sm" leftIcon={<FaThLarge size={11} />} onClick={goManageAssets}>
            管理素材
          </Button>
        )}
        {/* 全域設定入口：任何頁面皆可進入 /settings */}
        <IconButton tone="accent" title="設定" onClick={() => navigate('/settings')}>
          <FaCog size={15} />
        </IconButton>
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold shrink-0 overflow-hidden">
            {userInfo?.picture ? (
              <img src={userInfo.picture} alt={displayName} className="w-full h-full object-cover" />
            ) : (
              avatarLetter
            )}
          </div>
          <span className="text-sm text-ink-muted hidden md:block max-w-[120px] truncate">{displayName}</span>
        </div>
        <Button variant="ghost" size="sm" onClick={handleSignOut} className="hover:text-danger">
          登出
        </Button>
      </div>
    </header>
  );
}
