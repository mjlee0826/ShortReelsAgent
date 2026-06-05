import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import useProjectStore from '../../store/useProjectStore';
import { FaFilm, FaLink, FaMagic, FaCheckSquare, FaRegSquare, FaMusic, FaSpinner, FaTimes } from 'react-icons/fa';
import { Input, Select, Button } from '../ui';

// 配樂策略選項（具名常數，避免散落 magic string）
const MUSIC_OPTIONS = [
  { value: 'search_copyright', label: '🎵 搜尋配樂（可能含版權）' },
  { value: 'search_free', label: '🆓 搜尋免費配樂 (Jamendo CC 授權)' },
  { value: 'none', label: '🔇 不加配樂（自行在發布平台套用）' },
];
const MUSIC_NONE = 'none';
const ALLOWED_AUDIO_ACCEPT = '.mp3,.wav,.m4a,.aac,.flac,.ogg';

/**
 * SidebarForm：AI 導演生成表單。
 *
 * 收集導演指令、範本網址、配樂策略與字幕 / 濾鏡開關後送出生成。
 * 影片分析策略已移除（需求 4），改由素材頁的逐檔 Simple/Complex 設定決定，編輯器直接沿用 assets 的分析結果。
 */
export default function SidebarForm() {
  const {
    userPrompt, templateSource,
    enableSubtitles, enableFilters,
    musicStrategy, uploadedMusicFile, isUploadingMusic,
    isProcessing, updateForm, submitPrompt, uploadMusic, clearUploadedMusic,
  } = useBlueprintStore();

  const currentProject = useProjectStore((s) => s.currentProject);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!userPrompt) {
      alert('請填寫剪輯指令！');
      return;
    }
    submitPrompt(false);
  };

  const handleMusicUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    uploadMusic(currentProject?.name, file);
    e.target.value = '';
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-6">
      {/* 1. 當前專案（唯讀標示）*/}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-ink-muted flex items-center gap-2">
          <FaFilm className="text-accent" /> 當前專案
        </label>
        <div className="bg-surface-2/60 text-ink-muted px-3.5 py-2.5 rounded-xl border border-border truncate select-none">
          {currentProject?.display_name || '—'}
          <span className="ml-2 text-xs text-ink-faint font-mono">{currentProject?.name}</span>
        </div>
      </div>

      {/* 2. Template 網址 */}
      <Input
        label="Template 網址 (選填)"
        icon={<FaLink />}
        value={templateSource}
        onChange={(e) => updateForm('templateSource', e.target.value)}
        placeholder="https://www.instagram.com/reel/..."
      />

      {/* 3. 配樂策略 + 自訂 BGM 上傳 */}
      <div className="flex flex-col gap-2">
        <Select
          label="配樂策略"
          icon={<FaMusic />}
          value={musicStrategy}
          onChange={(e) => updateForm('musicStrategy', e.target.value)}
          options={MUSIC_OPTIONS}
        />

        {musicStrategy !== MUSIC_NONE && (
          <div className="flex flex-col gap-1.5 mt-1">
            <label className="text-xs text-ink-faint px-1">📁 上傳自訂 BGM（選填，優先於搜尋策略）</label>
            {uploadedMusicFile ? (
              <div className="flex items-center gap-2 bg-success/10 border border-success/30 rounded-xl px-3 py-2">
                <span className="text-success text-sm flex-1 truncate">✓ {uploadedMusicFile}</span>
                <button
                  type="button"
                  onClick={clearUploadedMusic}
                  className="text-ink-faint hover:text-danger transition-colors shrink-0"
                  title="移除自訂音樂"
                >
                  <FaTimes />
                </button>
              </div>
            ) : (
              <label
                className={`flex items-center justify-center gap-2 p-2.5 rounded-xl border border-dashed border-border-strong cursor-pointer transition-colors text-sm text-ink-faint ${
                  isUploadingMusic ? 'opacity-50 cursor-not-allowed' : 'hover:border-accent hover:text-accent'
                }`}
              >
                {isUploadingMusic
                  ? <><FaSpinner className="animate-spin" /> 上傳中...</>
                  : '+ 選擇音訊檔案 (.mp3 / .wav / .m4a)'}
                <input
                  type="file"
                  accept={ALLOWED_AUDIO_ACCEPT}
                  onChange={handleMusicUpload}
                  disabled={isUploadingMusic}
                  className="hidden"
                />
              </label>
            )}
          </div>
        )}
      </div>

      {/* 4. 導演指令 */}
      <div className="flex flex-col gap-1.5 flex-1">
        <label className="text-sm font-medium text-ink-muted flex items-center gap-2">
          <FaMagic className="text-accent" /> 導演指令 (User Prompt)
        </label>
        <textarea
          rows="5"
          value={userPrompt}
          onChange={(e) => updateForm('userPrompt', e.target.value)}
          placeholder="請描述你想剪輯的風格、內容或音樂需求..."
          className="bg-surface-2 text-ink placeholder-ink-faint p-4 rounded-xl border border-border focus:border-accent focus:outline-none resize-none transition-colors flex-1 leading-relaxed"
        />
      </div>

      {/* 5. 功能勾選 */}
      <div className="flex gap-6 bg-surface-2/50 p-3 rounded-xl border border-border">
        <button
          type="button"
          onClick={() => updateForm('enableSubtitles', !enableSubtitles)}
          className="flex items-center gap-2 text-sm font-medium text-ink-muted hover:text-ink transition-colors"
        >
          {enableSubtitles ? <FaCheckSquare className="text-accent text-lg" /> : <FaRegSquare className="text-lg" />} 啟用字幕
        </button>
        <button
          type="button"
          onClick={() => updateForm('enableFilters', !enableFilters)}
          className="flex items-center gap-2 text-sm font-medium text-ink-muted hover:text-ink transition-colors"
        >
          {enableFilters ? <FaCheckSquare className="text-accent text-lg" /> : <FaRegSquare className="text-lg" />} 啟用濾鏡
        </button>
      </div>

      {/* 6. 提交 */}
      <Button type="submit" size="lg" fullWidth loading={isProcessing} className="mt-1">
        {isProcessing ? 'AI 導演思考中...' : '🎬 開始生成影片'}
      </Button>
    </form>
  );
}
