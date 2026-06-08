import React from 'react';
import ChatBox from '../RightPanel/ChatBox';
import { IconButton } from '../ui';
import { FaTimes, FaRobot } from 'react-icons/fa';

// 抽屜寬度
const DRAWER_WIDTH = 'w-[440px]';

/**
 * AiCopilotDrawer：可收合的 AI 導演對話抽屜（copilot）。
 *
 * 由工作台工具列「💬 AI」切換，從右側滑入、覆蓋於編輯區之上；收合時移出畫面並停用互動。
 * 對話式微調仍走 submitPrompt(true)（重新生成邊界），結果會推進 Undo 快照。內容沿用 ChatBox。
 * @param {boolean} open 是否展開
 * @param {() => void} onClose 收合抽屜
 */
export default function AiCopilotDrawer({ open, onClose }) {
  return (
    <div
      className={`absolute top-0 right-0 h-full ${DRAWER_WIDTH} max-w-full bg-surface border-l border-border shadow-2xl z-30 flex flex-col transition-transform duration-300 ${
        open ? 'translate-x-0' : 'translate-x-full pointer-events-none'
      }`}
    >
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
