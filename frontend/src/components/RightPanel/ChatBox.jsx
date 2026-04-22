import React, { useState } from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaPaperPlane } from 'react-icons/fa';

export default function ChatBox() {
  const [chatInput, setChatInput] = useState('');
  const { isProcessing, submitPrompt, blueprint } = useBlueprintStore();

  const handleSend = (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    
    // 傳遞 true 代表這是「微調」，並附上使用者的對話內容
    submitPrompt(true, chatInput);
    setChatInput(''); // 清空輸入框
  };

  // 如果還沒有生成劇本，先隱藏對話框，保持介面乾淨
  if (!blueprint) {
    return (
      <div className="flex-1 flex items-center justify-center p-6 text-gray-500 text-sm text-center">
        請先在上方設定並生成第一版影片，<br/>即可開啟 AI 導演對話模式。
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-gray-900 border-t border-gray-800">
      <div className="p-4 bg-gray-800 text-sm text-gray-300 shadow-md">
        💬 <strong>AI 導演已就緒</strong>：有什麼想修改的細節嗎？
      </div>
      
      {/* 這裡是未來的對話歷史紀錄區 (擴充預留) */}
      <div className="flex-1 p-4 overflow-y-auto">
         {/* 目前先留空，你可以之後擴充顯示對話泡泡 */}
      </div>

      {/* 輸入區 */}
      <form onSubmit={handleSend} className="p-4 border-t border-gray-700 bg-gray-900 flex gap-2">
        <input 
          type="text" 
          placeholder="例如：把第二個畫面的節奏放慢..."
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          disabled={isProcessing}
          className="flex-1 bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
        />
        <button 
          type="submit"
          disabled={isProcessing || !chatInput.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 text-white p-3 rounded flex items-center justify-center transition-colors"
        >
          <FaPaperPlane />
        </button>
      </form>
    </div>
  );
}