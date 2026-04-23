import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaFilm, FaLink, FaMagic, FaCheckSquare, FaRegSquare, FaBrain } from 'react-icons/fa';

export default function SidebarForm() {
  const { 
    assetFolderName, userPrompt, templateSource, 
    enableSubtitles, enableFilters, videoStrategy, 
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
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-6">
      
      {/* 1. 素材資料夾 */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <FaFilm className="text-blue-400" /> 素材資料夾名稱
        </label>
        {/* 【放大】p-3, text-base, rounded-lg */}
        <input 
          type="text" 
          value={assetFolderName}
          onChange={(e) => updateForm('assetFolderName', e.target.value)}
          className="bg-gray-800/80 text-white p-3 text-base rounded-lg border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none transition-colors shadow-inner"
        />
      </div>

      {/* 2. 影片處理策略 */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <FaBrain className="text-blue-400" /> 影片分析策略
        </label>
        {/* 【放大】p-3, text-base, rounded-lg */}
        <select 
          value={videoStrategy}
          onChange={(e) => updateForm('videoStrategy', e.target.value)}
          className="bg-gray-800/80 text-white p-3 text-base rounded-lg border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none cursor-pointer transition-colors shadow-inner"
        >
          <option value="2">策略 2：一般模式 (本地 Qwen 分析)</option>
          <option value="1">策略 1：Complex 模式 (Gemini 深度索引)</option>
        </select>
        <p className="text-[11px] text-gray-500 px-1 font-mono mt-1">
          {videoStrategy === '1' ? '✨ 適合包含重要動作或對話的長影片' : '🚀 適合快速處理簡單素材 (本地執行)'}
        </p>
      </div>

      {/* 3. Template 網址 */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <FaLink className="text-blue-400" /> Template 網址 (選填)
        </label>
        <input 
          type="text" 
          value={templateSource}
          onChange={(e) => updateForm('templateSource', e.target.value)}
          placeholder="https://www.instagram.com/reel/..."
          className="bg-gray-800/80 text-white p-3 text-base rounded-lg border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none transition-colors shadow-inner placeholder-gray-600"
        />
      </div>

      {/* 4. 導演指令 */}
      <div className="flex flex-col gap-1.5 flex-1">
        <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <FaMagic className="text-blue-400" /> 導演指令 (User Prompt)
        </label>
        {/* 【放大】將 rows 增加為 5，並加大字體與 padding */}
        <textarea 
          rows="5"
          value={userPrompt}
          onChange={(e) => updateForm('userPrompt', e.target.value)}
          placeholder="請描述你想剪輯的風格、內容或音樂需求..."
          className="bg-gray-800/80 text-white p-4 text-base rounded-lg border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none resize-none transition-colors shadow-inner flex-1 leading-relaxed"
        />
      </div>

      {/* 5. 功能勾選 */}
      <div className="flex gap-6 mt-1 bg-gray-800/40 p-3 rounded-lg border border-gray-800">
        <button 
          type="button"
          onClick={() => updateForm('enableSubtitles', !enableSubtitles)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
        >
          {enableSubtitles ? <FaCheckSquare className="text-blue-500 text-lg"/> : <FaRegSquare className="text-lg" />} 啟用字幕
        </button>
        <button 
          type="button"
          onClick={() => updateForm('enableFilters', !enableFilters)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
        >
          {enableFilters ? <FaCheckSquare className="text-blue-500 text-lg"/> : <FaRegSquare className="text-lg" />} 啟用濾鏡
        </button>
      </div>

      {/* 6. 提交按鈕 */}
      {/* 【放大】py-3.5 增加高度，文字改為 text-lg */}
      <button 
        type="submit" 
        disabled={isProcessing}
        className={`mt-2 py-3.5 text-lg rounded-xl font-bold tracking-wide transition-all shadow-lg ${
          isProcessing ? 'bg-gray-700 text-gray-400 cursor-not-allowed border border-gray-600' : 'bg-blue-600 hover:bg-blue-500 text-white hover:shadow-blue-500/20 active:scale-[0.98]'
        }`}
      >
        {isProcessing ? 'AI 導演思考中...' : '🎬 開始生成影片'}
      </button>
    </form>
  );
}