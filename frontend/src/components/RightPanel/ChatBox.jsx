import React, { useState, useRef, useEffect } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
// 【新增】引入一些小圖示來裝飾對話泡泡
import { FaPaperPlane, FaUser, FaRobot, FaExclamationTriangle } from 'react-icons/fa';

export default function ChatBox() {
  const [chatInput, setChatInput] = useState('');
  // 【修改】把 chatHistory 也拿出來用
  const { isProcessing, submitPrompt, blueprint, chatHistory } = useBlueprintStore();
  
  // 【新增】用來控制捲動條的 Ref
  const scrollRef = useRef(null);

  // 【新增】每當對話紀錄更新、或是狀態變為處理中時，自動往下捲動到最新訊息
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatHistory, isProcessing]);

  const handleSend = (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    
    submitPrompt(true, chatInput);
    setChatInput(''); 
  };

  if (!blueprint) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-gray-500 text-sm text-center h-full bg-gray-900/50">
        <div className="border border-gray-800 rounded-2xl p-6 bg-gray-800/20">
          <span className="text-2xl block mb-3">💬</span>
          請先在上方設定並生成第一版影片，<br/>即可解鎖 AI 導演對話模式。
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-gray-900 h-full overflow-hidden">
      
      {/* 頂部狀態列 */}
      <div className="p-3 px-5 bg-gray-800/80 border-b border-gray-800 text-sm font-medium text-gray-300 shadow-sm flex items-center gap-2 shrink-0">
        <span className="animate-pulse">🟢</span> AI 導演已就緒：有什麼想修改的細節嗎？
      </div>
      
      {/* --- 【修改核心】歷史紀錄區 --- */}
      <div 
        ref={scrollRef} 
        className="flex-1 p-5 overflow-y-auto bg-gray-900/50 flex flex-col gap-5 scroll-smooth"
      >
        {chatHistory.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-2xl p-3.5 text-sm shadow-md ${
              msg.role === 'user' 
                ? 'bg-blue-600 text-white rounded-tr-sm' // 使用者：藍色泡泡靠右
                : msg.role === 'error'
                ? 'bg-red-900/50 text-red-200 border border-red-800/50 rounded-tl-sm' // 錯誤：紅色泡泡靠左
                : 'bg-gray-800 text-gray-200 border border-gray-700 rounded-tl-sm'    // AI：灰色泡泡靠左
            }`}>
              {/* 泡泡身份標籤 */}
              <div className="flex items-center gap-2 mb-1.5 opacity-60 text-[11px] font-bold uppercase tracking-wider">
                {msg.role === 'user' ? <FaUser /> : msg.role === 'error' ? <FaExclamationTriangle /> : <FaRobot />}
                {msg.role === 'user' ? 'You' : 'AI Director'}
              </div>
              {/* 泡泡內容 */}
              <div className="leading-relaxed whitespace-pre-wrap">{msg.content}</div>
            </div>
          </div>
        ))}

        {/* 正在思考時的動態「打字中」泡泡 */}
        {isProcessing && (
          <div className="flex justify-start">
            <div className="bg-gray-800 border border-gray-700 text-gray-400 rounded-2xl rounded-tl-sm p-4 text-sm flex items-center gap-2 shadow-md">
                <FaRobot className="opacity-60" />
                <span className="flex gap-1.5 ml-1">
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"></div>
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.15s' }}></div>
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.3s' }}></div>
                </span>
            </div>
          </div>
        )}
      </div>
      {/* ----------------------------- */}

      {/* 輸入區 */}
      <form onSubmit={handleSend} className="p-5 border-t border-gray-800 bg-gray-900 flex gap-3 shrink-0">
        <input 
          type="text" 
          placeholder="例如：把第二個畫面的節奏放慢..."
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          disabled={isProcessing}
          className="flex-1 bg-gray-800/80 text-white p-4 text-base rounded-xl border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none transition-colors shadow-inner placeholder-gray-500 disabled:opacity-50"
        />
        <button 
          type="submit"
          disabled={isProcessing || !chatInput.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-600 text-white px-6 rounded-xl flex items-center justify-center transition-all shadow-lg active:scale-95"
        >
          <FaPaperPlane className="text-lg" />
        </button>
      </form>
    </div>
  );
}