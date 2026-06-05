import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaPlus, FaTrash, FaFilm, FaExclamationCircle, FaThLarge, FaGoogleDrive } from 'react-icons/fa';
import useProjectStore from '../store/useProjectStore';
import AppHeader from '../components/AppHeader/AppHeader';
import { Button, Card, Badge, Modal, Input, Spinner, EmptyState, IconButton } from '../components/ui';

// 雲端來源識別字串（與後端 ingestion_engine 的 SOURCE_GDRIVE 對應）
const SOURCE_GDRIVE = 'gdrive';

/**
 * CreateProjectModal：建立新專案對話框。
 *
 * 依產品定位，新專案一律來自 Google Drive 資料夾，故「專案名稱」與「Drive 連結」皆為必填；
 * 送出後後端會建立雲端來源專案並於背景啟動首次同步（下載素材 + Phase 1）。
 */
function CreateProjectModal({ onClose, onCreate }) {
  const [displayName, setDisplayName] = useState('');
  const [driveLink, setDriveLink] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const canSubmit = displayName.trim() && driveLink.trim();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setIsCreating(true);
    try {
      await onCreate(displayName.trim(), driveLink.trim());
      onClose();
    } catch {
      // 失敗訊息由 store 寫入 errorMsg，這裡僅恢復可再次送出狀態
      setIsCreating(false);
    }
  };

  return (
    <Modal title="建立新專案" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="專案名稱"
          autoFocus
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="例：婚禮精華 2025"
          maxLength={60}
        />
        <Input
          label="Google Drive 資料夾連結"
          icon={<FaGoogleDrive />}
          value={driveLink}
          onChange={(e) => setDriveLink(e.target.value)}
          placeholder="https://drive.google.com/drive/folders/..."
          hint="請將資料夾分享設為「知道連結的任何人皆可檢視」；建立後素材會於背景自動下載並分析。"
        />
        <div className="flex justify-end gap-3 mt-1">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={!canSubmit} loading={isCreating}>建立專案</Button>
        </div>
      </form>
    </Modal>
  );
}

/**
 * ProjectCard：單一專案卡片。點卡片進編輯器、點「管理素材」進素材頁、hover 顯示刪除。
 * 依後設資料顯示 Drive 來源、藍圖狀態與同步錯誤徽章。
 */
function ProjectCard({ project, onOpen, onManage, onDelete }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const isDrive = project.source === SOURCE_GDRIVE;
  const hasBadges = isDrive || project.has_blueprint || project.last_sync_error;

  const lastModified = new Date(project.last_modified).toLocaleDateString('zh-TW', {
    year: 'numeric', month: 'short', day: 'numeric',
  });

  return (
    <Card interactive onClick={() => onOpen(project)} className="group relative p-5 flex flex-col gap-4">
      {/* 頂部：圖示（刪除鈕 hover 浮現於右上）*/}
      <div className="w-11 h-11 rounded-xl bg-accent/15 flex items-center justify-center text-accent text-lg">
        <FaFilm />
      </div>

      {/* 名稱與後設資訊 */}
      <div className="min-w-0">
        <h3 className="text-ink font-semibold text-base leading-tight truncate">{project.display_name}</h3>
        <p className="text-ink-faint text-xs mt-1">{project.asset_count} 個素材 · {lastModified}</p>
      </div>

      {/* 狀態徽章列（有才顯示）*/}
      {hasBadges && (
        <div className="flex flex-wrap items-center gap-1.5">
          {isDrive && <Badge tone="accent"><FaGoogleDrive size={10} /> Drive</Badge>}
          {project.has_blueprint && <Badge tone="success">已有藍圖</Badge>}
          {project.last_sync_error && (
            <span title={project.last_sync_error}><Badge tone="danger">同步失敗</Badge></span>
          )}
        </div>
      )}

      {/* 管理素材 */}
      <Button
        variant="secondary"
        size="sm"
        fullWidth
        leftIcon={<FaThLarge size={11} />}
        onClick={(e) => { e.stopPropagation(); onManage(project); }}
      >
        管理素材
      </Button>

      {/* 刪除（hover 才顯示）*/}
      <div
        className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={(e) => e.stopPropagation()}
      >
        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => onDelete(project.name)}
              className="text-[11px] px-2 py-1 bg-danger/90 hover:bg-danger text-white rounded-lg transition-colors"
            >
              確認刪除
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="text-[11px] px-2 py-1 text-ink-muted hover:text-ink transition-colors"
            >
              取消
            </button>
          </div>
        ) : (
          <IconButton tone="danger" className="w-7 h-7" onClick={() => setConfirmDelete(true)} title="刪除專案">
            <FaTrash size={11} />
          </IconButton>
        )}
      </div>
    </Card>
  );
}

/**
 * ProjectDashboard：專案總覽頁。列出使用者所有專案、建立新專案（Drive 來源）、進入編輯器或素材頁。
 */
export default function ProjectDashboard() {
  const navigate = useNavigate();
  const {
    projects, isLoading, errorMsg,
    fetchProjects, createProjectFromDrive, deleteProject, selectProject, clearError,
  } = useProjectStore();
  const [showCreateModal, setShowCreateModal] = useState(false);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleOpenProject = (project) => {
    selectProject(project);
    navigate('/editor');
  };

  // 進入素材管理頁：先選定專案（讓素材頁可取用 display_name），再導向
  const handleManageProject = (project) => {
    selectProject(project);
    navigate(`/projects/${project.name}/assets`);
  };

  return (
    <div className="flex flex-col h-screen bg-canvas font-sans">
      <AppHeader />

      <main className="flex-1 overflow-y-auto px-6 py-8 max-w-5xl mx-auto w-full">
        {/* 頁首：標題 + 新增按鈕 */}
        <div className="flex items-end justify-between mb-8 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-ink">我的專案</h1>
            <p className="text-sm text-ink-faint mt-1">選擇一個專案進入編輯器，或從 Google Drive 建立新專案</p>
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

        {/* 載入中 */}
        {isLoading && projects.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-20 text-ink-faint">
            <Spinner />
            <p className="text-sm">載入專案中...</p>
          </div>
        )}

        {/* 空狀態 / 專案格線 */}
        {!isLoading && projects.length === 0 ? (
          <EmptyState
            icon={<FaFilm />}
            title="目前沒有任何專案"
            description="從 Google Drive 資料夾建立你的第一個專案，素材會自動同步進來。"
            action={<Button leftIcon={<FaPlus size={12} />} onClick={() => setShowCreateModal(true)}>建立第一個專案</Button>}
          />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((project) => (
              <ProjectCard
                key={project.name}
                project={project}
                onOpen={handleOpenProject}
                onManage={handleManageProject}
                onDelete={deleteProject}
              />
            ))}
          </div>
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
