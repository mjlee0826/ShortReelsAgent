import { useCallback, useEffect, useRef, useState } from 'react';
import { apiService } from '../services/api.service';
import { extractErrorMessage } from '../utils/errorMessage';
import { PROGRESS_EVENT } from '../constants/events';
import useProgressSocket from './useProgressSocket';

// 視為「需要重跑 Phase 1」的素材狀態（開始生成時挑這些 + dirty）
const STATUS_UNPROCESSED = 'unprocessed';

// 專案 Phase 1 背景狀態值（對齊後端 ingestion_engine/models.py）：素材頁據此判斷「準備中」
// （初次建立資料夾正在下載 / 標準化素材，尚未收斂）以顯示轉圈、隱藏未處理的原始卡片
const PHASE1_STATUS_PENDING = 'pending';
const PHASE1_STATUS_INGESTING = 'ingesting';
const PHASE1_STATUS_PROCESSING = 'processing';
// 「準備中」（尚未收斂）的狀態集合：等待開始（pending）、下載 / 標準化中（ingesting），
// 以及分析剛起步但 WS job 尚未掛上的短暫 processing 視窗（掛上後 jobRunning 即接管，不再算準備中）
const PREPARING_STATUSES = new Set([
  PHASE1_STATUS_PENDING, PHASE1_STATUS_INGESTING, PHASE1_STATUS_PROCESSING,
]);
// 準備中時的輪詢間隔（毫秒）：背景在下載 / 標準化，週期查詢狀態，收斂即停
const PREPARING_POLL_INTERVAL_MS = 3000;

// 即時覆蓋層的卡片顯示狀態（具名常數，避免 magic string）
const LIVE_STATUS_PROCESSING = 'processing';
const LIVE_STATUS_ERROR = 'error';

/**
 * useProjectAssets：素材頁的資料層 hook（單一職責：素材讀取與 Phase 1 分析生命週期）。
 *
 * 封裝素材清單抓取、WebSocket 即時進度、Phase 1「準備中」輪詢，以及會變更素材的操作
 * （策略切換 / 批量策略 / 重新分析 / 開始生成）。頁面只需組合本 hook 與選取 hook 後渲染。
 *
 * @param {string} projectId 專案資料夾名稱
 * @param {object} [options]
 * @param {string} [options.initialError] 初始錯誤提示（例如由編輯器跳轉帶入的 notice）
 * @param {() => void} [options.onJobStart] 任一分析 job 啟動時呼叫（頁面用來重置選取）
 * @returns 素材狀態與操作集合
 */
export default function useProjectAssets(projectId, { initialError = '', onJobStart } = {}) {
  const [assets, setAssets] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(() => initialError);
  // WebSocket 即時狀態覆蓋層：path（relpath 身分）→ { status, stage }；與事件的 asset_id 對齊
  const [liveStatusMap, setLiveStatusMap] = useState({});
  const [jobRunning, setJobRunning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  // 已完成（pipeline_finish）的素材集合，用來累計進度，避免重複事件灌爆計數
  const finishedRef = useRef(new Set());
  // 專案 Phase 1 背景狀態（pending/processing/done/skipped/failed/null）：判斷是否「準備中」用
  const [phase1Status, setPhase1Status] = useState(null);

  // 準備中：背景仍在下載 / 標準化（phase1_status 未收斂）且尚未連上 WS 分析 job → 顯示轉圈、不渲染格線
  const preparing = !jobRunning && PREPARING_STATUSES.has(phase1Status);

  // ── 載入素材 ───────────────────────────────────────────────────────────────
  // 可重用的 refetch：供 WebSocket job 結束後取最終持久化狀態（在事件回呼內呼叫，非 effect）。
  // 首次載入靠 isLoading 初始為 true 顯示 spinner；之後的 refetch 靜默更新、不翻 spinner。
  const loadAssets = useCallback(async () => {
    try {
      const data = await apiService.fetchAssets(projectId);
      setAssets(data);
      setErrorMsg('');
    } catch (error) {
      setErrorMsg(`載入素材失敗：${extractErrorMessage(error)}`);
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  // ── WebSocket 進度事件 ──────────────────────────────────────────────────────
  const handleProgressEvent = useCallback((event) => {
    const { event_type: type, asset_id: assetId, stage_name: stage } = event;
    // 工作流終端：清即時層、回抓最終持久化狀態
    if (type === PROGRESS_EVENT.JOB_FINISHED || type === PROGRESS_EVENT.JOB_ERROR) {
      setJobRunning(false);
      setLiveStatusMap({});
      finishedRef.current = new Set();
      setProgress({ done: 0, total: 0 });
      if (type === PROGRESS_EVENT.JOB_ERROR) setErrorMsg(`分析失敗：${event.error || '未知錯誤'}`);
      loadAssets();
      return;
    }
    if (!assetId) return;
    if (type === PROGRESS_EVENT.PIPELINE_FINISH) {
      finishedRef.current.add(assetId);
      setProgress((p) => ({ ...p, done: finishedRef.current.size }));
      return;
    }
    if (type === PROGRESS_EVENT.STAGE_ERROR) {
      setLiveStatusMap((m) => ({ ...m, [assetId]: { status: LIVE_STATUS_ERROR, stage } }));
      return;
    }
    // pipeline_start / stage_start / stage_finish → 處理中 + 當前 stage
    setLiveStatusMap((m) => ({
      ...m,
      [assetId]: { status: LIVE_STATUS_PROCESSING, stage: stage || m[assetId]?.stage || null },
    }));
  }, [loadAssets]);

  // WS 在「未收到終端事件」下異常斷線（如後端重啟）：清即時層並回抓最終持久化狀態，避免卡在處理中
  const handleSocketClosed = useCallback(() => {
    setJobRunning(false);
    setLiveStatusMap({});
    finishedRef.current = new Set();
    setProgress({ done: 0, total: 0 });
    loadAssets();
  }, [loadAssets]);

  const connect = useProgressSocket(handleProgressEvent, handleSocketClosed);

  // 啟動一個 Phase 1 分析 job：先把涉及素材標處理中，拿到 job_id 後訂閱 WS。
  // involvedPaths 為素材 relpath 身分清單，與後續 WebSocket 事件的 asset_id 對齊。
  const startJob = useCallback(async (jobPromise, involvedPaths) => {
    setErrorMsg('');
    setJobRunning(true);
    // 開工即重置選取（處理中不應再停留在選取狀態）—— 實際清除交由頁面（onJobStart）
    onJobStart?.();
    finishedRef.current = new Set();
    setProgress({ done: 0, total: involvedPaths.length });
    const initialLive = {};
    involvedPaths.forEach((p) => { initialLive[p] = { status: LIVE_STATUS_PROCESSING, stage: null }; });
    setLiveStatusMap(initialLive);
    try {
      const { job_id: jobId } = await jobPromise;
      await connect(jobId);
    } catch (error) {
      const msg = extractErrorMessage(error);
      // 409 = 後端已有 Phase 1 在跑（雲端同步 / 另一次觸發）：非失敗，直接顯示「素材分析中，請稍候」
      setErrorMsg(error.response?.status === 409 ? msg : `啟動分析失敗：${msg}`);
      setJobRunning(false);
      setLiveStatusMap({});
      setProgress({ done: 0, total: 0 });
    }
  }, [connect, onJobStart]);

  // 偵測到背景同步已在跑的 Phase 1 job：先抓最新素材，再直接訂閱其 WS（不重新觸發分析，job 已在後端跑）。
  //
  // 關鍵：初次同步時掛載當下的素材清單可能仍為空——標準化前 list_assets 會隱藏待處理的 raw，故 assets
  // 一直是 []；待標準化完成、背景翻成 processing 並 publish job_id，輪詢才會走到這裡。此時 _std 卡片已可
  // 取得，必須重抓一次：否則格線會空白（無卡片可掛處理中動畫）、進度條 total 也算成 0，直到 job 結束才補上。
  // 重抓後才據最新素材算出待處理（dirty / 未處理）的 relpath 初始化進度條與每張卡片動畫；連線後 replay
  // buffer 會補播已發生的事件，使進度即時追上。
  const attachToRunningJob = useCallback(async (jobId) => {
    setErrorMsg('');
    setJobRunning(true);
    finishedRef.current = new Set();
    // 接上 job 前先抓最新素材（標準化後的 _std 卡片）：讓格線立即顯示卡片，pendingPaths / 進度條 total 才正確
    let pendingPaths = [];
    try {
      const data = await apiService.fetchAssets(projectId);
      setAssets(data);
      pendingPaths = data
        .filter((a) => a.dirty || a.status === STATUS_UNPROCESSED)
        .map((a) => a.path);
    } catch {
      // 抓素材失敗不致命：以空清單續接 WS，replay buffer 仍會補播進度
    }
    setProgress({ done: 0, total: pendingPaths.length });
    const initialLive = {};
    pendingPaths.forEach((p) => { initialLive[p] = { status: LIVE_STATUS_PROCESSING, stage: null }; });
    setLiveStatusMap(initialLive);
    try {
      await connect(jobId);
    } catch {
      setJobRunning(false);
      setLiveStatusMap({});
      setProgress({ done: 0, total: 0 });
    }
  }, [connect, projectId]);

  // 掛載 / 換專案時抓素材：setState 全落在 promise 回呼（非同步）以符合 effect 規範；
  // active 旗標避免請求未回前元件已卸載而對舊狀態 setState。素材載入後再查 Phase 1 進度：
  // 只要有進行中的 Phase 1 job（active_job_id；後端已校驗孤兒，重啟後回 null），就訂閱其 WS 補上
  // 即時進度——涵蓋背景同步預跑與素材頁手動觸發的「重新分析 / 開始生成」，使重整後進度條能接回。
  useEffect(() => {
    let active = true;
    apiService.fetchAssets(projectId)
      .then((data) => {
        if (!active) return undefined;
        setAssets(data);
        // 進度查詢失敗不致命（素材已載入）：catch 吞掉，僅不顯示背景進度
        return apiService.fetchPhase1Progress(projectId)
          .then((p) => {
            if (!active) return;
            // 記錄背景狀態：未收斂（pending/processing）且無 job 時，由下方輪詢 effect 接手顯示「準備中」
            setPhase1Status(p.phase1_status);
            if (p.active_job_id) {
              attachToRunningJob(p.active_job_id);
            }
          })
          .catch(() => {});
      })
      .catch((error) => {
        if (active) setErrorMsg(`載入素材失敗：${extractErrorMessage(error)}`);
      })
      .finally(() => { if (active) setIsLoading(false); });
    return () => { active = false; };
  }, [projectId, attachToRunningJob]);

  // 準備中（背景下載 / 標準化進行中、尚未連上 WS job）時週期輪詢 Phase 1 狀態，直到收斂：
  // - 出現 active_job_id（背景開始感知分析）→ 改訂閱 WS 進度條（attachToRunningJob 內部會重抓素材）；
  // - 收斂為 skipped/done/failed → 重新載入素材（此時 .mov/.heic 已轉成可預覽的 _std）並結束準備中。
  useEffect(() => {
    if (!preparing) return undefined;
    let active = true;
    const timer = setInterval(async () => {
      try {
        const p = await apiService.fetchPhase1Progress(projectId);
        if (!active) return;
        setPhase1Status(p.phase1_status);
        if (p.active_job_id) {
          attachToRunningJob(p.active_job_id);
        } else if (!PREPARING_STATUSES.has(p.phase1_status)) {
          loadAssets();
        }
      } catch {
        // 輪詢失敗不致命：下一輪再試
      }
    }, PREPARING_POLL_INTERVAL_MS);
    return () => { active = false; clearInterval(timer); };
  }, [preparing, projectId, attachToRunningJob, loadAssets]);

  // ── 策略切換 ───────────────────────────────────────────────────────────────
  /** 切換單一素材策略（以 relpath 身分 path 為鍵呼叫 API 與比對更新）。 */
  const setStrategy = useCallback(async (path, strategy) => {
    try {
      const updated = await apiService.setAssetStrategy(projectId, path, strategy);
      setAssets((arr) => arr.map((a) => (a.path === path ? updated : a)));
    } catch (error) {
      setErrorMsg(`更新策略失敗：${extractErrorMessage(error)}`);
    }
  }, [projectId]);

  /** 批量設定策略（paths 由呼叫端帶入，例如目前選取）。 */
  const bulkStrategy = useCallback(async (strategy, paths) => {
    const targets = [...paths];
    if (targets.length === 0) return;
    try {
      const results = await Promise.all(
        targets.map((p) => apiService.setAssetStrategy(projectId, p, strategy))
      );
      const byPath = new Map(results.map((r) => [r.path, r]));
      setAssets((arr) => arr.map((a) => byPath.get(a.path) || a));
    } catch (error) {
      setErrorMsg(`批量設定策略失敗：${extractErrorMessage(error)}`);
    }
  }, [projectId]);

  // ── 重新分析 / 開始生成 ─────────────────────────────────────────────────────
  /** 重新分析選取的素材（paths 由呼叫端帶入）。 */
  const reanalyzeSelected = useCallback((paths) => {
    const ids = [...paths];
    if (ids.length === 0) return;
    startJob(apiService.reanalyzeAssets(projectId, ids), ids);
  }, [projectId, startJob]);

  /** 重新分析全部素材。 */
  const reanalyzeAll = useCallback(() => {
    const ids = assets.map((a) => a.path);
    startJob(apiService.reanalyzeAssets(projectId, null), ids);
  }, [projectId, assets, startJob]);

  /** 開始生成：只重跑 dirty + 未處理素材；全部已是最新則提示不動作。 */
  const generate = useCallback(() => {
    const pending = assets
      .filter((a) => a.dirty || a.status === STATUS_UNPROCESSED)
      .map((a) => a.path);
    if (pending.length === 0) {
      setErrorMsg('沒有需要分析的素材（全部已是最新；可改用「重新分析」）。');
      return;
    }
    startJob(apiService.startAssetGenerate(projectId, null), pending);
  }, [projectId, assets, startJob]);

  return {
    assets,
    isLoading,
    errorMsg,
    setErrorMsg,
    liveStatusMap,
    jobRunning,
    progress,
    preparing,
    setStrategy,
    bulkStrategy,
    reanalyzeSelected,
    reanalyzeAll,
    generate,
  };
}
