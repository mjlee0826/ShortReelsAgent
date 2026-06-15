import React, { useState, useRef, useEffect } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaPaperPlane, FaUser, FaRobot, FaExclamationTriangle, FaWrench, FaQuestionCircle } from 'react-icons/fa';

/**
 * ChatBox：AI 導演對話框（agentic 改造後）。
 *
 * 同時是「初次生成入口」與「對話微調」：未生成藍圖時第一則訊息即觸發生成，已生成則為微調。導演 agentic
 * loop 的即時認知（思考串流 liveThinking / 工具旁白 tool / 中途提問 clarification）都呈現在此；導演 ask_user
 * 時下方輸入與選項按鈕改走 B2 續跑（submitClarificationAnswer）。
 */
export default function ChatBox() {
  const [chatInput, setChatInput] = useState('');
  // 以 selector 個別訂閱，避免播放時每幀 playhead 更新造成整個對話框重繪
  const isProcessing = useBlueprintStore((s) => s.isProcessing);
  const submitPrompt = useBlueprintStore((s) => s.submitPrompt);
  const submitClarificationAnswer = useBlueprintStore((s) => s.submitClarificationAnswer);
  const blueprint = useBlueprintStore((s) => s.blueprint);
  const chatHistory = useBlueprintStore((s) => s.chatHistory);
  const liveThinking = useBlueprintStore((s) => s.liveThinking);
  const pendingClarification = useBlueprintStore((s) => s.pendingClarification);
  const scrollRef = useRef(null);

  // 對話更新 / 思考串流 / 進入處理中時自動捲到底
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [chatHistory, isProcessing, liveThinking]);

  // 送出：待回答 → 走 B2 續跑；尚無藍圖 → 初次生成；否則 → 對話微調
  const handleSend = (e) => {
    e.preventDefault();
    const text = chatInput.trim();
    if (!text) return;
    if (pendingClarification) {
      submitClarificationAnswer(text);
    } else if (!blueprint) {
      submitPrompt(false, text);
    } else {
      submitPrompt(true, text);
    }
    setChatInput('');
  };

  const headerText = !blueprint
    ? 'AI 導演：描述你想要的短影片，我來生成'
    : 'AI 導演已就緒：有什麼想修改的細節嗎？';
  const placeholder = pendingClarification
    ? '輸入你的回答…'
    : !blueprint
      ? '描述你想要的短影片，例如：做一支熱血的健身 vlog…'
      : '例如：把第二個畫面的節奏放慢…';

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* 頂部狀態列 */}
      <div className="px-5 py-3 bg-surface-2/50 border-b border-border text-base font-medium text-ink-muted flex items-center gap-2 shrink-0">
        <span className={isProcessing ? 'animate-pulse' : ''}>🟢</span> {headerText}
      </div>

      {/* 歷史紀錄 */}
      <div ref={scrollRef} className="flex-1 p-5 overflow-y-auto flex flex-col gap-4 scroll-smooth">
        {chatHistory.map((msg, idx) => {
          // 工具旁白：淡色小行（導演「做了什麼」的軌跡）
          if (msg.role === 'tool') {
            return (
              <div key={idx} className="flex justify-start">
                <div className="flex items-center gap-2 text-xs text-ink-faint italic px-1">
                  <FaWrench className="opacity-50" /> {msg.content}
                </div>
              </div>
            );
          }
          // 中途提問：強調框 + 選項按鈕（僅在待回答時可點，回答後按鈕隱藏）
          if (msg.role === 'clarification') {
            return (
              <div key={idx} className="flex justify-start">
                <div className="max-w-[90%] rounded-2xl rounded-tl-sm p-4 bg-accent/10 border border-accent/30 text-ink shadow-md">
                  <div className="flex items-center gap-2 mb-1.5 text-accent text-xs font-bold uppercase tracking-wider">
                    <FaQuestionCircle /> AI 導演想確認
                  </div>
                  <div className="leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                  {pendingClarification && Array.isArray(msg.options) && msg.options.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-3">
                      {msg.options.map((opt, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => submitClarificationAnswer(opt)}
                          className="px-3.5 py-1.5 text-sm bg-accent text-white rounded-lg hover:bg-accent-hover transition-colors active:scale-95"
                        >
                          {opt}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          }
          // user / error / system（assistant 預設）
          return (
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
          );
        })}

        {/* 即時思考串流泡泡（有 liveThinking 時顯示推理；無則退回打字動畫） */}
        {isProcessing && liveThinking && (
          <div className="flex justify-start">
            <div className="max-w-[90%] bg-surface-2/60 border border-border/60 text-ink-muted rounded-2xl rounded-tl-sm p-4 text-sm shadow-sm">
              <div className="flex items-center gap-2 mb-1.5 opacity-50 text-xs font-bold uppercase tracking-wider">
                <FaRobot /> 思考中…
              </div>
              <div className="leading-relaxed whitespace-pre-wrap italic opacity-80">{liveThinking}</div>
            </div>
          </div>
        )}
        {isProcessing && !liveThinking && (
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

      {/* 輸入區（待回答時提示走續跑） */}
      <form onSubmit={handleSend} className="p-5 border-t border-border flex gap-3 shrink-0">
        <input
          type="text"
          placeholder={placeholder}
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
