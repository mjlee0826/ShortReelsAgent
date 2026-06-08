import React, { useEffect, useLayoutEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaSpinner } from 'react-icons/fa';
import AppHeader from '../components/AppHeader/AppHeader';
import SetupView from '../components/Editor/SetupView';
import Workbench from '../components/Editor/Workbench';
import useBlueprintStore from '../store/useBlueprintStore';
import useProjectStore from '../store/useProjectStore';

/**
 * EditorPage：編輯器頁的兩階段殼層。
 *
 * 依 blueprint 是否存在條件渲染（不新增路由）：
 *   - 載入既有藍圖中 → 載入動畫
 *   - 尚未生成 → SetupView（聚焦的生成前畫面）
 *   - 已有藍圖 → Workbench（AI 粗剪 + 人工精修工作台）
 * 進入時自動向後端讀回上次生成的藍圖；另負責「素材未分析」的守門跳轉。
 */
export default function EditorPage() {
  const navigate = useNavigate();
  const blueprint = useBlueprintStore((s) => s.blueprint);
  const isLoadingBlueprint = useBlueprintStore((s) => s.isLoadingBlueprint);
  const loadSavedBlueprint = useBlueprintStore((s) => s.loadSavedBlueprint);
  const redirectToAssetsProject = useBlueprintStore((s) => s.redirectToAssetsProject);
  const clearAssetsRedirect = useBlueprintStore((s) => s.clearAssetsRedirect);
  const currentProjectName = useProjectStore((s) => s.currentProject?.name);

  // 進入編輯器（或切換專案）時，若記憶體無 blueprint 就向後端讀回上次生成的結果。
  // 用 useLayoutEffect：在瀏覽器繪製前就把 isLoadingBlueprint 設起，避免閃過 SetupView。
  // 依賴含 blueprint：可化解 selectProject 非同步 reset 與本效果的競態（reset 後 blueprint 變 null 會再觸發）。
  useLayoutEffect(() => {
    if (currentProjectName && !blueprint) loadSavedBlueprint(currentProjectName);
  }, [currentProjectName, blueprint, loadSavedBlueprint]);

  // 生成因素材未分析失敗：帶提示跳轉素材頁，讓使用者先完成分析（reactive 守門）
  useEffect(() => {
    if (!redirectToAssetsProject) return;
    const project = redirectToAssetsProject;
    clearAssetsRedirect();
    navigate(`/projects/${project}/assets`, {
      state: { notice: '請先完成素材分析，再回編輯器生成影片。' },
    });
  }, [redirectToAssetsProject, clearAssetsRedirect, navigate]);

  return (
    <div className="flex flex-col h-screen w-full font-sans bg-canvas overflow-hidden">
      <AppHeader />
      {isLoadingBlueprint ? (
        <div className="flex-1 flex flex-col items-center justify-center bg-canvas">
          <FaSpinner className="animate-spin text-accent text-5xl mb-4" />
          <p className="text-ink-muted text-sm tracking-wide">正在載入專案影片…</p>
        </div>
      ) : blueprint ? (
        <Workbench />
      ) : (
        <SetupView />
      )}
    </div>
  );
}
