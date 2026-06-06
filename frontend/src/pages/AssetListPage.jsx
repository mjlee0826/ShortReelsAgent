import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { FaArrowLeft, FaExclamationCircle, FaImages } from 'react-icons/fa';
import { apiService } from '../services/api.service';
import useProjectStore from '../store/useProjectStore';
import useProgressSocket from '../hooks/useProgressSocket';
import AppHeader from '../components/AppHeader/AppHeader';
import AssetGrid from '../components/AssetGrid/AssetGrid';
import AssetDetailModal from '../components/AssetGrid/AssetDetailModal';
import BulkActionBar from '../components/AssetGrid/BulkActionBar';
import SelectionToolbar from '../components/AssetGrid/SelectionToolbar';
import ProgressOverlay from '../components/AssetGrid/ProgressOverlay';
import { IconButton, Spinner, EmptyState } from '../components/ui';

// 視為「需要重跑 Phase 1」的素材狀態（開始生成時挑這些 + dirty）
const STATUS_UNPROCESSED = 'unprocessed';

/**
 * AssetListPage：專案素材管理頁（Layer 5）。
 *
 * 審閱素材縮圖與狀態、逐檔切換 Simple/Complex 策略、觸發 Phase 1 重新分析 / 開始生成,並以
 * WebSocket 即時把每張卡片更新為「處理中 + 當前 stage」。完整生成(Phase 2–4)仍由編輯器負責。
 */
export default function AssetListPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const currentProject = useProjectStore((s) => s.currentProject);
  const selectProject = useProjectStore((s) => s.selectProject);

  const [assets, setAssets] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');
  const [selected, setSelected] = useState(new Set());
  // 選取模式：開啟後卡片才顯示勾選框、整卡可點選（與 selected 為獨立關注點）
  const [selectionMode, setSelectionMode] = useState(false);
  // WebSocket 即時狀態覆蓋層：path（relpath 身分）→ { status, stage }；與事件的 asset_id 對齊
  const [liveStatusMap, setLiveStatusMap] = useState({});
  const [jobRunning, setJobRunning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  // 已完成（pipeline_finish）的素材集合,用來累計進度,避免重複事件灌爆計數
  const finishedRef = useRef(new Set());
  // 詳情彈窗：null = 關閉；非 null = 開啟該素材詳情（存 relpath 身分；非選取模式點卡片開啟）
  const [detailPath, setDetailPath] = useState(null);

  const displayName =
    currentProject?.name === projectId ? currentProject.display_name : projectId;

  // 詳情彈窗對應的素材（以 relpath 身分查找）；供彈窗取顯示檔名與縮圖後備
  const detailAsset = detailPath ? assets.find((a) => a.path === detailPath) : null;

  // ── 載入素材 ───────────────────────────────────────────────────────────────
  // 可重用的 refetch：供 WebSocket job 結束後取最終持久化狀態（在事件回呼內呼叫，非 effect）。
  // 首次載入靠 isLoading 初始為 true 顯示 spinner；之後的 refetch 靜默更新、不翻 spinner。
  const loadAssets = useCallback(async () => {
    try {
      const data = await apiService.fetchAssets(projectId);
      setAssets(data);
      setErrorMsg('');
    } catch (error) {
      const msg = error.response?.data?.detail || error.message || String(error);
      setErrorMsg(`載入素材失敗：${msg}`);
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  // 掛載 / 換專案時抓素材：setState 全落在 promise 回呼（非同步）以符合 effect 規範；
  // active 旗標避免請求未回前元件已卸載而對舊狀態 setState。
  useEffect(() => {
    let active = true;
    apiService.fetchAssets(projectId)
      .then((data) => { if (active) setAssets(data); })
      .catch((error) => {
        if (active) {
          const msg = error.response?.data?.detail || error.message || String(error);
          setErrorMsg(`載入素材失敗：${msg}`);
        }
      })
      .finally(() => { if (active) setIsLoading(false); });
    return () => { active = false; };
  }, [projectId]);

  // ── WebSocket 進度事件 ──────────────────────────────────────────────────────
  const handleProgressEvent = useCallback((event) => {
    const { event_type: type, asset_id: assetId, stage_name: stage } = event;
    // 工作流終端：清即時層、回抓最終持久化狀態
    if (type === 'job_finished' || type === 'job_error') {
      setJobRunning(false);
      setLiveStatusMap({});
      finishedRef.current = new Set();
      setProgress({ done: 0, total: 0 });
      if (type === 'job_error') setErrorMsg(`分析失敗：${event.error || '未知錯誤'}`);
      loadAssets();
      return;
    }
    if (!assetId) return;
    if (type === 'pipeline_finish') {
      finishedRef.current.add(assetId);
      setProgress((p) => ({ ...p, done: finishedRef.current.size }));
      return;
    }
    if (type === 'stage_error') {
      setLiveStatusMap((m) => ({ ...m, [assetId]: { status: 'error', stage } }));
      return;
    }
    // pipeline_start / stage_start / stage_finish → 處理中 + 當前 stage
    setLiveStatusMap((m) => ({
      ...m,
      [assetId]: { status: 'processing', stage: stage || m[assetId]?.stage || null },
    }));
  }, [loadAssets]);

  const connect = useProgressSocket(handleProgressEvent);

  // 啟動一個 Phase 1 分析 job：先把涉及素材標處理中,拿到 job_id 後訂閱 WS
  // involvedPaths 為素材 relpath 身分清單，與後續 WebSocket 事件的 asset_id 對齊
  const startJob = useCallback(async (jobPromise, involvedPaths) => {
    setErrorMsg('');
    setJobRunning(true);
    // 開工即清空選取並退出選取模式（處理中不應再停留在選取狀態）
    setSelected(new Set());
    setSelectionMode(false);
    finishedRef.current = new Set();
    setProgress({ done: 0, total: involvedPaths.length });
    const initialLive = {};
    involvedPaths.forEach((p) => { initialLive[p] = { status: 'processing', stage: null }; });
    setLiveStatusMap(initialLive);
    try {
      const { job_id: jobId } = await jobPromise;
      await connect(jobId);
    } catch (error) {
      const msg = error.response?.data?.detail || error.message || String(error);
      setErrorMsg(`啟動分析失敗：${msg}`);
      setJobRunning(false);
      setLiveStatusMap({});
      setProgress({ done: 0, total: 0 });
    }
  }, [connect]);

  // ── 選取 ───────────────────────────────────────────────────────────────────
  // 選取集合一律存素材 relpath 身分（asset.path）
  const toggleSelect = useCallback((path) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelected(new Set(assets.map((a) => a.path)));
  }, [assets]);

  const clearSelection = useCallback(() => setSelected(new Set()), []);

  // 進入 / 離開選取模式；離開時一併清空選取
  const enterSelection = useCallback(() => {
    setSelectionMode(true);
    setDetailPath(null); // 進選取模式即關閉詳情，避免兩模式狀態交疊
  }, []);
  const exitSelection = useCallback(() => {
    setSelectionMode(false);
    clearSelection();
  }, [clearSelection]);

  // ── 詳情彈窗 ─────────────────────────────────────────────────────────────────
  const openDetail = useCallback((path) => setDetailPath(path), []);
  const closeDetail = useCallback(() => setDetailPath(null), []);

  // ── 策略切換 ───────────────────────────────────────────────────────────────
  // 以 relpath 身分（path）為鍵呼叫 API 與比對更新
  const handleToggleStrategy = useCallback(async (path, strategy) => {
    try {
      const updated = await apiService.setAssetStrategy(projectId, path, strategy);
      setAssets((arr) => arr.map((a) => (a.path === path ? updated : a)));
    } catch (error) {
      const msg = error.response?.data?.detail || error.message || String(error);
      setErrorMsg(`更新策略失敗：${msg}`);
    }
  }, [projectId]);

  const handleBulkStrategy = useCallback(async (strategy) => {
    const targets = [...selected];
    if (targets.length === 0) return;
    try {
      const results = await Promise.all(
        targets.map((p) => apiService.setAssetStrategy(projectId, p, strategy))
      );
      const byPath = new Map(results.map((r) => [r.path, r]));
      setAssets((arr) => arr.map((a) => byPath.get(a.path) || a));
    } catch (error) {
      const msg = error.response?.data?.detail || error.message || String(error);
      setErrorMsg(`批量設定策略失敗：${msg}`);
    }
  }, [projectId, selected]);

  // ── 重新分析 / 開始生成 ─────────────────────────────────────────────────────
  const handleReanalyzeSelected = useCallback(() => {
    const ids = [...selected];
    if (ids.length === 0) return;
    startJob(apiService.reanalyzeAssets(projectId, ids), ids);
  }, [projectId, selected, startJob]);

  const handleReanalyzeAll = useCallback(() => {
    const ids = assets.map((a) => a.path);
    startJob(apiService.reanalyzeAssets(projectId, null), ids);
  }, [projectId, assets, startJob]);

  const handleGenerate = useCallback(() => {
    // 開始生成只重跑 dirty + 未處理素材；全部已是最新則提示不動作
    const pending = assets
      .filter((a) => a.dirty || a.status === STATUS_UNPROCESSED)
      .map((a) => a.path);
    if (pending.length === 0) {
      setErrorMsg('沒有需要分析的素材（全部已是最新；可改用「重新分析」）。');
      return;
    }
    startJob(apiService.startAssetGenerate(projectId, null), pending);
  }, [projectId, assets, startJob]);

  const goEditor = useCallback(() => {
    // 確保編輯器取得當前專案（素材頁可能由重新整理直接進入,store 尚未選定）
    if (currentProject?.name !== projectId) {
      selectProject({ name: projectId, display_name: displayName });
    }
    navigate('/editor');
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

        {/* 進度條（工作進行中才顯示）*/}
        <ProgressOverlay visible={jobRunning} done={progress.done} total={progress.total} />

        {/* 工具列：選取模式顯示情境列，否則顯示預設列（同位置、等高，切換不跳動）*/}
        {selectionMode ? (
          <SelectionToolbar
            total={assets.length}
            selectedCount={selected.size}
            jobRunning={jobRunning}
            onExitSelection={exitSelection}
            onSelectAll={selectAll}
            onClearSelection={clearSelection}
            onBulkStrategy={handleBulkStrategy}
            onReanalyzeSelected={handleReanalyzeSelected}
          />
        ) : (
          <BulkActionBar
            total={assets.length}
            jobRunning={jobRunning}
            onEnterSelection={enterSelection}
            onReanalyzeAll={handleReanalyzeAll}
            onGoEditor={goEditor}
            onGenerate={handleGenerate}
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
            onToggleStrategy={handleToggleStrategy}
            onOpenDetail={openDetail}
          />
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
