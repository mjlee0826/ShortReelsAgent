import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaFilm, FaLink, FaMagic, FaCheckSquare, FaRegSquare } from 'react-icons/fa';

export default function SidebarForm() {
  // 從 Zustand 取出狀態與更新方法
  const { 
    assetFolderName, userPrompt, templateSource, 
    enableSubtitles, enableFilters, isProcessing, 
    updateForm, submitPrompt 
  } = useBlueprintStore();

  // 處理表單送出
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!assetFolderName || !userPrompt) {
      alert('請填寫資料夾名稱與剪輯指令！');
      return;
    }
    submitPrompt(false); // false 代表這是「首次生成」，不是微調
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-6 border-b border-gray-700 bg-gray-900">
      
      {/* 1. 資料夾名稱輸入 */}
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-400 flex items-center gap-2">
          <FaFilm /> 素材資料夾名稱
        </label>
        <input 
          type="text" 
          placeholder="例如: snowman"
          value={assetFolderName}
          onChange={(e) => updateForm('assetFolderName', e.target.value)}
          className="bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
        />
      </div>

      {/* 2. Template 輸入 */}
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-400 flex items-center gap-2">
          <FaLink /> Template 網址 (選填)
        </label>
        <input 
          type="text" 
          placeholder="輸入 IG Reels 或 YT Shorts 網址"
          value={templateSource}
          onChange={(e) => updateForm('templateSource', e.target.value)}
          className="bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
        />
      </div>

      {/* 3. 剪輯指令 (User Prompt) */}
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-400 flex items-center gap-2">
          <FaMagic /> 導演指令 (User Prompt)
        </label>
        <textarea 
          rows="3"
          placeholder="例如：幫我剪一支熱血的 Vlog，配合快節奏音樂..."
          value={userPrompt}
          onChange={(e) => updateForm('userPrompt', e.target.value)}
          className="bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none resize-none"
        />
      </div>

      {/* 4. 功能勾選框 (字幕與濾鏡) */}
      <div className="flex gap-4 mt-2">
        <button 
          type="button"
          onClick={() => updateForm('enableSubtitles', !enableSubtitles)}
          className="flex items-center gap-2 text-sm text-gray-300 hover:text-white"
        >
          {enableSubtitles ? <FaCheckSquare className="text-blue-500"/> : <FaRegSquare />} 啟用字幕
        </button>
        <button 
          type="button"
          onClick={() => updateForm('enableFilters', !enableFilters)}
          className="flex items-center gap-2 text-sm text-gray-300 hover:text-white"
        >
          {enableFilters ? <FaCheckSquare className="text-blue-500"/> : <FaRegSquare />} 啟用濾鏡
        </button>
      </div>

      {/* 5. 提交按鈕 */}
      <button 
        type="submit" 
        disabled={isProcessing}
        className={`mt-4 py-2 rounded font-bold transition-colors ${
          isProcessing ? 'bg-gray-600 text-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-500 text-white'
        }`}
      >
        {isProcessing ? 'AI 導演思考中...' : '🎬 開始生成影片'}
      </button>
    </form>
  );
}