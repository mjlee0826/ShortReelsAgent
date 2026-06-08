import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import AppHeader from '../components/AppHeader/AppHeader';
import SetupView from '../components/Editor/SetupView';
import Workbench from '../components/Editor/Workbench';
import useBlueprintStore from '../store/useBlueprintStore';

/**
 * EditorPage：編輯器頁的兩階段殼層。
 *
 * 依 blueprint 是否存在條件渲染（不新增路由）：
 *   - 尚未生成 → SetupView（聚焦的生成前畫面）
 *   - 已有藍圖 → Workbench（AI 粗剪 + 人工精修工作台）
 * 另負責「素材未分析」的守門跳轉。
 */
export default function EditorPage() {
  const navigate = useNavigate();
  const blueprint = useBlueprintStore((s) => s.blueprint);
  const redirectToAssetsProject = useBlueprintStore((s) => s.redirectToAssetsProject);
  const clearAssetsRedirect = useBlueprintStore((s) => s.clearAssetsRedirect);

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
      {blueprint ? <Workbench /> : <SetupView />}
    </div>
  );
}
