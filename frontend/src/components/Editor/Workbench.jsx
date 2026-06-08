import React, { useState } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import VideoPlayer from '../RemotionPlayer/VideoPlayer';
import Inspector from './Inspector';
import SnapshotPanel from './SnapshotPanel';
import TimelinePanel from './Timeline/TimelinePanel';
import AiCopilotDrawer from './AiCopilotDrawer';
import RegeneratePanel from './RegeneratePanel';
import { Button, IconButton } from '../ui';
import { FaUndo, FaRedo, FaSyncAlt, FaRobot, FaSpinner } from 'react-icons/fa';

// 三欄寬度：左右用固定寬度（清單 / Inspector 維持可讀），中央影片吃滿剩餘空間並隨螢幕放大。
// 9:16 預覽受高度限制，故不需各 1/3；窄側欄 + 寬中欄能給預覽最多呼吸空間。
const SNAPSHOT_WIDTH = 'w-[260px]';
const INSPECTOR_WIDTH = 'w-[360px]';

/**
 * Workbench：兩階段中的「生成後」編輯工作台（三欄版型）。
 *
 * 版面：頂部工具列（復原 / 重做 / 重新生成 / AI）＋ 三欄（左：版本快照、中：影片預覽、
 * 右：Inspector 屬性工作台）＋ 底部全寬時間軸；AI copilot 為彈窗、重新生成為彈窗。
 * 對應設計文件 §1 目標版面與使用者指定的 1/3 三欄配置。
 */
export default function Workbench() {
  const isProcessing = useBlueprintStore((s) => s.isProcessing);
  const errorMsg = useBlueprintStore((s) => s.errorMsg);
  const canUndo = useBlueprintStore((s) => s.history.past.length > 0);
  const canRedo = useBlueprintStore((s) => s.history.future.length > 0);
  const undo = useBlueprintStore((s) => s.undo);
  const redo = useBlueprintStore((s) => s.redo);

  const [showRegenerate, setShowRegenerate] = useState(false);
  const [showCopilot, setShowCopilot] = useState(false);

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-canvas">
      {/* 工具列 */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-surface shrink-0">
        <IconButton tone="neutral" title="復原 (Undo)" disabled={!canUndo} onClick={undo}>
          <FaUndo size={13} />
        </IconButton>
        <IconButton tone="neutral" title="重做 (Redo)" disabled={!canRedo} onClick={redo}>
          <FaRedo size={13} />
        </IconButton>

        <div className="flex-1" />

        <Button variant="secondary" size="sm" leftIcon={<FaSyncAlt size={11} />} onClick={() => setShowRegenerate(true)}>
          重新生成
        </Button>
        <Button
          variant={showCopilot ? 'primary' : 'secondary'}
          size="sm"
          leftIcon={<FaRobot size={12} />}
          onClick={() => setShowCopilot((v) => !v)}
        >
          AI
        </Button>
      </div>

      {/* 系統錯誤提示 */}
      {errorMsg && (
        <div className="bg-danger/15 text-danger px-4 py-2 text-sm font-medium shrink-0 border-b border-danger/30">
          ⚠️ {errorMsg}
        </div>
      )}

      {/* 工具列以下的編輯區（relative：作為生成遮罩的定位基準）*/}
      <div className="relative flex-1 flex flex-col overflow-hidden">
        {/* 三欄：左 版本快照（窄）/ 中 影片（吃滿）/ 右 Inspector（窄）*/}
        <div className="flex flex-1 overflow-hidden">
          <div className={`${SNAPSHOT_WIDTH} shrink-0 h-full`}>
            <SnapshotPanel />
          </div>
          <div className="flex-1 min-w-0 h-full relative">
            <VideoPlayer />
          </div>
          <div className={`${INSPECTOR_WIDTH} shrink-0 h-full`}>
            <Inspector onRequestRegenerate={() => setShowRegenerate(true)} />
          </div>
        </div>

        {/* 底部時間軸（全寬）*/}
        <TimelinePanel />

        {/* AI copilot 抽屜（右側可收合，覆蓋於編輯區之上）*/}
        <AiCopilotDrawer open={showCopilot} onClose={() => setShowCopilot(false)} />

        {/* 生成中遮罩 */}
        {isProcessing && (
          <div className="absolute inset-0 bg-canvas/80 backdrop-blur-sm z-40 flex flex-col items-center justify-center">
            <FaSpinner className="animate-spin text-accent text-6xl mb-6" />
            <h3 className="text-ink font-bold text-xl tracking-widest">AI 導演思考中...</h3>
            <p className="text-ink-muted text-sm mt-3 animate-pulse">正在精確計算時間軸與混音策略</p>
          </div>
        )}
      </div>

      {/* 重新生成彈窗 */}
      {showRegenerate && <RegeneratePanel onClose={() => setShowRegenerate(false)} />}
    </div>
  );
}
