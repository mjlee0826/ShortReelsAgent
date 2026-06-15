import React from 'react';
import ChatBox from '../RightPanel/ChatBox';
import { IconButton } from '../ui';
import { FaTimes, FaRobot } from 'react-icons/fa';
import useResizableWidth from '../../hooks/useResizableWidth';
import {
  COPILOT_DEFAULT_WIDTH,
  COPILOT_MIN_WIDTH,
  COPILOT_MAX_WIDTH,
  COPILOT_WIDTH_STORAGE_KEY,
} from '../../constants/copilotDrawer';

/**
 * AiCopilotDrawer：可收合且可拖曳調整寬度的 AI 導演對話抽屜（copilot）。
 *
 * 由工作台工具列「💬 AI」切換，從右側滑入、覆蓋於編輯區之上；收合時移出畫面並停用互動。
 * 寬度交由 useResizableWidth 管理：拖左緣把手即時調整、雙擊把手還原預設、偏好存 localStorage。
 * 對話式微調仍走 submitPrompt(true)（重新生成邊界），結果會推進 Undo 快照。內容沿用 ChatBox。
 * z 層級高於生成遮罩（z-40）：生成中抽屜仍可見，使用者能即時看導演 agentic loop 的思考串流與旁白。
 * @param {boolean} open 是否展開
 * @param {() => void} onClose 收合抽屜
 */
export default function AiCopilotDrawer({ open, onClose }) {
  const { width, isResizing, onResizeStart, resetWidth } = useResizableWidth({
    defaultWidth: COPILOT_DEFAULT_WIDTH,
    minWidth: COPILOT_MIN_WIDTH,
    maxWidth: COPILOT_MAX_WIDTH,
    storageKey: COPILOT_WIDTH_STORAGE_KEY,
  });

  return (
    <div
      // 寬度改由 inline style 控制（可拖曳）；拖曳中關閉位移過場避免跟手延遲
      style={{ width: `${width}px` }}
      className={`absolute top-0 right-0 h-full max-w-full bg-surface border-l border-border shadow-2xl z-50 flex flex-col ${
        isResizing ? '' : 'transition-transform duration-300'
      } ${open ? 'translate-x-0' : 'translate-x-full pointer-events-none'}`}
    >
      {/* 左緣拖曳把手：靠左錨定的細條，hover / 拖曳時高亮；雙擊還原預設寬度 */}
      <div
        role="separator"
        aria-orientation="vertical"
        title="拖曳調整寬度（雙擊還原）"
        onMouseDown={onResizeStart}
        onDoubleClick={resetWidth}
        className={`absolute top-0 left-0 h-full w-1.5 -ml-0.5 cursor-col-resize z-10 transition-colors hover:bg-accent/40 ${
          isResizing ? 'bg-accent/60' : 'bg-transparent'
        }`}
      />

      {/* 抽屜標題列 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-2/40 shrink-0">
        <h3 className="text-base font-bold text-ink flex items-center gap-2">
          <FaRobot className="text-accent" /> AI 導演 Copilot
        </h3>
        <IconButton tone="neutral" title="收合" onClick={onClose}>
          <FaTimes size={14} />
        </IconButton>
      </div>

      {/* 對話內容 */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <ChatBox />
      </div>
    </div>
  );
}
