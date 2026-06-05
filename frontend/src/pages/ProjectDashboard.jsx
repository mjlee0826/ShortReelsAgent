import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaPlus, FaFilm, FaExclamationCircle, FaSearch } from 'react-icons/fa';
import useProjectStore from '../store/useProjectStore';
import AppHeader from '../components/AppHeader/AppHeader';
import { Button, Spinner, EmptyState } from '../components/ui';
import { ProjectGrid, ProjectToolbar, CreateProjectModal } from '../components/ProjectGrid';
import { SORT_KEY } from '../components/ProjectGrid/projectStatus';

/**
 * ProjectDashboard：專案總覽頁（協調者）。
 *
 * 組合 AppHeader + 頁首 + 瀏覽工具列（搜尋 / 排序）+ 載入 / 錯誤 / 空狀態 + 專案網格 + 建立對話框。
 * 資料流沿用 useProjectStore；搜尋與排序為純前端（useMemo），不額外打 API。
 */
export default function ProjectDashboard() {
  const navigate = useNavigate();
  const {
    projects, isLoading, errorMsg,
    fetchProjects, createProjectFromDrive, deleteProject, selectProject, clearError,
  } = useProjectStore();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortKey, setSortKey] = useState(SORT_KEY.RECENT);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // 依搜尋（名稱不分大小寫）與排序計算可見專案；純前端、不變更原始清單
  const visibleProjects = useMemo(() => {
    const keyword = searchQuery.trim().toLowerCase();
    const filtered = keyword
      ? projects.filter((p) => p.display_name.toLowerCase().includes(keyword))
      : projects;
    // 複製後排序，避免就地改動 store 的陣列
    return [...filtered].sort((a, b) => {
      if (sortKey === SORT_KEY.NAME) return a.display_name.localeCompare(b.display_name, 'zh-Hant');
      // 預設：最近修改在前
      return new Date(b.last_modified) - new Date(a.last_modified);
    });
  }, [projects, searchQuery, sortKey]);

  const handleOpenProject = (project) => {
    selectProject(project);
    navigate('/editor');
  };

  // 進入素材管理頁：先選定專案（讓素材頁可取用 display_name），再導向
  const handleManageProject = (project) => {
    selectProject(project);
    navigate(`/projects/${project.name}/assets`);
  };

  const hasProjects = projects.length > 0;

  return (
    <div className="flex flex-col h-screen bg-canvas font-sans">
      <AppHeader />

      <main className="flex-1 overflow-y-auto px-6 py-8 max-w-6xl mx-auto w-full">
        {/* 頁首：標題 + 專案數 + 新增按鈕 */}
        <div className="flex items-end justify-between mb-7 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-ink tracking-tight">我的專案</h1>
            <p className="text-sm text-ink-faint mt-1">
              {hasProjects
                ? `共 ${projects.length} 個專案 · 選一個進入編輯器，或從 Google Drive 建立新專案`
                : '選擇一個專案進入編輯器，或從 Google Drive 建立新專案'}
            </p>
          </div>
          <Button leftIcon={<FaPlus size={12} />} onClick={() => setShowCreateModal(true)}>新增專案</Button>
        </div>

        {/* 錯誤訊息 */}
        {errorMsg && (
          <div className="flex items-center gap-2 mb-5 px-4 py-3 bg-danger/10 border border-danger/30 rounded-xl text-danger text-sm">
            <FaExclamationCircle className="shrink-0" />
            <span className="flex-1">{errorMsg}</span>
            <button onClick={clearError} className="text-ink-faint hover:text-ink transition-colors">✕</button>
          </div>
        )}

        {/* 瀏覽工具列（有專案才顯示）*/}
        {hasProjects && (
          <ProjectToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            sortKey={sortKey}
            onSortChange={setSortKey}
          />
        )}

        {/* 內容：載入 → 無專案 → 搜尋無結果 → 網格（單一條件鏈，避免重疊）*/}
        {isLoading && projects.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-20 text-ink-faint">
            <Spinner />
            <p className="text-sm">載入專案中...</p>
          </div>
        ) : projects.length === 0 ? (
          <EmptyState
            icon={<FaFilm />}
            title="目前沒有任何專案"
            description="從 Google Drive 資料夾建立你的第一個專案，素材會自動同步進來。"
            action={<Button leftIcon={<FaPlus size={12} />} onClick={() => setShowCreateModal(true)}>建立第一個專案</Button>}
          />
        ) : visibleProjects.length === 0 ? (
          <EmptyState
            icon={<FaSearch />}
            title="找不到符合的專案"
            description={`沒有名稱包含「${searchQuery.trim()}」的專案，試試其他關鍵字。`}
          />
        ) : (
          <ProjectGrid
            projects={visibleProjects}
            onOpen={handleOpenProject}
            onManage={handleManageProject}
            onDelete={deleteProject}
          />
        )}
      </main>

      {showCreateModal && (
        <CreateProjectModal
          onClose={() => setShowCreateModal(false)}
          onCreate={createProjectFromDrive}
        />
      )}
    </div>
  );
}
