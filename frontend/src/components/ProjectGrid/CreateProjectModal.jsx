import React, { useState } from 'react';
import { FaGoogleDrive, FaFolderOpen, FaCheckCircle } from 'react-icons/fa';
import { Modal, Input, Button } from '../ui';
import { ACCEPTED_MEDIA_ACCEPT, filterMediaFiles } from '../../constants/media';

/**
 * CreateProjectModal：建立新專案對話框。
 *
 * 提供兩種來源（以分頁切換）：
 *  - Drive：貼公開資料夾連結，後端背景同步下載素材 + Phase 1。
 *  - 本機資料夾（空白專案）：直接上傳整個資料夾，後端存入 raw/ 並依設定背景跑 Phase 1。
 */

// 建立來源模式（具名常數，避免 magic string 散落）
const CREATE_MODE = { DRIVE: 'drive', FOLDER: 'folder' };

export default function CreateProjectModal({ onClose, onCreate, onCreateFromFolder }) {
  const [mode, setMode] = useState(CREATE_MODE.DRIVE);
  const [displayName, setDisplayName] = useState('');
  const [driveLink, setDriveLink] = useState('');
  const [mediaFiles, setMediaFiles] = useState([]); // 已過濾出的受支援媒體檔
  const [folderName, setFolderName] = useState(''); // 所選資料夾名（供顯示）
  const [isCreating, setIsCreating] = useState(false);

  const isDrive = mode === CREATE_MODE.DRIVE;
  const canSubmit = isDrive
    ? displayName.trim() && driveLink.trim()
    : displayName.trim() && mediaFiles.length > 0;

  // 選資料夾：webkitdirectory 會帶整夾（含子夾）檔案；先濾出受支援媒體並記錄資料夾名供顯示
  const handleSelectFolder = (e) => {
    const all = Array.from(e.target.files || []);
    setMediaFiles(filterMediaFiles(all));
    // webkitRelativePath 形如 "MyFolder/sub/a.jpg"，取第一段作為資料夾名
    const firstPath = all[0]?.webkitRelativePath || '';
    setFolderName(firstPath.split('/')[0] || '');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setIsCreating(true);
    try {
      if (isDrive) {
        await onCreate(displayName.trim(), driveLink.trim());
      } else {
        await onCreateFromFolder(displayName.trim(), mediaFiles);
      }
      onClose();
    } catch {
      // 失敗訊息由 store 寫入 errorMsg，這裡僅恢復可再次送出狀態
      setIsCreating(false);
    }
  };

  // 分頁按鈕樣式（選中為實心、未選中為弱化），集中於此避免 inline 重複
  const tabClass = (active) =>
    `flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
      active ? 'bg-accent text-white shadow-sm' : 'text-ink-muted hover:text-ink'
    }`;

  return (
    <Modal title="建立新專案" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {/* 來源分頁切換 */}
        <div className="flex gap-1 p-1 bg-surface-2 rounded-xl">
          <button type="button" className={tabClass(isDrive)} onClick={() => setMode(CREATE_MODE.DRIVE)}>
            <FaGoogleDrive /> Google Drive 連結
          </button>
          <button type="button" className={tabClass(!isDrive)} onClick={() => setMode(CREATE_MODE.FOLDER)}>
            <FaFolderOpen /> 上傳資料夾
          </button>
        </div>

        <Input
          label="專案名稱"
          autoFocus
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="例：婚禮精華 2025"
          maxLength={60}
        />

        {isDrive ? (
          <Input
            label="Google Drive 資料夾連結"
            icon={<FaGoogleDrive />}
            value={driveLink}
            onChange={(e) => setDriveLink(e.target.value)}
            placeholder="https://drive.google.com/drive/folders/..."
            hint="請將資料夾分享設為「知道連結的任何人皆可檢視」；建立後素材會於背景自動下載並分析。"
          />
        ) : (
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-ink-muted flex items-center gap-2">
              <span className="text-accent"><FaFolderOpen /></span>
              本機資料夾
            </label>
            {mediaFiles.length > 0 ? (
              // 已選：顯示資料夾名與通過過濾的媒體檔數，並可重新選擇
              <label className="flex items-center gap-2 bg-success/10 border border-success/30 rounded-xl px-3 py-2.5 cursor-pointer">
                <FaCheckCircle className="text-success shrink-0" />
                <span className="text-success text-sm flex-1 truncate">
                  {folderName ? `${folderName}／` : ''}已選 {mediaFiles.length} 個媒體檔
                </span>
                <span className="text-xs text-ink-faint shrink-0">重新選擇</span>
                <input
                  type="file"
                  webkitdirectory=""
                  directory=""
                  multiple
                  accept={ACCEPTED_MEDIA_ACCEPT}
                  onChange={handleSelectFolder}
                  className="hidden"
                />
              </label>
            ) : (
              // 未選：虛線選擇框
              <label className="flex items-center justify-center gap-2 p-3 rounded-xl border border-dashed border-border-strong cursor-pointer transition-colors text-sm text-ink-faint hover:border-accent hover:text-accent">
                + 選擇一個資料夾（含圖片／影片）
                <input
                  type="file"
                  webkitdirectory=""
                  directory=""
                  multiple
                  accept={ACCEPTED_MEDIA_ACCEPT}
                  onChange={handleSelectFolder}
                  className="hidden"
                />
              </label>
            )}
            <p className="text-xs text-ink-faint px-0.5 leading-relaxed">
              將上傳資料夾內的圖片／影片，非媒體檔會自動略過；建立後依設定在背景分析。
            </p>
          </div>
        )}

        <div className="flex justify-end gap-3 mt-1">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={!canSubmit} loading={isCreating}>建立專案</Button>
        </div>
      </form>
    </Modal>
  );
}
