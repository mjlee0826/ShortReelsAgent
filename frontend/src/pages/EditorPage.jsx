import React, { useEffect, useLayoutEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { FaSpinner } from 'react-icons/fa';
import AppHeader from '../components/AppHeader/AppHeader';
import Workbench from '../components/Editor/Workbench';
import useBlueprintStore from '../store/useBlueprintStore';
import useProjectStore from '../store/useProjectStore';
import useProgressSocket from '../hooks/useProgressSocket';
import { apiService } from '../services/api.service';

// 就地編輯自動儲存的 debounce 間隔（毫秒）：連續編輯只在停手後寫一次，避免每次 mutate 都打後端。
const AUTOSAVE_DEBOUNCE_MS = 1000;

/**
 * EditorPage：編輯器頁殼層（單一工作台版）。
 *
 * 不再分「生成前 / 生成後」兩頁——一律渲染 Workbench（未生成時為等待劇本的空台、Pilot 對話預設開著，
 * 初次生成直接於對話框下指令）：
 *   - 載入既有藍圖中 → 載入動畫
 *   - 其餘 → Workbench（AI 粗剪 + 人工精修工作台）
 * 專案身分改由網址 /projects/:projectId/editor 帶入（比照素材頁），進入時自動向後端讀回上次生成的
 * 藍圖；另負責「素材未分析」的守門跳轉。
 */
export default function EditorPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const blueprint = useBlueprintStore((s) => s.blueprint);
  const isLoadingBlueprint = useBlueprintStore((s) => s.isLoadingBlueprint);
  const loadSavedBlueprint = useBlueprintStore((s) => s.loadSavedBlueprint);
  const redirectToAssetsProject = useBlueprintStore((s) => s.redirectToAssetsProject);
  const clearAssetsRedirect = useBlueprintStore((s) => s.clearAssetsRedirect);
  const currentProject = useProjectStore((s) => s.currentProject);
  const currentProjectName = currentProject?.name;
  const selectProject = useProjectStore((s) => s.selectProject);
  const isProcessing = useBlueprintStore((s) => s.isProcessing);
  const persistBlueprint = useBlueprintStore((s) => s.persistBlueprint);
  // 進行中生成的 WS 訂閱狀態 / 回呼（Observer Pattern 前端側）
  const generationJobId = useBlueprintStore((s) => s.generationJobId);
  const onGenerationEvent = useBlueprintStore((s) => s.onGenerationEvent);
  const onGenerationClosed = useBlueprintStore((s) => s.onGenerationClosed);
  const attachGeneration = useBlueprintStore((s) => s.attachGeneration);
  const connect = useProgressSocket(onGenerationEvent, onGenerationClosed);

  // 由網址參數同步當前專案：直接重整 /projects/:projectId/editor 時 store 尚未選定，
  // 以 projectId 補選（display_name 後備為 projectId，比照素材頁）。由總覽頁正常進入時 name 已相符、
  // 不會覆蓋既有 display_name；selectProject 內會重置 blueprint store，故僅在不相符時觸發避免誤清。
  useEffect(() => {
    if (projectId && currentProjectName !== projectId) {
      selectProject({ name: projectId, display_name: projectId });
    }
  }, [projectId, currentProjectName, selectProject]);

  // 進入編輯器（或切換專案）時，若記憶體無 blueprint 就向後端讀回上次生成的結果。
  // 用 useLayoutEffect：在瀏覽器繪製前就把 isLoadingBlueprint 設起，避免閃過空台工作台。
  // 依賴含 blueprint：可化解 selectProject 非同步 reset 與本效果的競態（reset 後 blueprint 變 null 會再觸發）。
  useLayoutEffect(() => {
    if (currentProjectName && !blueprint) loadSavedBlueprint(currentProjectName);
  }, [currentProjectName, blueprint, loadSavedBlueprint]);

  // 有進行中生成 job 就訂閱其 WS（初次提交設 generationJobId、或重進接回皆走此路徑）
  useEffect(() => {
    if (generationJobId) connect(generationJobId);
  }, [generationJobId, connect]);

  // 就地編輯自動儲存：任何編輯（裁切 / 字幕 / 音量 / 運鏡開關 / 換曲 / undo-redo / 還原快照）
  // 都會換掉 blueprint 物件參照 → 此效果 debounce 後落地。persistBlueprint 內以 persistedBlueprint
  // 去重，故載入 / 生成結果（剛從磁碟讀回或 run_workflow 已寫）會 no-op，不冗餘回寫。
  // 生成 / 載入中不自動存：避免與後端寫 PHASE4 競寫，且當下 blueprint 非使用者就地編輯。
  useEffect(() => {
    if (!blueprint || !currentProjectName || isProcessing || isLoadingBlueprint) return;
    const timerId = setTimeout(() => persistBlueprint(currentProjectName), AUTOSAVE_DEBOUNCE_MS);
    return () => clearTimeout(timerId);
  }, [blueprint, currentProjectName, isProcessing, isLoadingBlueprint, persistBlueprint]);

  // 掛載 / 換專案：查是否有進行中生成 job，有就接回其即時進度（比照 Phase 1 重整接回，見 docs §10.9）。
  // 後端已校驗孤兒（重啟後回 null），故只在仍有有效 job 時才訂閱；無則維持讀磁碟藍圖的既有路徑。
  useEffect(() => {
    if (!currentProjectName) return;
    let active = true;
    apiService.fetchGenerationProgress(currentProjectName)
      .then((data) => { if (active && data?.active_job_id) attachGeneration(data.active_job_id); })
      .catch(() => { /* 查詢失敗不致命：維持讀磁碟藍圖的既有路徑 */ });
    return () => { active = false; };
  }, [currentProjectName, attachGeneration]);

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
      ) : (
        <Workbench />
      )}
    </div>
  );
}
