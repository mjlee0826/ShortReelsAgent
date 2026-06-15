import React from 'react';
import useBlueprintStore from '../../store/useBlueprintStore';
import useProjectStore from '../../store/useProjectStore';
import { FaFilm, FaLink, FaMagic, FaCheckSquare, FaRegSquare, FaMusic } from 'react-icons/fa';
import { Input, Select, Button } from '../ui';
import { makeMusicOptions, MUSIC_NONE } from '../../constants/music';
import MusicUploadField from './MusicUploadField';

// 配樂策略選項（none 標籤：生成情境用「不加配樂」）
const MUSIC_OPTIONS = makeMusicOptions('🔇 不加配樂（自行在發布平台套用）');
const PROMPT_ROWS = 5;

/**
 * GenerationForm：AI 導演生成 / 重新生成的共用表單（DRY）。
 *
 * 收集導演指令、範本網址、配樂策略與字幕 / 濾鏡開關後送出生成。
 * 屬「重新生成」邊界（需 AI 重新推理），統一呼叫 submitPrompt(false)；目前由 RegeneratePanel 使用
 *（初始生成已改由工作台的 Pilot 對話直接下指令，不再經本表單）。
 *
 * @param {string} submitLabel 送出按鈕文字
 * @param {boolean} showProject 是否顯示當前專案唯讀列（初始生成顯示、重新生成可省）
 * @param {() => void} onSubmitted 送出後回呼（例如關閉 Modal）
 */
export default function GenerationForm({ submitLabel = '🎬 開始生成影片', showProject = true, onSubmitted }) {
  const {
    userPrompt, templateSource,
    enableSubtitles, enableFilters,
    musicStrategy, uploadedMusicFile, isUploadingMusic,
    isProcessing, generationStage, updateForm, submitPrompt, uploadMusic, clearUploadedMusic,
  } = useBlueprintStore();

  const currentProject = useProjectStore((s) => s.currentProject);

  // 送出前驗證指令非空；送出後立即回呼（loading 遮罩由工作台顯示）
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!userPrompt) {
      alert('請填寫剪輯指令！');
      return;
    }
    submitPrompt(false);
    onSubmitted?.();
  };

  const handleMusicUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    uploadMusic(currentProject?.name, file);
    e.target.value = '';
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      {/* 1. 當前專案（唯讀標示）*/}
      {showProject && (
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-ink-muted flex items-center gap-2">
            <FaFilm className="text-accent" /> 當前專案
          </label>
          <div className="bg-surface-2/60 text-ink-muted px-3.5 py-2.5 rounded-xl border border-border truncate select-none">
            {currentProject?.display_name || '—'}
            <span className="ml-2 text-xs text-ink-faint font-mono">{currentProject?.name}</span>
          </div>
        </div>
      )}

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
          <MusicUploadField
            uploadedFile={uploadedMusicFile}
            isUploading={isUploadingMusic}
            onSelectFile={handleMusicUpload}
            onClear={clearUploadedMusic}
            label="📁 上傳自訂 BGM（選填，優先於搜尋策略）"
            labelClassName="text-xs text-ink-faint px-1"
            className="mt-1"
          />
        )}
      </div>

      {/* 4. 導演指令 */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-ink-muted flex items-center gap-2">
          <FaMagic className="text-accent" /> 導演指令 (User Prompt)
        </label>
        <textarea
          rows={PROMPT_ROWS}
          value={userPrompt}
          onChange={(e) => updateForm('userPrompt', e.target.value)}
          placeholder="請描述你想剪輯的風格、內容或音樂需求..."
          className="bg-surface-2 text-ink placeholder-ink-faint p-4 rounded-xl border border-border focus:border-accent focus:outline-none resize-none transition-colors leading-relaxed"
        />
      </div>

      {/* 5. 功能勾選 */}
      <div className="flex flex-wrap gap-x-6 gap-y-2 bg-surface-2/50 p-3 rounded-xl border border-border">
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
        {/* 自動運鏡 / 卡點改為編輯器「專案 / 輸出」面板的即時開關（render-time 視覺效果，免重新生成）*/}
      </div>

      {/* 6. 提交（生成中顯示 WS 即時階段文案：下載配樂 / 範本語意分析 / 聽寫中…，兩分支交錯更新） */}
      <Button type="submit" size="lg" fullWidth loading={isProcessing} className="mt-1">
        {isProcessing
          ? (generationStage ? `生成中：${generationStage}…` : 'AI 導演思考中...')
          : submitLabel}
      </Button>
    </form>
  );
}
