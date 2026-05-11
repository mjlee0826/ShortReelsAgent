import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaPlus, FaTrash, FaFilm, FaExclamationCircle } from 'react-icons/fa';
import useProjectStore from '../store/useProjectStore';
import AppHeader from '../components/AppHeader/AppHeader';

// 建立專案的 Modal 元件
function CreateProjectModal({ onClose, onCreate }) {
  const [displayName, setDisplayName] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!displayName.trim()) return;
    setIsCreating(true);
    try {
      await onCreate(displayName.trim());
      onClose();
    } catch {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 px-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <h2 className="text-lg font-semibold text-white mb-4">建立新專案</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <input
            autoFocus
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="專案名稱（例：婚禮精華 2025）"
            className="bg-gray-800 text-white px-4 py-3 rounded-xl border border-gray-700 focus:border-blue-500 focus:outline-none"
            maxLength={60}
          />
          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={!displayName.trim() || isCreating}
              className="px-5 py-2 text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg font-medium transition-all"
            >
              {isCreating ? '建立中...' : '建立專案'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// 專案卡片元件
function ProjectCard({ project, onOpen, onDelete }) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleDeleteClick = (e) => {
    e.stopPropagation();
    setConfirmDelete(true);
  };

  const handleConfirmDelete = async (e) => {
    e.stopPropagation();
    await onDelete(project.name);
  };

  const lastModified = new Date(project.last_modified).toLocaleDateString('zh-TW', {
    year: 'numeric', month: 'short', day: 'numeric',
  });

  return (
    <div
      onClick={() => onOpen(project)}
      className="group relative bg-gray-900 border border-gray-800 hover:border-blue-600 rounded-2xl p-5 cursor-pointer transition-all hover:shadow-lg hover:shadow-blue-500/10 flex flex-col gap-3"
    >
      {/* 藍圖狀態標示 */}
      <div className="flex items-center justify-between">
        <div className="w-10 h-10 rounded-xl bg-gray-800 flex items-center justify-center text-blue-400 text-lg">
          <FaFilm />
        </div>
        {project.has_blueprint && (
          <span className="text-[10px] px-2 py-0.5 bg-blue-900/50 text-blue-400 rounded-full border border-blue-800/50">
            已有藍圖
          </span>
        )}
      </div>

      {/* 名稱與素材數量 */}
      <div>
        <h3 className="text-white font-semibold text-base leading-tight truncate">{project.display_name}</h3>
        <p className="text-gray-500 text-xs mt-1">{project.asset_count} 個素材・{lastModified}</p>
      </div>

      {/* 刪除按鈕（hover 才顯示）*/}
      <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
        {confirmDelete ? (
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={handleConfirmDelete}
              className="text-[11px] px-2 py-1 bg-red-700 hover:bg-red-600 text-white rounded-lg"
            >
              確認刪除
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); }}
              className="text-[11px] px-2 py-1 text-gray-400 hover:text-white"
            >
              取消
            </button>
          </div>
        ) : (
          <button
            onClick={handleDeleteClick}
            className="p-1.5 text-gray-600 hover:text-red-400 transition-colors"
            title="刪除專案"
          >
            <FaTrash size={12} />
          </button>
        )}
      </div>
    </div>
  );
}

export default function ProjectDashboard() {
  const navigate = useNavigate();
  const { projects, isLoading, errorMsg, fetchProjects, createProject, deleteProject, selectProject, clearError } = useProjectStore();
  const [showCreateModal, setShowCreateModal] = useState(false);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleOpenProject = (project) => {
    selectProject(project);
    navigate('/editor');
  };

  return (
    <div className="flex flex-col h-screen bg-black font-sans">
      <AppHeader />

      <main className="flex-1 overflow-y-auto px-6 py-8 max-w-5xl mx-auto w-full">
        {/* 頁首：標題 + 新增按鈕 */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">我的專案</h1>
            <p className="text-sm text-gray-500 mt-1">選擇一個專案進入編輯器，或建立新專案</p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-xl transition-all active:scale-95 shadow-lg shadow-blue-500/20"
          >
            <FaPlus size={12} /> 新增專案
          </button>
        </div>

        {/* 錯誤訊息 */}
        {errorMsg && (
          <div className="flex items-center gap-2 mb-4 px-4 py-3 bg-red-950/50 border border-red-800/50 rounded-xl text-red-400 text-sm">
            <FaExclamationCircle />
            <span>{errorMsg}</span>
            <button onClick={clearError} className="ml-auto text-gray-500 hover:text-white">✕</button>
          </div>
        )}

        {/* 載入中 */}
        {isLoading && projects.length === 0 && (
          <div className="flex items-center justify-center py-20 text-gray-600">
            <div className="flex flex-col items-center gap-3">
              <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-sm">載入專案中...</p>
            </div>
          </div>
        )}

        {/* 專案卡片格線 */}
        {!isLoading && projects.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-600 gap-4">
            <FaFilm size={40} className="opacity-20" />
            <p className="text-base">目前沒有任何專案</p>
            <button
              onClick={() => setShowCreateModal(true)}
              className="text-sm text-blue-500 hover:text-blue-400 underline underline-offset-2"
            >
              建立你的第一個專案
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((project) => (
              <ProjectCard
                key={project.name}
                project={project}
                onOpen={handleOpenProject}
                onDelete={deleteProject}
              />
            ))}
          </div>
        )}
      </main>

      {/* 建立專案 Modal */}
      {showCreateModal && (
        <CreateProjectModal
          onClose={() => setShowCreateModal(false)}
          onCreate={createProject}
        />
      )}
    </div>
  );
}
