import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
// 新增 FaBrain 圖示
import { FaFilm, FaLink, FaMagic, FaCheckSquare, FaRegSquare, FaBrain } from 'react-icons/fa';

export default function SidebarForm() {
  const { 
    assetFolderName, userPrompt, templateSource, 
    enableSubtitles, enableFilters, videoStrategy, // 取得 strategy
    isProcessing, updateForm, submitPrompt 
  } = useBlueprintStore();

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!assetFolderName || !userPrompt) {
      alert('請填寫資料夾名稱與剪輯指令！');
      return;
    }
    submitPrompt(false);
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-6 border-b border-gray-700 bg-gray-900">
      
      {/* 1. 素材資料夾 */}
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-400 flex items-center gap-2">
          <FaFilm /> 素材資料夾名稱
        </label>
        <input 
          type="text" 
          value={assetFolderName}
          onChange={(e) => updateForm('assetFolderName', e.target.value)}
          className="bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
        />
      </div>

      {/* 2. 影片處理策略 (新增的下拉選單) */}
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-400 flex items-center gap-2">
          <FaBrain /> 影片分析策略
        </label>
        <select 
          value={videoStrategy}
          onChange={(e) => updateForm('videoStrategy', e.target.value)}
          className="bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none cursor-pointer"
        >
          <option value="2">策略 2：一般模式 (本地 Qwen 分析)</option>
          <option value="1">策略 1：Complex 模式 (Gemini 深度索引)</option>
        </select>
        <p className="text-[10px] text-gray-500 px-1">
          {videoStrategy === '1' ? '✨ 適合包含重要動作或對話的長影片 (消耗 API 額度)' : '🚀 適合快速處理簡單素材 (本地執行)'}
        </p>
      </div>

      {/* 3. Template 網址 */}
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-400 flex items-center gap-2">
          <FaLink /> Template 網址 (選填)
        </label>
        <input 
          type="text" 
          value={templateSource}
          onChange={(e) => updateForm('templateSource', e.target.value)}
          className="bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
        />
      </div>

      {/* 4. 導演指令 */}
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-400 flex items-center gap-2">
          <FaMagic /> 導演指令 (User Prompt)
        </label>
        <textarea 
          rows="3"
          value={userPrompt}
          onChange={(e) => updateForm('userPrompt', e.target.value)}
          className="bg-gray-800 text-white p-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none resize-none"
        />
      </div>

      {/* 5. 功能勾選 */}
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

      {/* 6. 提交按鈕 */}
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