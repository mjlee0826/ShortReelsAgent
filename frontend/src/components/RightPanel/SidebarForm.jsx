import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import { FaFilm, FaLink, FaMagic, FaCheckSquare, FaRegSquare, FaBrain, FaMusic, FaSpinner, FaTimes } from 'react-icons/fa';

export default function SidebarForm() {
  const {
    assetFolderName, userPrompt, templateSource,
    enableSubtitles, enableFilters, videoStrategy,
    musicStrategy, uploadedMusicFile, isUploadingMusic,
    isProcessing, updateForm, submitPrompt, uploadMusic, clearUploadedMusic,
  } = useBlueprintStore();

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!assetFolderName || !userPrompt) {
      alert('請填寫資料夾名稱與剪輯指令！');
      return;
    }
    submitPrompt(false);
  };

  const handleMusicUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    uploadMusic(assetFolderName, file);
    // 清空 input 值，允許重複選同一個檔案
    e.target.value = '';
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-6">

      {/* 1. 素材資料夾 */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <FaFilm className="text-blue-400" /> 素材資料夾名稱
        </label>
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

      {/* 4. 配樂策略 */}
      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <FaMusic className="text-blue-400" /> 配樂策略
        </label>
        <select
          value={musicStrategy}
          onChange={(e) => updateForm('musicStrategy', e.target.value)}
          className="bg-gray-800/80 text-white p-3 text-base rounded-lg border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none cursor-pointer transition-colors shadow-inner"
        >
          <option value="search_copyright">🎵 搜尋配樂（可能含版權）</option>
          <option value="search_free">🆓 搜尋免費配樂 (Jamendo CC 授權)</option>
          <option value="none">🔇 不加配樂（自行在發布平台套用）</option>
        </select>

        {/* 自訂 BGM 上傳：strategy 為 none 時隱藏 */}
        {musicStrategy !== 'none' && (
          <div className="flex flex-col gap-1.5 mt-1">
            <label className="text-xs text-gray-400 px-1">
              📁 上傳自訂 BGM（選填，優先於搜尋策略）
            </label>
            {uploadedMusicFile ? (
              /* 已上傳：顯示檔名與清除按鈕 */
              <div className="flex items-center gap-2 bg-green-900/30 border border-green-700/50 rounded-lg px-3 py-2">
                <span className="text-green-400 text-sm flex-1 truncate">✓ {uploadedMusicFile}</span>
                <button
                  type="button"
                  onClick={clearUploadedMusic}
                  className="text-gray-500 hover:text-red-400 transition-colors shrink-0"
                  title="移除自訂音樂"
                >
                  <FaTimes />
                </button>
              </div>
            ) : (
              /* 未上傳：顯示上傳按鈕 */
              <label className={`flex items-center justify-center gap-2 p-2.5 rounded-lg border border-dashed border-gray-600 cursor-pointer transition-colors text-sm text-gray-400 ${isUploadingMusic ? 'opacity-50 cursor-not-allowed' : 'hover:border-blue-500 hover:text-blue-400'}`}>
                {isUploadingMusic
                  ? <><FaSpinner className="animate-spin" /> 上傳中...</>
                  : '+ 選擇音訊檔案 (.mp3 / .wav / .m4a)'
                }
                <input
                  type="file"
                  accept=".mp3,.wav,.m4a,.aac,.flac,.ogg"
                  onChange={handleMusicUpload}
                  disabled={isUploadingMusic}
                  className="hidden"
                />
              </label>
            )}
          </div>
        )}
      </div>

      {/* 5. 導演指令 */}
      <div className="flex flex-col gap-1.5 flex-1">
        <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <FaMagic className="text-blue-400" /> 導演指令 (User Prompt)
        </label>
        <textarea
          rows="5"
          value={userPrompt}
          onChange={(e) => updateForm('userPrompt', e.target.value)}
          placeholder="請描述你想剪輯的風格、內容或音樂需求..."
          className="bg-gray-800/80 text-white p-4 text-base rounded-lg border border-gray-700 focus:border-blue-500 focus:bg-gray-800 focus:outline-none resize-none transition-colors shadow-inner flex-1 leading-relaxed"
        />
      </div>

      {/* 6. 功能勾選 */}
      <div className="flex gap-6 mt-1 bg-gray-800/40 p-3 rounded-lg border border-gray-800">
        <button
          type="button"
          onClick={() => updateForm('enableSubtitles', !enableSubtitles)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
        >
          {enableSubtitles ? <FaCheckSquare className="text-blue-500 text-lg" /> : <FaRegSquare className="text-lg" />} 啟用字幕
        </button>
        <button
          type="button"
          onClick={() => updateForm('enableFilters', !enableFilters)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
        >
          {enableFilters ? <FaCheckSquare className="text-blue-500 text-lg" /> : <FaRegSquare className="text-lg" />} 啟用濾鏡
        </button>
      </div>

      {/* 7. 提交按鈕 */}
      <button
        type="submit"
        disabled={isProcessing}
        className={`mt-2 py-3.5 text-lg rounded-xl font-bold tracking-wide transition-all shadow-lg ${
          isProcessing
            ? 'bg-gray-700 text-gray-400 cursor-not-allowed border border-gray-600'
            : 'bg-blue-600 hover:bg-blue-500 text-white hover:shadow-blue-500/20 active:scale-[0.98]'
        }`}
      >
        {isProcessing ? 'AI 導演思考中...' : '🎬 開始生成影片'}
      </button>
    </form>
  );
}
