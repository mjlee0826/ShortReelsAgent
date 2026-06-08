import React, { useState, useRef, useEffect } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaPaperPlane, FaUser, FaRobot, FaExclamationTriangle } from 'react-icons/fa';

/**
 * ChatBox：AI 導演對話框。
 * 生成第一版藍圖後解鎖；可送出微調指令，顯示對話歷史與「思考中」動畫，並自動捲動到最新訊息。
 */
export default function ChatBox() {
  const [chatInput, setChatInput] = useState('');
  // 以 selector 個別訂閱：避免播放時每幀 playhead 更新造成整個對話框重繪
  const isProcessing = useBlueprintStore((s) => s.isProcessing);
  const submitPrompt = useBlueprintStore((s) => s.submitPrompt);
  const blueprint = useBlueprintStore((s) => s.blueprint);
  const chatHistory = useBlueprintStore((s) => s.chatHistory);
  const scrollRef = useRef(null);

  // 對話更新或進入處理中時自動捲到底
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [chatHistory, isProcessing]);

  const handleSend = (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    submitPrompt(true, chatInput);
    setChatInput('');
  };

  // 尚未生成藍圖：顯示鎖定提示
  if (!blueprint) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-ink-faint text-sm text-center h-full">
        <div className="border border-border rounded-2xl p-6 bg-surface-2/30">
          <span className="text-2xl block mb-3">💬</span>
          請先在上方設定並生成第一版影片，<br />即可解鎖 AI 導演對話模式。
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* 頂部狀態列 */}
      <div className="px-5 py-3 bg-surface-2/50 border-b border-border text-base font-medium text-ink-muted flex items-center gap-2 shrink-0">
        <span className="animate-pulse">🟢</span> AI 導演已就緒：有什麼想修改的細節嗎？
      </div>

      {/* 歷史紀錄 */}
      <div ref={scrollRef} className="flex-1 p-5 overflow-y-auto flex flex-col gap-5 scroll-smooth">
        {chatHistory.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-2xl p-4 text-base shadow-md ${
                msg.role === 'user'
                  ? 'bg-accent text-white rounded-tr-sm'
                  : msg.role === 'error'
                    ? 'bg-danger/15 text-danger border border-danger/30 rounded-tl-sm'
                    : 'bg-surface-2 text-ink border border-border rounded-tl-sm'
              }`}
            >
              <div className="flex items-center gap-2 mb-1.5 opacity-60 text-xs font-bold uppercase tracking-wider">
                {msg.role === 'user' ? <FaUser /> : msg.role === 'error' ? <FaExclamationTriangle /> : <FaRobot />}
                {msg.role === 'user' ? 'You' : 'AI Director'}
              </div>
              <div className="leading-relaxed whitespace-pre-wrap">{msg.content}</div>
            </div>
          </div>
        ))}

        {/* 思考中的「打字」動畫 */}
        {isProcessing && (
          <div className="flex justify-start">
            <div className="bg-surface-2 border border-border text-ink-muted rounded-2xl rounded-tl-sm p-4 text-sm flex items-center gap-2 shadow-md">
              <FaRobot className="opacity-60" />
              <span className="flex gap-1.5 ml-1">
                <div className="w-1.5 h-1.5 bg-accent rounded-full animate-bounce" />
                <div className="w-1.5 h-1.5 bg-accent rounded-full animate-bounce" style={{ animationDelay: '0.15s' }} />
                <div className="w-1.5 h-1.5 bg-accent rounded-full animate-bounce" style={{ animationDelay: '0.3s' }} />
              </span>
            </div>
          </div>
        )}
      </div>

      {/* 輸入區 */}
      <form onSubmit={handleSend} className="p-5 border-t border-border flex gap-3 shrink-0">
        <input
          type="text"
          placeholder="例如：把第二個畫面的節奏放慢..."
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          disabled={isProcessing}
          className="flex-1 bg-surface-2 text-ink text-base p-3.5 rounded-xl border border-border focus:border-accent focus:outline-none transition-colors placeholder-ink-faint disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={isProcessing || !chatInput.trim()}
          className="bg-accent hover:bg-accent-hover disabled:bg-surface-2 disabled:text-ink-faint text-white px-6 rounded-xl flex items-center justify-center transition-all shadow-lg active:scale-95"
        >
          <FaPaperPlane className="text-lg" />
        </button>
      </form>
    </div>
  );
}
