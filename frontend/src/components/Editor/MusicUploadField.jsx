import React from 'react';
import { FaSpinner, FaTimes } from 'react-icons/fa';
import { ALLOWED_AUDIO_ACCEPT } from '../../constants/music';

/**
 * MusicUploadField：自訂 BGM 上傳欄位（純呈現元件）。
 *
 * 封裝「已上傳 → 綠色檔名膠囊 + 移除鈕」與「未上傳 → 虛線上傳框 + 上傳中 spinner」這段
 * 先前在 GenerationForm 與 ChangeMusicModal 重複的 UI。元件本身不碰 store，
 * 由父層接 useBlueprintStore 的上傳狀態與動作。
 *
 * @param {string|null} uploadedFile 已上傳的檔名（null 代表尚未上傳）
 * @param {boolean} isUploading 是否上傳中（顯示 spinner、禁用輸入）
 * @param {(e: Event) => void} onSelectFile 選檔事件處理（父層負責呼叫上傳）
 * @param {() => void} onClear 移除已上傳檔案
 * @param {string} label 欄位上方的說明文字
 * @param {string} [labelClassName] 說明文字的樣式（兩呼叫端略有差異）
 * @param {string} [className] 外層容器附加樣式
 */
export default function MusicUploadField({
  uploadedFile,
  isUploading,
  onSelectFile,
  onClear,
  label,
  labelClassName = 'text-sm text-ink-muted',
  className = '',
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label className={labelClassName}>{label}</label>
      {uploadedFile ? (
        // 已上傳：顯示檔名與移除鈕
        <div className="flex items-center gap-2 bg-success/10 border border-success/30 rounded-xl px-3 py-2">
          <span className="text-success text-sm flex-1 truncate">✓ {uploadedFile}</span>
          <button
            type="button"
            onClick={onClear}
            className="text-ink-faint hover:text-danger transition-colors shrink-0"
            title="移除自訂音樂"
          >
            <FaTimes />
          </button>
        </div>
      ) : (
        // 未上傳：虛線上傳框（上傳中時轉圈並禁用）
        <label
          className={`flex items-center justify-center gap-2 p-2.5 rounded-xl border border-dashed border-border-strong cursor-pointer transition-colors text-sm text-ink-faint ${
            isUploading ? 'opacity-50 cursor-not-allowed' : 'hover:border-accent hover:text-accent'
          }`}
        >
          {isUploading
            ? <><FaSpinner className="animate-spin" /> 上傳中...</>
            : '+ 選擇音訊檔案 (.mp3 / .wav / .m4a)'}
          <input
            type="file"
            accept={ALLOWED_AUDIO_ACCEPT}
            onChange={onSelectFile}
            disabled={isUploading}
            className="hidden"
          />
        </label>
      )}
    </div>
  );
}
