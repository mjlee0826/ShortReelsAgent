import React, { useState } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaPaperPlane } from 'react-icons/fa';

export default function ChatBox() {
  const [chatInput, setChatInput] = useState('');
  const { isProcessing, submitPrompt, blueprint } = useBlueprintStore();

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
      <div className="p-3 px-5 bg-gray-800/80 border-b border-gray-800 text-sm font-medium text-gray-300 shadow-sm flex items-center gap-2 shrink-0">
        <span className="animate-pulse">🟢</span> AI 導演已就緒：有什麼想修改的細節嗎？
      </div>
      
      {/* 歷史紀錄區：flex-1 讓它佔滿剩餘空間，overflow-y-auto 允許捲動 */}
      <div className="flex-1 p-5 overflow-y-auto bg-gray-900/50">
         {/* 目前先留空，你可以之後擴充顯示對話泡泡 */}
      </div>

      {/* 輸入區：放大框體與按鈕 */}
      <form onSubmit={handleSend} className="p-5 border-t border-gray-800 bg-gray-900 flex gap-3 shrink-0">
        {/* 【放大】p-4, text-base, rounded-xl */}
        <input 
          type="text" 
          placeholder="例如：把第二個畫面的節奏放慢..."
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          disabled={isProcessing}
          className="flex-1 bg-gray-800/80 text-white p-4 text-base rounded-xl border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none transition-colors shadow-inner placeholder-gray-500"
        />
        {/* 【放大】px-6 加寬按鈕 */}
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