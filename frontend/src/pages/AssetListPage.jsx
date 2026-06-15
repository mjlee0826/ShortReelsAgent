import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { FaArrowLeft, FaExclamationCircle, FaImages } from 'react-icons/fa';
import useProjectStore from '../store/useProjectStore';
import useProjectAssets from '../hooks/useProjectAssets';
import useAssetSelection from '../hooks/useAssetSelection';
import AppHeader from '../components/AppHeader/AppHeader';
import AssetGrid from '../components/AssetGrid/AssetGrid';
import AssetDetailModal from '../components/AssetGrid/AssetDetailModal';
import AssetSummaryBar from '../components/AssetGrid/AssetSummaryBar';
import BulkActionBar from '../components/AssetGrid/BulkActionBar';
import SelectionToolbar from '../components/AssetGrid/SelectionToolbar';
import ProgressOverlay from '../components/AssetGrid/ProgressOverlay';
import { summarizeAssets } from '../components/AssetGrid/assetSummary';
import { IconButton, Spinner, EmptyState } from '../components/ui';

/**
 * AssetListPage：專案素材管理頁（Layer 5）。
 *
 * 審閱素材縮圖與狀態、逐檔切換 Simple/Complex 策略、觸發 Phase 1 重新分析 / 開始生成，並以
 * WebSocket 即時把每張卡片更新為「處理中 + 當前 stage」。資料層在 useProjectAssets、選取層
 * 在 useAssetSelection；本元件負責組合兩者與版面呈現。完整生成（Phase 2–4）仍由編輯器負責。
 */
export default function AssetListPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const currentProject = useProjectStore((s) => s.currentProject);
  const selectProject = useProjectStore((s) => s.selectProject);

  // 選取層先宣告（不依賴素材清單）：其 exitSelection 供資料層在 job 啟動時重置選取，避免循環依賴
  const {
    selected, selectionMode, toggleSelect, selectAll, clearSelection, enterSelection, exitSelection,
  } = useAssetSelection();

  // 資料層：素材讀取 + 分析生命週期 + 會變更素材的操作
  const {
    assets, isLoading, errorMsg, setErrorMsg,
    liveStatusMap, jobRunning, progress, preparing,
    setStrategy, bulkStrategy, reanalyzeSelected, reanalyzeAll, generate,
  } = useProjectAssets(projectId, {
    // 由編輯器因素材未分析跳轉進來時，location.state.notice 作為初始提示帶入
    initialError: location.state?.notice || '',
    onJobStart: exitSelection,
  });

  // 詳情彈窗：null = 關閉；非 null = 開啟該素材詳情（存 relpath 身分；非選取模式點卡片開啟）
  const [detailPath, setDetailPath] = useState(null);

  const displayName =
    currentProject?.name === projectId ? currentProject.display_name : projectId;

  // 詳情彈窗對應的素材（以 relpath 身分查找）；供彈窗取顯示檔名與縮圖後備
  const detailAsset = detailPath ? assets.find((a) => a.path === detailPath) : null;

  // 素材統計（照片數 / 影片數 / 影片總時長）：素材清單變動才重算，供統計列呈現
  const summary = useMemo(() => summarizeAssets(assets), [assets]);

  // 提示已透過 initialError 帶入；此處只清掉 history state，避免重整 / 返回時殘留同一則提示
  useEffect(() => {
    if (location.state?.notice) {
      window.history.replaceState({}, document.title);
    }
  }, [location.state]);

  // ── 詳情彈窗 ─────────────────────────────────────────────────────────────────
  const openDetail = useCallback((path) => setDetailPath(path), []);
  const closeDetail = useCallback(() => setDetailPath(null), []);

  // 進選取模式即關閉詳情，避免兩模式狀態交疊（跨關注點，由頁面組合兩 hook）
  const handleEnterSelection = useCallback(() => {
    enterSelection();
    setDetailPath(null);
  }, [enterSelection]);

  const goEditor = useCallback(() => {
    // 確保編輯器取得當前專案（素材頁可能由重新整理直接進入，store 尚未選定）
    if (currentProject?.name !== projectId) {
      selectProject({ name: projectId, display_name: displayName });
    }
    navigate(`/projects/${projectId}/editor`);
  }, [currentProject, projectId, displayName, selectProject, navigate]);

  return (
    <div className="flex flex-col h-screen bg-canvas font-sans">
      <AppHeader />

      <main className="flex-1 overflow-y-auto px-6 py-8 max-w-6xl mx-auto w-full">
        {/* 頁首：返回 + 標題 */}
        <div className="flex items-center gap-3 mb-6">
          <IconButton onClick={() => navigate('/')} title="返回專案列表">
            <FaArrowLeft size={14} />
          </IconButton>
          <div>
            <h1 className="text-xl font-bold text-ink">{displayName}</h1>
            <p className="text-xs text-ink-faint mt-0.5">審閱素材、設定 Simple/Complex 策略，再開始分析</p>
          </div>
        </div>

        {/* 錯誤訊息 */}
        {errorMsg && (
          <div className="flex items-center gap-2 mb-4 px-4 py-3 bg-danger/10 border border-danger/30 rounded-xl text-danger text-sm">
            <FaExclamationCircle className="shrink-0" />
            <span className="flex-1">{errorMsg}</span>
            <button onClick={() => setErrorMsg('')} className="text-ink-faint hover:text-ink transition-colors">✕</button>
          </div>
        )}

        {preparing ? (
          /* 準備中：背景仍在下載 / 標準化素材，顯示轉圈、不渲染工具列與格線（避免閃出未處理的原始卡片）*/
          <div className="flex flex-col items-center gap-3 py-24 text-ink-faint">
            <Spinner />
            <p className="text-sm">正在下載並處理素材，請稍候…</p>
            <p className="text-xs text-ink-faint/70">背景正在從 Google Drive 下載並標準化素材，完成後會自動顯示。</p>
          </div>
        ) : (
          <>
            {/* 進度條（工作進行中才顯示）*/}
            <ProgressOverlay visible={jobRunning} done={progress.done} total={progress.total} />

            {/* 素材統計列：照片數 / 影片數 / 影片總時長（有素材才顯示）*/}
            {assets.length > 0 && (
              <AssetSummaryBar
                imageCount={summary.imageCount}
                videoCount={summary.videoCount}
                totalVideoDuration={summary.totalVideoDuration}
              />
            )}

            {/* 工具列：選取模式顯示情境列，否則顯示預設列（同位置、等高，切換不跳動）*/}
            {selectionMode ? (
              <SelectionToolbar
                total={assets.length}
                selectedCount={selected.size}
                jobRunning={jobRunning}
                onExitSelection={exitSelection}
                onSelectAll={() => selectAll(assets.map((a) => a.path))}
                onClearSelection={clearSelection}
                onBulkStrategy={(strategy) => bulkStrategy(strategy, [...selected])}
                onReanalyzeSelected={() => reanalyzeSelected([...selected])}
              />
            ) : (
              <BulkActionBar
                total={assets.length}
                jobRunning={jobRunning}
                onEnterSelection={handleEnterSelection}
                onReanalyzeAll={reanalyzeAll}
                onGoEditor={goEditor}
                onGenerate={generate}
              />
            )}

            {/* 載入中 */}
            {isLoading && assets.length === 0 && (
              <div className="flex flex-col items-center gap-3 py-20 text-ink-faint">
                <Spinner />
                <p className="text-sm">載入素材中...</p>
              </div>
            )}

            {/* 空狀態 */}
            {!isLoading && assets.length === 0 ? (
              <EmptyState
                icon={<FaImages />}
                title="這個專案還沒有素材"
                description="從 Google Drive 同步的素材下載完成後即可在此審閱。"
              />
            ) : (
              <AssetGrid
                assets={assets}
                selected={selected}
                liveStatusMap={liveStatusMap}
                jobRunning={jobRunning}
                selectionMode={selectionMode}
                onToggleSelect={toggleSelect}
                onToggleStrategy={setStrategy}
                onOpenDetail={openDetail}
              />
            )}
          </>
        )}

        {/* 素材詳情彈窗（非選取模式點卡片開啟）：呈現完整媒體 + Phase 1 資訊 */}
        {detailPath && (
          <AssetDetailModal
            projectName={projectId}
            path={detailPath}
            filename={detailAsset?.filename || detailPath}
            thumbnailUrl={detailAsset?.thumbnail_url}
            onClose={closeDetail}
          />
        )}
      </main>
    </div>
  );
}
