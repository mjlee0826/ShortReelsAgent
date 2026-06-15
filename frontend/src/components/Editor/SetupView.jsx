import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import GenerationForm from './GenerationForm';
import ChatBox from '../RightPanel/ChatBox';
import { FaMagic } from 'react-icons/fa';

const MUSIC_SEARCH_COPYRIGHT = 'search_copyright';

/**
 * SetupView：blueprint 尚未產生時的「生成前」畫面（agentic 改造後）。
 *
 * 上半為生成表單（設定 + 初次指令）；一旦開始生成（或有對話 / 導演中途提問），下半即時呈現導演 agentic
 * loop 的思考串流、工具旁白與 ask_user 提問（共用 :component:`ChatBox`），讓初次生成也看得到導演的認知
 * 與對話對齊。生成成功後 EditorPage 切到 Workbench。
 */
export default function SetupView() {
  const { errorMsg, musicStrategy, isProcessing, chatHistory, pendingClarification } = useBlueprintStore();
  // 有對話 / 處理中 / 待回答 → 顯示導演對話面板（初次生成的思考串流與提問都在這裡）
  const showChat = isProcessing || (chatHistory && chatHistory.length > 0) || !!pendingClarification;

  return (
    <div className="flex-1 overflow-y-auto bg-canvas">
      <div className="max-w-xl mx-auto px-6 py-12">
        {/* 標題區 */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-accent/15 text-accent flex items-center justify-center text-2xl mx-auto mb-4">
            <FaMagic />
          </div>
          <h1 className="text-2xl font-bold text-ink tracking-wide">AI 導演工作台</h1>
          <p className="text-sm text-ink-faint mt-2">描述你的需求，讓 AI 導演為你剪出第一版短影音</p>
        </div>

        {/* 系統錯誤提示 */}
        {errorMsg && (
          <div className="bg-danger/15 text-danger px-4 py-3 text-sm font-medium rounded-xl border border-danger/30 mb-5">
            ⚠️ {errorMsg}
          </div>
        )}

        {/* 版權風險提示（search_copyright 策略時顯示）*/}
        {musicStrategy === MUSIC_SEARCH_COPYRIGHT && (
          <div className="bg-warning/10 border-l-4 border-warning text-warning px-4 py-3 text-sm rounded-r-xl mb-5">
            ⚠️ 此配樂策略可能含有版權音樂，發布至 IG / TikTok 可能遭靜音或下架。建議直接在發布平台套用官方音樂庫。
          </div>
        )}

        {/* 生成表單卡片 */}
        <div className="bg-surface border border-border rounded-2xl p-6">
          <GenerationForm submitLabel="🎬 開始生成影片" showProject />
        </div>

        {/* 導演對話面板：初次生成時即時呈現思考串流 / 工具旁白 / 中途提問（共用 ChatBox） */}
        {showChat && (
          <div className="mt-6 h-[440px] bg-surface border border-border rounded-2xl flex flex-col overflow-hidden">
            <ChatBox />
          </div>
        )}
      </div>
    </div>
  );
}
